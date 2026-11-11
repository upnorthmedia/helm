#include "io.h"

#include <stdlib.h>
#include <string.h>

#include "bsp/esp-bsp.h"
#include "driver/gpio.h"
#include "esp_check.h"
#include "esp_log.h"
#include "esp_rom_sys.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "sdkconfig.h"

#include "helm_controls.h"
#include "helm_knob.h"
#include "helm_lights.h"
#include "helm_tone.h"

#if CONFIG_HELM_LIGHTS
#include "led_strip.h"
#endif

static const char *TAG = "io";

/*
 * Pins the board itself uses, from Waveshare's schematic
 * (ESP32-P4-WIFI6-Touch-LCD-5-Schematic.pdf) and the board package's pin map
 * (bsp/esp32_p4_wifi6_touch_lcd_5.h): GPIO0/1 32 kHz crystal; 2 the touch
 * controller's interrupt when R108 is fitted (the schematic marks it NC/0R);
 * 6, 14 to 19, 54 the ESP32-C6 Wi-Fi module; 7/8 I2C (touch, codecs, knob);
 * 9 to 13 I2S to the codecs; 20 the battery voltage divider; 23, 26, 27, 33
 * touch reset, backlight, panel reset, backlight enable; 24/25 the USB
 * Serial/JTAG pads; 34 to 38 the chip's strapping pins (35 is also BOOT and
 * the CH343P's auto-boot line, 37/38 UART0 to the CH343P); 39 to 45 the
 * microSD card; 53 the speaker amplifier enable. A Helm pin setting on any of
 * these fails the build.
 */
#define BOARD_PIN(p)                                                                                   \
    ((p) <= 2 || ((p) >= 6 && (p) <= 20) || ((p) >= 23 && (p) <= 27) || ((p) >= 33 && (p) <= 45) ||  \
     (p) >= 53)

#if CONFIG_HELM_KEYS_GPIO
#if BOARD_PIN(CONFIG_HELM_PIN_KEY_YES) || BOARD_PIN(CONFIG_HELM_PIN_KEY_LATER) || \
    BOARD_PIN(CONFIG_HELM_PIN_KEY_HOLD) || BOARD_PIN(CONFIG_HELM_PIN_KEY_FOCUS)
#error "A key switch pin is one the board already uses; see BOARD_PIN in io.c"
#endif
#endif
#if CONFIG_HELM_LIGHTS
#if BOARD_PIN(CONFIG_HELM_PIN_LIGHTS)
#error "The light chain pin is one the board already uses; see BOARD_PIN in io.c"
#endif
#if CONFIG_HELM_KEYS_GPIO
#if CONFIG_HELM_PIN_LIGHTS == CONFIG_HELM_PIN_KEY_YES || CONFIG_HELM_PIN_LIGHTS == CONFIG_HELM_PIN_KEY_LATER || \
    CONFIG_HELM_PIN_LIGHTS == CONFIG_HELM_PIN_KEY_HOLD || CONFIG_HELM_PIN_LIGHTS == CONFIG_HELM_PIN_KEY_FOCUS
#error "The light chain pin is also a key switch pin"
#endif
#endif
#endif

static const char *s_caps[3];
static size_t s_cap_count;

static void add_cap(const char *cap)
{
    if (s_cap_count < sizeof s_caps / sizeof s_caps[0]) {
        s_caps[s_cap_count++] = cap;
    }
}

/* ------------------------------------------------------------ key switches */

#if CONFIG_HELM_KEYS_GPIO
static const gpio_num_t KEY_PINS[HELM_ACTION_COUNT] = {
    [HELM_ACTION_YES] = CONFIG_HELM_PIN_KEY_YES,
    [HELM_ACTION_LATER] = CONFIG_HELM_PIN_KEY_LATER,
    [HELM_ACTION_HOLD] = CONFIG_HELM_PIN_KEY_HOLD,
    [HELM_ACTION_FOCUS] = CONFIG_HELM_PIN_KEY_FOCUS,
};

static helm_debounce_t s_keys[HELM_ACTION_COUNT];
static bool s_keys_on;

static bool keys_start(void)
{
    uint64_t mask = 0;
    for (int k = 0; k < HELM_ACTION_COUNT; k++) {
        mask |= 1ULL << KEY_PINS[k];
    }
    if (__builtin_popcountll(mask) != HELM_ACTION_COUNT) {
        ESP_LOGE(TAG, "two keys share a pin; key switches off");
        return false;
    }
    const gpio_config_t cfg = {
        .pin_bit_mask = mask,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    esp_err_t err = gpio_config(&cfg);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "key pins: %s; key switches off", esp_err_to_name(err));
        return false;
    }
    for (int k = 0; k < HELM_ACTION_COUNT; k++) {
        s_keys[k] = (helm_debounce_t){0};
    }
    ESP_LOGI(TAG, "key switches on GPIO %d %d %d %d", KEY_PINS[0], KEY_PINS[1], KEY_PINS[2], KEY_PINS[3]);
    return true;
}

