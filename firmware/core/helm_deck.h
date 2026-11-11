/*
 * What the deck does, apart from drawing: the C port of sim/state.py (screens,
 * selection, scrolling, hold to confirm, mute, chime, link timeout) joined
 * with the device end of the link from helm/wire/transport.py (DeviceLink:
 * seq gaps, bad CRCs, rate-limited resync) and the simulator's hello cadence.
 *
 * Feed it received bytes, control input, and a millisecond clock; it calls
 * `emit` with each Event for the bridge, which the platform encodes with
 * helm_event_frame() and writes to the serial port. Drawing code reads the
 * state back through the query functions.
 *
 * Time is a uint32_t millisecond counter that may wrap (Arduino millis(),
 * or esp_timer_get_time() / 1000 truncated). Call helm_deck_tick() at least
 * every 100 ms. A helm_deck_t is about 31 KB (a frame buffer and two models),
 * so keep it in static storage, not on a task stack.
 */
#ifndef HELM_DECK_H
#define HELM_DECK_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "helm_event.h"
#include "helm_frame.h"
#include "helm_model.h"

#ifdef __cplusplus
extern "C" {
#endif

#define HELM_HOLD_MS 1000u                /* YES / LATER / HOLD must be held this long */
#define HELM_LINK_TIMEOUT_MS 10000u       /* no model for longer than this reads as unknown */
#define HELM_RESYNC_MIN_INTERVAL_MS 2000u /* resync at most this often, as the Harness Pro does */
#define HELM_HELLO_EVERY_MS 2000u         /* hello again this often until a bridge answers */
#define HELM_SWEEP_MS 2000u               /* green sweep when something lands */
#define HELM_RESULT_LINGER_MS 8000u       /* a final result stays up this long, then home */

/* Display copies kept for the result screen; cut at a UTF-8 boundary. */
#define HELM_PENDING_SHORT_ID_BYTES 128u
#define HELM_PENDING_TEXT_BYTES 512u
/* The project view's name. The bridge clips projects to 32 characters, so
 * this holds any it sends (at most 4 bytes each). */
#define HELM_VIEW_BYTES 132u

typedef void (*helm_emit_fn)(void *ctx, const helm_event_t *event);

typedef struct {
    const char *fw;          /* firmware version for hello */
    const char *const *caps; /* capability names for hello */
    size_t cap_count;
    helm_emit_fn emit; /* the event's strings are valid only during the call */
    void *ctx;
} helm_deck_config_t;

typedef enum {
    HELM_SCREEN_HOME,
    HELM_SCREEN_LIST,
    HELM_SCREEN_DETAIL,  /* full text, only after a knob press (D18) */
    HELM_SCREEN_CONFIRM, /* while a key is held */
    HELM_SCREEN_RESULT   /* the bridge's answer to a completed hold */
} helm_screen_t;

typedef enum {
    HELM_LINK_OK,
    HELM_LINK_WAITING,                 /* no model yet */
    HELM_LINK_SILENT,                  /* no model for over 10 s */
    HELM_LINK_BRIDGE_PROBLEM,          /* link.bridge_ok is false */
    HELM_LINK_FIRSTMATE_NOT_LISTENING  /* link.firstmate_can_receive is not true */
} helm_link_state_t;

typedef struct {
    helm_deck_config_t cfg;

    /* Link */
    helm_decoder_t decoder;
    helm_model_t models[2];
    uint8_t current; /* index into models of the model on screen */
    bool has_model;
    bool silent;     /* latched once the link timeout passes, so clock wrap cannot hide it */
    uint32_t last_model_ms;
    uint32_t last_rx_ms;
    bool have_seq;
    int64_t last_seq;
    uint32_t corrupt_seen;
    bool resync_pending;
    bool resync_sent;
    uint32_t last_resync_ms;
    bool hello_sent;
    uint32_t last_hello_ms;

    /* Counters, for a debug screen or log line */
    uint32_t seq_gaps;
    uint32_t bad_messages; /* JSON frames that did not parse as a model */
    helm_parse_status_t last_parse_error;

    /* Deck */
    helm_screen_t screen;
    int selected; /* index into the current model's items, or -1; always in the view */
    char view[HELM_VIEW_BYTES]; /* project the list is filtered to; "" is the "all" view */
    int32_t detail_scroll;
    bool muted;

    bool holding;
    helm_action_t hold_key;
    uint32_t hold_started_ms;
    helm_screen_t hold_return;

    bool pending; /* a hold completed; waiting for or showing the result */
    helm_action_t pending_key;
    int64_t pending_seq_after; /* only a model newer than this can carry our result */
    char pending_short_id[HELM_PENDING_SHORT_ID_BYTES];
    bool pending_has_result;
    helm_result_state_t pending_state;
    bool pending_seen;               /* queued, and firstmate has read the note */
    helm_opt_int_t pending_waited_s; /* queued: seconds since the note was sent */
    bool pending_stalled;            /* queued and unread past the bridge's limit */
    char pending_text[HELM_PENDING_TEXT_BYTES];
    bool pending_final;
    uint32_t pending_final_ms;

    bool sweeping;
    uint32_t sweep_started_ms;
    uint32_t chimes; /* requested and not yet played */
    bool chime_seq_known;
    int64_t chime_seq;
    bool seen_sent;
    int64_t seen_sent_for; /* seen goes out once per model */
} helm_deck_t;

void helm_deck_init(helm_deck_t *deck, const helm_deck_config_t *cfg);

/* Bytes from the serial port. */
void helm_deck_rx(helm_deck_t *deck, const uint8_t *data, size_t len, uint32_t now_ms);

/* Timers: partial-frame expiry, resync, hello, hold completion, result linger. */
void helm_deck_tick(helm_deck_t *deck, uint32_t now_ms);

/*
 * Controls. Every one counts as a touch.
 *
 * The knob on Home turns through the project views ("all" first, then each
 * project the items name, in byte order) when there is more than one, and
 * otherwise opens the list. On the list it moves the selection within the
 * view, and turning up past the first row goes back to Home. A press opens
 * the list from Home, the full text from the list, and goes back from there.
 */
void helm_deck_key_down(helm_deck_t *deck, helm_action_t key, uint32_t now_ms);
void helm_deck_key_up(helm_deck_t *deck, helm_action_t key, uint32_t now_ms);
void helm_deck_knob(helm_deck_t *deck, int32_t delta, uint32_t now_ms);
void helm_deck_knob_press(helm_deck_t *deck, bool long_press, uint32_t now_ms);

/* State for drawing and lights. */
const helm_model_t *helm_deck_model(const helm_deck_t *deck); /* NULL before the first model */
helm_link_state_t helm_deck_link_state(const helm_deck_t *deck, uint32_t now_ms);
helm_attention_t helm_deck_attention(const helm_deck_t *deck, uint32_t now_ms);
const helm_item_t *helm_deck_selected(const helm_deck_t *deck);
/* A key is lit only when its action applies to the selected item, never
 * while the Mac is locked, and YES / LATER / HOLD never while firstmate is away. */
bool helm_deck_key_lit(const helm_deck_t *deck, helm_action_t key, uint32_t now_ms);
/* 0 to 1000 while a key is held, else 0. */
uint32_t helm_deck_hold_progress_permille(const helm_deck_t *deck, uint32_t now_ms);
bool helm_deck_sweeping(const helm_deck_t *deck, uint32_t now_ms);
/* True once per chime to play (a model with chime set, unless muted or away). */
bool helm_deck_take_chime(helm_deck_t *deck);

/* The project view: its name, or NULL for "all". */
const char *helm_deck_view(const helm_deck_t *deck);
/* True when some item names a project, so the knob on Home has views to turn through. */
bool helm_deck_has_views(const helm_deck_t *deck);
/* Items in the view, the item index at a position in it (-1 past the end),
 * and the position of an item index (-1 when it is not in the view). */
int helm_deck_view_count(const helm_deck_t *deck);
int helm_deck_view_item(const helm_deck_t *deck, int pos);
int helm_deck_view_pos(const helm_deck_t *deck, int index);

/* The first list position (within the view) to show so the selection sits mid-window. */
int helm_deck_list_first(const helm_deck_t *deck, int rows);
/* Keep detail_scroll within the text once the drawing code knows its height. */
void helm_deck_clamp_detail_scroll(helm_deck_t *deck, int32_t total_lines, int32_t visible_lines);

#ifdef __cplusplus
}
#endif

#endif /* HELM_DECK_H */
