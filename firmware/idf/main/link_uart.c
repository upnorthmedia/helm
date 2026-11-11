/*
 * Fallback link over UART0, which the board's CH343P bridges to the
 * "Type-C UART" connector (H1) on GPIO37 (TX) and GPIO38 (RX). UART0 is also
 * the boot ROM's and the log console's port, so once the link starts, log
 * lines go out as Harness log frames (type 0x04) instead of raw text; the
 * bridge ignores them and `python3 -m helm.wire.decode` can show them.
 * Text written before that (the boot ROM banner, early boot logs) is noise
 * the bridge's decoder skips.
 */
#include "sdkconfig.h"

#if CONFIG_HELM_LINK_UART0

#include <stdarg.h>
#include <stdio.h>

#include "driver/uart.h"
#include "esp_check.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

#include "helm_frame.h"
#include "link.h"

static const char *TAG = "link_uart";

#define LINK_UART UART_NUM_0
#define RX_BUFFER_BYTES (16 * 1024)
#define TX_BUFFER_BYTES (4 * 1024)
#define LOG_LINE_BYTES 256

static SemaphoreHandle_t s_write_lock; /* recursive: a log line can come from inside a write */

static void write_locked(const uint8_t *frame, size_t len)
{
    uart_write_bytes(LINK_UART, frame, len);
}

static int log_as_frames(const char *fmt, va_list args)
{
    static uint8_t frame[HELM_FRAME_HEADER_BYTES + LOG_LINE_BYTES + HELM_FRAME_CRC_BYTES];
    xSemaphoreTakeRecursive(s_write_lock, portMAX_DELAY);
    char *line = (char *)frame + HELM_FRAME_HEADER_BYTES;
    int n = vsnprintf(line, LOG_LINE_BYTES, fmt, args);
    size_t len = n < 0 ? 0 : (n >= LOG_LINE_BYTES ? LOG_LINE_BYTES - 1 : (size_t)n);
    while (len > 0 && (line[len - 1] == '\n' || line[len - 1] == '\r')) {
        len--;
    }
    size_t total = helm_frame_encode(HELM_FRAME_TYPE_LOG, frame + HELM_FRAME_HEADER_BYTES, len, frame, sizeof frame);
    if (total > 0) {
        write_locked(frame, total);
    }
    xSemaphoreGiveRecursive(s_write_lock);
    return n;
}

esp_err_t link_start(void)
{
    s_write_lock = xSemaphoreCreateRecursiveMutex();
    if (s_write_lock == NULL) {
        return ESP_ERR_NO_MEM;
    }
    const uart_config_t cfg = {
        .baud_rate = CONFIG_HELM_LINK_UART_BAUD,
        .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };
    ESP_RETURN_ON_ERROR(uart_driver_install(LINK_UART, RX_BUFFER_BYTES, TX_BUFFER_BYTES, 0, NULL, 0), TAG, "uart install");
    ESP_RETURN_ON_ERROR(uart_param_config(LINK_UART, &cfg), TAG, "uart config");
    ESP_LOGI(TAG, "UART0 link at %d baud; logs continue as log frames", CONFIG_HELM_LINK_UART_BAUD);
    esp_log_set_vprintf(log_as_frames);
    return ESP_OK;
}

size_t link_read(uint8_t *buf, size_t cap, TickType_t wait)
{
    int n = uart_read_bytes(LINK_UART, buf, cap, wait);
    return n > 0 ? (size_t)n : 0;
}

void link_write(const uint8_t *frame, size_t len)
{
    xSemaphoreTakeRecursive(s_write_lock, portMAX_DELAY);
    write_locked(frame, len);
    xSemaphoreGiveRecursive(s_write_lock);
}

#endif /* CONFIG_HELM_LINK_UART0 */
