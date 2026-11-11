/*
 * The byte link to the bridge on the Mac. One implementation is built,
 * chosen in menuconfig (Helm deck > Link to the Mac): link_usb.c for the
 * P4's native USB as a CDC-ACM device, or link_uart.c for UART0 through the
 * board's CH343P.
 */
#pragma once

#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"
#include "freertos/FreeRTOS.h"

esp_err_t link_start(void);

/* Wait up to `wait` for received bytes; returns how many were copied. */
size_t link_read(uint8_t *buf, size_t cap, TickType_t wait);

/*
 * Send one whole frame. Never blocks for long: the deck often sits in front
 * of a stopped bridge, and the bridge resends the full model every 2 s, so a
 * frame that cannot go out now is dropped (as helm/wire/transport.py does).
 * Safe to call from any task; frames are never interleaved.
 */
void link_write(const uint8_t *frame, size_t len);
