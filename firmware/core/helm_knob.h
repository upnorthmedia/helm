/*
 * The knob: Adafruit's I2C STEMMA QT rotary encoder (PID 5880, the PID 4991
 * board with the encoder fitted), which runs Adafruit's seesaw firmware.
 * This file speaks the seesaw register protocol over a caller-supplied I2C
 * device, so it runs the same on the board and in the host tests.
 *
 * Protocol, from Adafruit's seesaw guide
 * (https://learn.adafruit.com/adafruit-seesaw-atsamd09-breakout, "Reading
 * and Writing Data", "GPIO", "NeoPixel", "Encoder") and the Adafruit_Seesaw
 * Arduino library (https://github.com/adafruit/Adafruit_Seesaw,
 * Adafruit_seesaw.cpp/.h and seesaw_neopixel.cpp):
 *
 *   write: [module base] [function register] [data ...]
 *   read:  write [module base] [function register], wait (the library waits
 *          250 us by default), then read the bytes
 *   Multi-byte values are big-endian, as the library sends and parses them.
 *   The guide calls the NeoPixel BUF_LENGTH little-endian; the library, the
 *   working reference, sends it big-endian, and so does this file.
 *
 * Board facts, from Adafruit's guide for the board
 * (https://learn.adafruit.com/adafruit-i2c-qt-rotary-encoder, "Pinouts")
 * and the library's encoder example (examples/encoder/encoder_basic): default
 * address 0x36 (A0 to A2 jumpers add 1, 2, 4), the push switch on seesaw pin
 * 24 (pressed reads low; the firmware enables its pull-up when asked), the
 * NeoPixel on seesaw pin 6, firmware product code 4991.
 */
#ifndef HELM_KNOB_H
#define HELM_KNOB_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "helm_controls.h"
#include "helm_lights.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Module bases and function registers (Adafruit_seesaw.h). */
#define HELM_SEESAW_STATUS_BASE 0x00
#define HELM_SEESAW_STATUS_HW_ID 0x01
#define HELM_SEESAW_STATUS_VERSION 0x02
#define HELM_SEESAW_GPIO_BASE 0x01
#define HELM_SEESAW_GPIO_DIRCLR_BULK 0x03
#define HELM_SEESAW_GPIO_BULK 0x04
#define HELM_SEESAW_GPIO_BULK_SET 0x05
#define HELM_SEESAW_GPIO_PULLENSET 0x0B
#define HELM_SEESAW_NEOPIXEL_BASE 0x0E
#define HELM_SEESAW_NEOPIXEL_PIN 0x01
#define HELM_SEESAW_NEOPIXEL_SPEED 0x02
#define HELM_SEESAW_NEOPIXEL_BUF_LENGTH 0x03
#define HELM_SEESAW_NEOPIXEL_BUF 0x04
#define HELM_SEESAW_NEOPIXEL_SHOW 0x05
#define HELM_SEESAW_ENCODER_BASE 0x11
#define HELM_SEESAW_ENCODER_DELTA 0x40 /* + encoder number; reading clears it */

#define HELM_SEESAW_READ_DELAY_US 250u

/* The PID 5880 / 4991 board. */
#define HELM_KNOB_DEFAULT_ADDR 0x36
#define HELM_KNOB_PRODUCT 4991
#define HELM_KNOB_SWITCH_PIN 24
#define HELM_KNOB_PIXEL_PIN 6

#define HELM_KNOB_RETRY_MS 2000u /* how often to look for an absent knob */
#define HELM_KNOB_MAX_FAILS 3    /* failed polls in a row before the knob counts as gone */
#define HELM_KNOB_SETTLE_MS 10u  /* push switch debounce */

/* One I2C device: the knob at its address. Each call is one transaction. */
typedef struct {
    /* Does anything answer at the address? Called before each look for an
     * absent knob, so it should not log a NACK. May be NULL. */
    bool (*probe)(void *ctx);
    bool (*write)(void *ctx, const uint8_t *data, size_t len); /* false on NACK or bus error */
    bool (*read)(void *ctx, uint8_t *data, size_t len);
    void (*delay_us)(void *ctx, uint32_t us);
    void *ctx;
} helm_seesaw_bus_t;

typedef struct {
    helm_seesaw_bus_t bus;
    uint32_t long_ms;
    bool ready;
    uint8_t fails;
    bool waiting; /* a probe failed; the next is due at next_probe_ms */
    uint32_t next_probe_ms;
    int reported; /* the last helm_knob_change_t reported, so each is reported once */
    uint8_t hw_id;    /* from the last successful probe */
    uint16_t product; /* from the last successful probe */
    helm_button_t button;
    bool light_written;
    helm_rgb_t light;
} helm_knob_t;

/* Each is reported once, when it first becomes true. */
typedef enum {
    HELM_KNOB_NO_CHANGE,
    HELM_KNOB_ABSENT,     /* nothing answered the first look; looked for every HELM_KNOB_RETRY_MS */
    HELM_KNOB_FOUND,      /* answered and set up; hw_id and product are filled in */
    HELM_KNOB_LOST,       /* stopped answering; looked for again every HELM_KNOB_RETRY_MS */
    HELM_KNOB_NOT_SEESAW  /* something answered but its hardware id is not a seesaw's */
} helm_knob_change_t;

typedef struct {
    helm_knob_change_t change;
    int32_t delta; /* detents turned since the last poll, as the seesaw counts them */
    helm_press_t press;
} helm_knob_input_t;

/* long_ms: how long the push must be held to count as a long press. */
void helm_knob_init(helm_knob_t *knob, const helm_seesaw_bus_t *bus, uint32_t long_ms);

/*
 * Look for the knob if it is absent (at most every HELM_KNOB_RETRY_MS, the
 * first time at once), else read its turn and push switch. An absent knob
 * costs one probe (or one NACKed write) per retry and never blocks beyond
 * the bus's own timeout.
 */
helm_knob_input_t helm_knob_poll(helm_knob_t *knob, uint32_t now_ms);

/* Set the knob's NeoPixel. Writes only when the knob is ready and the color changed. */
void helm_knob_set_light(helm_knob_t *knob, helm_rgb_t color);

/* Parsing helpers, exposed for the tests. */
uint32_t helm_seesaw_u32(const uint8_t b[4]);
bool helm_seesaw_hw_id_known(uint8_t hw_id);

#ifdef __cplusplus
}
#endif

#endif /* HELM_KNOB_H */
