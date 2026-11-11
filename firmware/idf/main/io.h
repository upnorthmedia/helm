/*
 * The deck's physical controls and outputs other than the screen: four key
 * switches, the I2C knob, the light chain (four key lights, then the 8-light
 * bar), and the chime. Each is a menuconfig setting under Helm deck, on by
 * default, and none of them stops the deck when its part is missing: a key
 * pin with nothing on it reads as never pressed, an absent knob is logged
 * once and looked for again every 2 s, a light pin with nothing on it is
 * harmless, and the chime plays to an empty speaker connector. The touch
 * screen (ui.c) works alongside all of them.
 *
 * The timing, colors, seesaw protocol, and tone are portable code in
 * firmware/core (helm_controls, helm_lights, helm_knob, helm_tone) with host
 * tests; this file only wires them to ESP-IDF.
 */
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"
#include "helm_deck.h"

typedef struct {
    void (*key)(helm_action_t key, bool down, uint32_t now_ms);
    void (*knob)(int32_t delta, uint32_t now_ms);
    void (*knob_press)(bool long_press, uint32_t now_ms);
} io_input_cb_t;

/* Set up every configured part. A part that fails is logged and left off;
 * the deck carries on without it. */
esp_err_t io_start(void);

/* Capability names for hello, for the parts io_start brought up ("knob" only
 * if it answered at start). Returns how many it wrote, at most max. */
size_t io_caps(const char **caps, size_t max);

/* Read the controls and report changes. Call from the deck task. */
void io_poll(const io_input_cb_t *cb, uint32_t now_ms);

/* Drive the lights and play any chime the deck asks for. Call from the deck task. */
void io_update(helm_deck_t *deck, uint32_t now_ms);
