/*
 * The deck's screens on the LCD-5's panel turned landscape, 1280 x 720, drawn
 * with LVGL 9 from the Waveshare board package, laid out to match
 * sim/render.py: Home (including the link-unknown state, with the view's
 * items in a right-hand column), List, Detail, Confirm with its 1 s fill bar,
 * and Result, under the status strip.
 *
 * Touch stands in for the controls not wired yet: the on-screen keys along
 * the bottom (CONFIG_HELM_TOUCH_KEYS) press and hold like the real keys, a
 * vertical swipe turns the knob, a tap presses it (a tap on a list row moves
 * to that row, a tap on the selected row opens it), and a long press is the
 * knob's long press (mute).
 *
 * LVGL is not thread safe: call ui_init and ui_render with the display lock
 * held (bsp_display_lock). Touch handlers run in the LVGL task and never
 * touch the deck; they hand inputs to `post`, which queues them for the deck
 * task.
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "helm_deck.h"

typedef enum {
    UI_INPUT_KEY,      /* an on-screen key went down or up */
    UI_INPUT_KNOB,     /* a swipe: delta knob steps */
    UI_INPUT_PRESS,    /* a tap: knob press */
    UI_INPUT_LONG,     /* a long press: knob long press */
    UI_INPUT_ROW       /* a tap on list row `row` (an item index) */
} ui_input_type_t;

typedef struct {
    ui_input_type_t type;
    helm_action_t key;
    bool down;
    int32_t delta;
    int row;
} ui_input_t;

typedef void (*ui_post_fn)(const ui_input_t *input);

void ui_init(ui_post_fn post);

/* Redraw from the deck's state. Call from the deck task, lock held. */
void ui_render(helm_deck_t *deck, uint32_t now_ms);