static void keys_poll(const io_input_cb_t *cb, uint32_t now_ms)
{
    if (!s_keys_on) {
        return;
    }
    for (int k = 0; k < HELM_ACTION_COUNT; k++) {
        bool pressed = gpio_get_level(KEY_PINS[k]) == 0; /* a press pulls the pin to GND */
        if (helm_debounce(&s_keys[k], pressed, now_ms, CONFIG_HELM_KEY_DEBOUNCE_MS)) {
            cb->key((helm_action_t)k, s_keys[k].down, now_ms);
        }
    }
}
#endif

/* -------------------------------------------------------------------- knob */

#if CONFIG_HELM_KNOB
#define KNOB_I2C_HZ 100000      /* the seesaw's I2C clock; the bus itself runs at 400 kHz */
#define KNOB_I2C_TIMEOUT_MS 20  /* one transaction; an absent knob NACKs at once */
#define KNOB_POLL_MS 10

static i2c_master_bus_handle_t s_i2c;
static i2c_master_dev_handle_t s_knob_dev;
static helm_knob_t s_knob;
static uint32_t s_knob_polled_ms;

static bool knob_probe(void *ctx)
{
    (void)ctx;
    return i2c_master_probe(s_i2c, CONFIG_HELM_KNOB_I2C_ADDR, KNOB_I2C_TIMEOUT_MS) == ESP_OK;
}

static bool knob_write(void *ctx, const uint8_t *data, size_t len)
{
    (void)ctx;
    return i2c_master_transmit(s_knob_dev, data, len, KNOB_I2C_TIMEOUT_MS) == ESP_OK;
}

static bool knob_read(void *ctx, uint8_t *data, size_t len)
{
    (void)ctx;
    return i2c_master_receive(s_knob_dev, data, len, KNOB_I2C_TIMEOUT_MS) == ESP_OK;
}

static void knob_delay(void *ctx, uint32_t us)
{
    (void)ctx;
    esp_rom_delay_us(us);
}

static void knob_report(helm_knob_change_t change)
{
    switch (change) {
    case HELM_KNOB_NO_CHANGE:
        break;
    case HELM_KNOB_ABSENT:
        ESP_LOGW(TAG, "no knob at I2C 0x%02x; looking again every %u s", CONFIG_HELM_KNOB_I2C_ADDR,
                 HELM_KNOB_RETRY_MS / 1000);
        break;
    case HELM_KNOB_FOUND:
        ESP_LOGI(TAG, "knob at I2C 0x%02x: seesaw hardware 0x%02x, product %u", CONFIG_HELM_KNOB_I2C_ADDR,
                 s_knob.hw_id, s_knob.product);
        if (s_knob.product != HELM_KNOB_PRODUCT) {
            ESP_LOGW(TAG, "expected seesaw product %d (Adafruit 4991/5880); using it anyway", HELM_KNOB_PRODUCT);
        }
        break;
    case HELM_KNOB_LOST:
        ESP_LOGW(TAG, "knob at I2C 0x%02x stopped answering; looking again every %u s", CONFIG_HELM_KNOB_I2C_ADDR,
                 HELM_KNOB_RETRY_MS / 1000);
        break;
    case HELM_KNOB_NOT_SEESAW:
        ESP_LOGW(TAG, "the device at I2C 0x%02x is not a seesaw (hardware id 0x%02x); knob off",
                 CONFIG_HELM_KNOB_I2C_ADDR, s_knob.hw_id);
        break;
    }
}

static bool knob_start(uint32_t now_ms)
{
    /* The board package's shared bus (GPIO7/GPIO8); the display start calls this again harmlessly. */
    esp_err_t err = bsp_i2c_init();
    s_i2c = bsp_i2c_get_handle();
    if (err != ESP_OK || s_i2c == NULL) {
        ESP_LOGE(TAG, "I2C bus: %s; knob off", esp_err_to_name(err));
        return false;
    }
    const i2c_device_config_t dev = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = CONFIG_HELM_KNOB_I2C_ADDR,
        .scl_speed_hz = KNOB_I2C_HZ,
    };
    err = i2c_master_bus_add_device(s_i2c, &dev, &s_knob_dev);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "knob I2C device: %s; knob off", esp_err_to_name(err));
        return false;
    }
    const helm_seesaw_bus_t bus = {knob_probe, knob_write, knob_read, knob_delay, NULL};
    helm_knob_init(&s_knob, &bus, CONFIG_HELM_KNOB_LONG_PRESS_MS);
    knob_report(helm_knob_poll(&s_knob, now_ms).change);
    s_knob_polled_ms = now_ms;
    return true;
}

