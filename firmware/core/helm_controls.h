/*
 * Timing for the physical controls: switch debounce, and the knob button's
 * press and long press. Pure logic on a millisecond clock (it may wrap);
 * the platform reads the pins and feeds the readings in.
 */
#ifndef HELM_CONTROLS_H
#define HELM_CONTROLS_H

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Zero-initialise: released, with no reading yet. */
typedef struct {
    bool down;      /* the debounced state */
    bool raw;       /* the last reading */
    uint32_t since; /* when the reading last changed */
} helm_debounce_t;

/*
 * Feed one reading (true = pressed). The debounced state follows a reading
 * only once it has held for settle_ms. Returns true when the debounced state
 * changes; read it from d->down.
 */
bool helm_debounce(helm_debounce_t *d, bool raw, uint32_t now_ms, uint32_t settle_ms);

typedef enum {
    HELM_PRESS_NONE,
    HELM_PRESS_SHORT, /* released before long_ms */
    HELM_PRESS_LONG   /* still held at long_ms; its release reports nothing */
} helm_press_t;

/* Zero-initialise. */
typedef struct {
    helm_debounce_t switch_state;
    uint32_t down_ms; /* when the debounced press began */
    bool long_sent;
} helm_button_t;

/*
 * Feed one reading of the knob's push switch. A long press is reported as
 * soon as the press has lasted long_ms, without waiting for the release, as
 * the simulator and the touch screen do.
 */
helm_press_t helm_button(helm_button_t *b, bool raw, uint32_t now_ms, uint32_t settle_ms, uint32_t long_ms);

#ifdef __cplusplus
}
#endif

#endif /* HELM_CONTROLS_H */
