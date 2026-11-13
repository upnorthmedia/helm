/*
 * The Helm deck on the Waveshare ESP32-P4-WIFI6-Touch-LCD-5, turned landscape.
 *
 * One task, the deck task, owns the deck state (firmware/core/helm_deck.h is
 * single-threaded): it reads frames from the link, applies touch and control
 * input, runs the deck's timers, drives the lights and chime, and redraws
 * the screen. Touch handlers run in the LVGL task and only queue input here.
 */
#include <stddef.h>
#include <stdint.h>

#include "bsp/esp-bsp.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "sdkconfig.h"

#include "helm_deck.h"
#include "io.h"
#include "link.h"
#include "ui.h"

static const char *TAG = "helm";

#define FIRMWARE "helm-idf-0.1"
#define LOOP_MS 20       /* longest wait for bytes; the deck needs a tick at least every 100 ms */
#define DRAW_EVERY_MS 33 /* about 30 frames a second for the hold bar */
#define KEY_INPUT_WAIT_MS 500 /* longest a key input waits for room in the queue */
#define DECK_TASK_STACK (12 * 1024)
#define DECK_TASK_PRIORITY 5

/* What this deck has, for hello: the screen and touch, then whatever io_start
 * brought up (keys-4 always, on screen or as switches; knob, lightbar-8, chime). */
static const char *s_caps[8] = {"screen-1280x720", "touch"};
static size_t s_cap_count = 2;

static helm_deck_t s_deck; /* about 31 KB: static, not on a stack */
static QueueHandle_t s_inputs;

/*
 * Start the screen and touch turned landscape: the panel is 720 x 1280
 * portrait, and ui.c lays out 1280 x 720. The LVGL adapter turns the picture
 * as it copies to the panel, so the touch points are turned to match here
 * (esp_lcd_touch mirrors against the panel's 720 x 1280, then swaps). Turned,
 * the adapter's default triple-partial mode can freeze on the P4 with
 * ESP-IDF's unpatched PPA driver (esp_lvgl_adapter README, "PPA Freeze Fix"),
 * so the screen uses double-direct, which also suits a UI that changes in
 * small areas. Either way the adapter needs three frame buffers, the board
 * package's default (CONFIG_BSP_LCD_DPI_BUFFER_NUMS).
 */
static lv_display_t *display_start(void)
{
    bsp_display_cfg_t cfg = {
        .lv_adapter_cfg = ESP_LV_ADAPTER_DEFAULT_CONFIG(),
        .tear_avoid_mode = ESP_LV_ADAPTER_TEAR_AVOID_MODE_DOUBLE_DIRECT,
    };
#if CONFIG_HELM_ROTATE_CASE
    cfg.rotation = ESP_LV_ADAPTER_ROTATE_270;
    cfg.touch_flags.mirror_y = 1;
    cfg.touch_flags.swap_xy = 1;
#else
    cfg.rotation = ESP_LV_ADAPTER_ROTATE_90;
    cfg.touch_flags.mirror_x = 1;
    cfg.touch_flags.swap_xy = 1;
#endif
    return bsp_display_start_with_config(&cfg);
}

/*
 * The board package's bsp_display_lock() (1.0.4) returns esp_lv_adapter_lock()'s
 * esp_err_t as a bool, so it reads false when the lock is taken and true when it
 * is not. Ask the adapter directly; release with bsp_display_unlock() as usual.
 */
static bool display_lock(int32_t timeout_ms)
{
    return esp_lv_adapter_lock(timeout_ms) == ESP_OK;
}

static uint32_t now_ms(void)
{
    return (uint32_t)(esp_timer_get_time() / 1000); /* wraps after 49 days; the core allows it */
}

static void emit(void *ctx, const helm_event_t *event)
{
    (void)ctx;
    static uint8_t frame[HELM_FRAME_MAX];
    size_t n = helm_event_frame(event, frame, sizeof frame);
    if (n > 0) {
        link_write(frame, n);
    }
}

/*
 * Called in the LVGL task. A lost key release would let a hold complete that
 * the captain let go of, so key inputs wait for room; the deck task drains
 * the queue at least every LOOP_MS plus one redraw, and never needs this task
 * to do so. Swipes and taps are not worth stalling the touch handling for.
 */