static bool s_knob_on;

static void knob_poll(const io_input_cb_t *cb, uint32_t now_ms)
{
    if (!s_knob_on || now_ms - s_knob_polled_ms < KNOB_POLL_MS) {
        return;
    }
    s_knob_polled_ms = now_ms;
    helm_knob_input_t in = helm_knob_poll(&s_knob, now_ms);
    knob_report(in.change);
    if (in.delta != 0) {
#if CONFIG_HELM_KNOB_REVERSE
        in.delta = -in.delta;
#endif
        cb->knob(in.delta, now_ms);
    }
    if (in.press != HELM_PRESS_NONE) {
        cb->knob_press(in.press == HELM_PRESS_LONG, now_ms);
    }
}
#endif

/* ------------------------------------------------------------------ lights */

#if CONFIG_HELM_LIGHTS
#define CHAIN_LEN (HELM_ACTION_COUNT + HELM_BAR_LIGHTS)

static led_strip_handle_t s_strip;
static helm_rgb_t s_shown[CHAIN_LEN];
static bool s_shown_valid;
static bool s_strip_error_logged;

static bool lights_start(void)
{
    const led_strip_config_t cfg = {
        .strip_gpio_num = CONFIG_HELM_PIN_LIGHTS,
        .max_leds = CHAIN_LEN,
        /* NeoKey sockets carry SK6812 mini-E lights and the stick WS2812B;
         * both take GRB at 800 kHz with WS2812 timing. */
        .led_model = LED_MODEL_WS2812,
        .color_component_format = LED_STRIP_COLOR_COMPONENT_FMT_GRB,
        .flags = {.invert_out = false},
    };
    const led_strip_rmt_config_t rmt = {
        .clk_src = RMT_CLK_SRC_DEFAULT,
        .resolution_hz = 10 * 1000 * 1000,
        .mem_block_symbols = 0,
        .flags = {.with_dma = false},
    };
    esp_err_t err = led_strip_new_rmt_device(&cfg, &rmt, &s_strip);
    if (err == ESP_OK) {
        err = led_strip_clear(s_strip);
    }
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "light chain on GPIO %d: %s; lights off", CONFIG_HELM_PIN_LIGHTS, esp_err_to_name(err));
        return false;
    }
    ESP_LOGI(TAG, "light chain on GPIO %d: %d key lights, then %d bar lights, brightness cap %d/255",
             CONFIG_HELM_PIN_LIGHTS, HELM_ACTION_COUNT, HELM_BAR_LIGHTS, CONFIG_HELM_LIGHT_BRIGHTNESS);
    return true;
}

static bool s_lights_on;

static void lights_show(const helm_lights_t *lights)
{
    if (!s_lights_on) {
        return;
    }
    helm_rgb_t chain[CHAIN_LEN];
    memcpy(chain, lights->keys, sizeof lights->keys);
    memcpy(chain + HELM_ACTION_COUNT, lights->bar, sizeof lights->bar);
    if (s_shown_valid && memcmp(chain, s_shown, sizeof chain) == 0) {
        return;
    }
    esp_err_t err = ESP_OK;
    for (int i = 0; i < CHAIN_LEN && err == ESP_OK; i++) {
        err = led_strip_set_pixel(s_strip, (uint32_t)i, chain[i].r, chain[i].g, chain[i].b);
    }
    if (err == ESP_OK) {
        err = led_strip_refresh(s_strip);
    }
    s_shown_valid = err == ESP_OK;
    if (s_shown_valid) {
        memcpy(s_shown, chain, sizeof chain);
    } else if (!s_strip_error_logged) {
        s_strip_error_logged = true;
        ESP_LOGE(TAG, "light chain: %s", esp_err_to_name(err));
    }
}
#endif

/* ------------------------------------------------------------------- chime */

#if CONFIG_HELM_CHIME_SPEAKER
#define CHIME_RATE 22050 /* bsp_audio_init's default I2S rate */
#define CHIME_PEAK 16000 /* about half of full scale; the codec volume does the rest */
#define CHIME_GAP_MS 120 /* between chimes that arrive together */

static esp_codec_dev_handle_t s_speaker;
static TaskHandle_t s_chime_task;
static int16_t *s_tone;
static size_t s_tone_len;

