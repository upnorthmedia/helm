/*
 * Device-to-bridge Events (helm/contract.py) and their encoding, matching
 * codec.encode_event byte for byte: a TYPE_JSON frame holding compact JSON
 * with "t" first and then the contract fields in declaration order.
 */
#ifndef HELM_EVENT_H
#define HELM_EVENT_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "helm_model.h"

#ifdef __cplusplus
extern "C" {
#endif

#define HELM_PRODUCT "helm" /* hello names the product, so a Harness daemon lets go */

typedef enum { HELM_KEY_DOWN, HELM_KEY_UP, HELM_KEY_HELD } helm_key_phase_t;

typedef enum {
    HELM_EVENT_HELLO,
    HELM_EVENT_KEY,
    HELM_EVENT_KNOB,
    HELM_EVENT_KNOB_PRESS,
    HELM_EVENT_SELECT,
    HELM_EVENT_SEEN,  /* any touch on the deck */
    HELM_EVENT_RESYNC /* a model was lost: send the full model now */
} helm_event_type_t;

typedef struct {
    helm_event_type_t type;
    union {
        struct {
            const char *fw;
            const char *const *caps;
            size_t cap_count;
        } hello;
        struct {
            helm_action_t key;
            helm_key_phase_t phase; /* held = the 1 s hold completed */
        } key;
        struct {
            int32_t delta;
        } knob;
        struct {
            bool long_press;
        } knob_press;
        struct {
            const char *ref;
        } select;
    } u;
} helm_event_t;

const char *helm_event_type_name(helm_event_type_t type);
const char *helm_key_phase_name(helm_key_phase_t phase);

/* Write the JSON payload; returns its length, or 0 when it does not fit. */
size_t helm_event_payload(const helm_event_t *event, uint8_t *out, size_t cap);

/* Write the complete frame; returns its length, or 0 when it does not fit.
 * HELM_FRAME_MAX bytes always suffice. */
size_t helm_event_frame(const helm_event_t *event, uint8_t *out, size_t cap);

#ifdef __cplusplus
}
#endif

#endif /* HELM_EVENT_H */