static void post_input(const ui_input_t *input)
{
    TickType_t wait = input->type == UI_INPUT_KEY ? pdMS_TO_TICKS(KEY_INPUT_WAIT_MS) : 0;
    if (xQueueSend(s_inputs, input, wait) != pdTRUE) {
        ESP_LOGW(TAG, "input queue full; dropped a touch");
    }
}

static void apply_input(const ui_input_t *in, uint32_t now)
{
    switch (in->type) {
    case UI_INPUT_KEY:
        if (in->down) {
            helm_deck_key_down(&s_deck, in->key, now);
        } else {
            helm_deck_key_up(&s_deck, in->key, now);
        }
        break;
    case UI_INPUT_KNOB:
        helm_deck_knob(&s_deck, in->delta, now);
        break;
    case UI_INPUT_PRESS:
        helm_deck_knob_press(&s_deck, false, now);
        break;
    case UI_INPUT_LONG:
        helm_deck_knob_press(&s_deck, true, now);
        break;
    case UI_INPUT_ROW: {
        /* A tap on the selected row opens it; a tap on another row moves there.
         * Rows are positions in the project view, so the knob steps count those. */
        int row = helm_deck_view_pos(&s_deck, in->row);
        int selected = helm_deck_view_pos(&s_deck, s_deck.selected);
        if (row < 0) {
            break; /* the list changed under the finger */
        }
        if (in->row == s_deck.selected) {
            helm_deck_knob_press(&s_deck, false, now);
        } else {
            helm_deck_knob(&s_deck, row - (selected < 0 ? 0 : selected), now);
        }
        break;
    }
    }
}

/* Physical controls (io.c), called from the deck task. */
static void on_key(helm_action_t key, bool down, uint32_t now)
{
    if (down) {
        helm_deck_key_down(&s_deck, key, now);
    } else {
        helm_deck_key_up(&s_deck, key, now);
    }
}

static void on_knob(int32_t delta, uint32_t now)
{
    helm_deck_knob(&s_deck, delta, now);
}

static void on_knob_press(bool long_press, uint32_t now)
{
    helm_deck_knob_press(&s_deck, long_press, now);
}

static void deck_task(void *arg)
{
    (void)arg;
    static uint8_t rx[1024];
    const io_input_cb_t controls = {on_key, on_knob, on_knob_press};
    uint32_t last_draw = now_ms() - DRAW_EVERY_MS;
    for (;;) {
        size_t n = link_read(rx, sizeof rx, pdMS_TO_TICKS(LOOP_MS));
        uint32_t now = now_ms();
        if (n > 0) {
            helm_deck_rx(&s_deck, rx, n, now);
        }
        ui_input_t in;
        while (xQueueReceive(s_inputs, &in, 0) == pdTRUE) {
            apply_input(&in, now);
        }
        io_poll(&controls, now);
        helm_deck_tick(&s_deck, now);
        io_update(&s_deck, now);
        if (now - last_draw >= DRAW_EVERY_MS) {
            last_draw = now;
            if (display_lock(100)) {
                ui_render(&s_deck, now);
                bsp_display_unlock();
            }
        }
    }
}

void app_main(void)
{
    ESP_LOGI(TAG, "%s starting", FIRMWARE);
    s_inputs = xQueueCreate(32, sizeof(ui_input_t));
    ESP_ERROR_CHECK(s_inputs != NULL ? ESP_OK : ESP_ERR_NO_MEM);
    ESP_ERROR_CHECK(io_start());

    lv_display_t *display = display_start();
    ESP_ERROR_CHECK(display != NULL ? ESP_OK : ESP_FAIL);
    ESP_ERROR_CHECK(bsp_display_backlight_on());
    if (display_lock(-1)) {
        ui_init(post_input);
        bsp_display_unlock();
    }

    s_cap_count += io_caps(s_caps + s_cap_count, sizeof s_caps / sizeof s_caps[0] - s_cap_count);
    const helm_deck_config_t cfg = {FIRMWARE, s_caps, s_cap_count, emit, NULL};
    helm_deck_init(&s_deck, &cfg);
    ESP_ERROR_CHECK(link_start());
    xTaskCreate(deck_task, "deck", DECK_TASK_STACK, NULL, DECK_TASK_PRIORITY, NULL);
}