/* Plays one tone per notification, so the deck task never waits on audio. */
static void chime_task(void *arg)
{
    (void)arg;
    bool error_logged = false;
    for (;;) {
        ulTaskNotifyTake(pdFALSE, portMAX_DELAY);
        int err = esp_codec_dev_write(s_speaker, s_tone, (int)(s_tone_len * sizeof s_tone[0]));
        if (err != ESP_CODEC_DEV_OK && !error_logged) {
            error_logged = true;
            ESP_LOGE(TAG, "chime: speaker write failed (%d)", err);
        }
        vTaskDelay(pdMS_TO_TICKS(CHIME_GAP_MS));
    }
}

static bool chime_start(void)
{
    s_tone_len = helm_tone_samples(CHIME_RATE, CONFIG_HELM_CHIME_MS);
    s_tone = malloc(s_tone_len * sizeof s_tone[0]);
    if (s_tone == NULL) {
        ESP_LOGE(TAG, "chime: no memory for the tone; chime off");
        return false;
    }
    helm_tone(s_tone, s_tone_len, CHIME_RATE, CONFIG_HELM_CHIME_HZ, CONFIG_HELM_CHIME_MS, CHIME_PEAK);

    s_speaker = bsp_audio_codec_speaker_init();
    if (s_speaker == NULL) {
        ESP_LOGE(TAG, "chime: the ES8311 codec did not start; chime off");
        return false;
    }
    esp_codec_dev_sample_info_t fs = {
        .bits_per_sample = 16,
        .channel = 1,
        .sample_rate = CHIME_RATE,
    };
    int err = esp_codec_dev_open(s_speaker, &fs);
    if (err == ESP_CODEC_DEV_OK) {
        err = esp_codec_dev_set_out_vol(s_speaker, CONFIG_HELM_CHIME_VOLUME);
    }
    if (err != ESP_CODEC_DEV_OK) {
        ESP_LOGE(TAG, "chime: speaker output did not open (%d); chime off", err);
        return false;
    }
    if (xTaskCreate(chime_task, "chime", 3072, NULL, 3, &s_chime_task) != pdPASS) {
        ESP_LOGE(TAG, "chime: no task; chime off");
        return false;
    }
    ESP_LOGI(TAG, "chime: %d Hz for %d ms at volume %d on the speaker output", CONFIG_HELM_CHIME_HZ,
             CONFIG_HELM_CHIME_MS, CONFIG_HELM_CHIME_VOLUME);
    return true;
}

static bool s_chime_on;

static void chime_play(void)
{
    if (s_chime_on) {
        xTaskNotifyGive(s_chime_task);
    } else {
        ESP_LOGI(TAG, "chime (speaker off)");
    }
}
#else
static void chime_play(void)
{
    ESP_LOGI(TAG, "chime");
}
#endif

/* --------------------------------------------------------------- interface */

esp_err_t io_start(void)
{
#if CONFIG_HELM_KEYS_GPIO
    s_keys_on = keys_start();
#else
    ESP_LOGI(TAG, "key switches off in menuconfig; keys are on screen");
#endif
    add_cap("keys-4"); /* on screen or as switches */
#if CONFIG_HELM_KNOB
    s_knob_on = knob_start((uint32_t)(esp_timer_get_time() / 1000));
    if (s_knob_on && s_knob.ready) {
        add_cap("knob");
    }
#endif
#if CONFIG_HELM_LIGHTS
    s_lights_on = lights_start();
    if (s_lights_on) {
        add_cap("lightbar-8");
    }
#endif
#if CONFIG_HELM_CHIME_SPEAKER
    s_chime_on = chime_start();
    if (s_chime_on) {
        add_cap("chime");
    }
#endif
    return ESP_OK;
}

size_t io_caps(const char **caps, size_t max)
{
    size_t n = s_cap_count < max ? s_cap_count : max;
    memcpy(caps, s_caps, n * sizeof caps[0]);
    return n;
}

void io_poll(const io_input_cb_t *cb, uint32_t now_ms)
{
#if CONFIG_HELM_KEYS_GPIO
    keys_poll(cb, now_ms);
#endif
#if CONFIG_HELM_KNOB
    knob_poll(cb, now_ms);
#endif
    (void)cb;
    (void)now_ms;
}

void io_update(helm_deck_t *deck, uint32_t now_ms)
{
    helm_lights_t lights;
    helm_lights_compute(deck, now_ms, CONFIG_HELM_LIGHT_BRIGHTNESS, &lights);
#if CONFIG_HELM_LIGHTS
    lights_show(&lights);
#endif
#if CONFIG_HELM_KNOB
    if (s_knob_on) {
        helm_knob_set_light(&s_knob, lights.knob);
    }
#endif
    while (helm_deck_take_chime(deck)) {
        chime_play();
    }
}
