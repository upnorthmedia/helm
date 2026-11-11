/*
 * The link over the ESP32-P4's native USB 2.0 port as a TinyUSB CDC-ACM
 * device. On the Waveshare board this is connector H2, labelled "Type-C"
 * (the other one, H1 "Type-C UART", goes to the CH343P). The USB product and
 * manufacturer strings come from sdkconfig.defaults (CONFIG_TINYUSB_DESC_*).
 */
#include "sdkconfig.h"

#if CONFIG_HELM_LINK_USB_CDC

#include <stdbool.h>

#include "esp_check.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/stream_buffer.h"
#include "tinyusb.h"
#include "tinyusb_cdc_acm.h"
#include "tinyusb_default_config.h"
#include "tusb.h"

#include "link.h"

static const char *TAG = "link_usb";

#define RX_BUFFER_BYTES (16 * 1024)
#define WRITE_BUDGET_MS 100

static StreamBufferHandle_t s_rx;
static SemaphoreHandle_t s_write_lock;
static volatile bool s_host_open; /* DTR: a program on the Mac has the port open */

static void on_rx(int itf, cdcacm_event_t *event)
{
    (void)event;
    uint8_t buf[CONFIG_TINYUSB_CDC_RX_BUFSIZE];
    size_t n = 0;
    if (tinyusb_cdcacm_read((tinyusb_cdcacm_itf_t)itf, buf, sizeof buf, &n) == ESP_OK && n > 0) {
        /* A full buffer means the deck task is stuck; the frame decoder
         * resyncs on whatever gets dropped here. */
        xStreamBufferSend(s_rx, buf, n, 0);
    }
}

static void on_line_state(int itf, cdcacm_event_t *event)
{
    (void)itf;
    s_host_open = event->line_state_changed_data.dtr;
    ESP_LOGI(TAG, "host %s the port", s_host_open ? "opened" : "closed");
}

esp_err_t link_start(void)
{
    s_rx = xStreamBufferCreate(RX_BUFFER_BYTES, 1);
    s_write_lock = xSemaphoreCreateMutex();
    if (s_rx == NULL || s_write_lock == NULL) {
        return ESP_ERR_NO_MEM;
    }
    /* On the P4 the default configuration is the high-speed port. */
    const tinyusb_config_t usb_cfg = TINYUSB_DEFAULT_CONFIG();
    ESP_RETURN_ON_ERROR(tinyusb_driver_install(&usb_cfg), TAG, "tinyusb install");
    const tinyusb_config_cdcacm_t acm_cfg = {
        .cdc_port = TINYUSB_CDC_ACM_0,
        .callback_rx = on_rx,
        .callback_line_state_changed = on_line_state,
    };
    ESP_RETURN_ON_ERROR(tinyusb_cdcacm_init(&acm_cfg), TAG, "cdc-acm init");
    ESP_LOGI(TAG, "USB CDC-ACM link started");
    return ESP_OK;
}

size_t link_read(uint8_t *buf, size_t cap, TickType_t wait)
{
    return xStreamBufferReceive(s_rx, buf, cap, wait);
}

void link_write(const uint8_t *frame, size_t len)
{
    if (!s_host_open) {
        return; /* nobody is listening; the next hello goes out once someone is */
    }
    xSemaphoreTake(s_write_lock, portMAX_DELAY);
    TickType_t start = xTaskGetTickCount();
    /*
     * Queue a frame only once the whole of it fits in the TX FIFO, so a slow
     * host never leaves part of one frame in front of the next. Every event
     * frame fits (CONFIG_TINYUSB_CDC_TX_BUFSIZE is 4096); only a larger frame
     * falls through to the chunked loop below.
     */
    if (len <= CONFIG_TINYUSB_CDC_TX_BUFSIZE) {
        while (tud_cdc_n_write_available(TINYUSB_CDC_ACM_0) < len) {
            tinyusb_cdcacm_write_flush(TINYUSB_CDC_ACM_0, 0);
            if (!s_host_open || xTaskGetTickCount() - start >= pdMS_TO_TICKS(WRITE_BUDGET_MS)) {
                ESP_LOGW(TAG, "dropped a %u byte frame: host not reading", (unsigned)len);
                xSemaphoreGive(s_write_lock);
                return;
            }
            vTaskDelay(1);
        }
    }
    size_t sent = 0;
    while (sent < len) {
        sent += tinyusb_cdcacm_write_queue(TINYUSB_CDC_ACM_0, frame + sent, len - sent);
        tinyusb_cdcacm_write_flush(TINYUSB_CDC_ACM_0, 0);
        if (sent < len) {
            if (xTaskGetTickCount() - start >= pdMS_TO_TICKS(WRITE_BUDGET_MS)) {
                /* The rest is dropped; the bridge's decoder skips the partial frame. */
                ESP_LOGW(TAG, "dropped %u of %u bytes: host not reading", (unsigned)(len - sent), (unsigned)len);
                break;
            }
            vTaskDelay(1);
        }
    }
    xSemaphoreGive(s_write_lock);
}

#endif /* CONFIG_HELM_LINK_USB_CDC */
