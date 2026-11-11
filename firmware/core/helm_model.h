/*
 * The contract Model (helm/contract.py) as fixed-size C structs, and a parser
 * for the "model" JSON payload that helm/wire/codec.py writes.
 *
 * Strings live in one pool inside the model, addressed by offset. A payload is
 * at most HELM_FRAME_MAX_PAYLOAD bytes and every decoded string is shorter
 * than its quoted source, so the pool always holds every string of any model
 * that fits a frame: nothing is truncated, and a ref echoed in `select` or `key` is
 * byte for byte what the bridge sent. Offsets rather than pointers keep the
 * struct safe to copy with memcpy.
 *
 * Parsing validates like codec.decode_model: required fields, value types
 * (a bool is never an int), and enum values. Unknown keys are ignored, and the
 * fields added after the first release (link.away, link.mac_locked,
 * item.project, usage, context) are optional, so this parser and an older or newer bridge still agree. Integers
 * must fit their C field (int64 for seq, int32 elsewhere), which is narrower
 * than Python's unbounded int but far beyond anything the bridge sends.
 */
#ifndef HELM_MODEL_H
#define HELM_MODEL_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "helm_frame.h"

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Enough items for any model that fits one frame: the smallest item the codec
 * accepts encodes to more than 100 bytes (tests/test_firmware_core.py checks
 * this bound against the Python encoder).
 */
#define HELM_MAX_ITEMS 80u
#define HELM_STRING_POOL_BYTES HELM_FRAME_MAX_PAYLOAD

typedef uint16_t helm_str_t; /* offset into helm_model_t.strings */
#define HELM_STR_NULL ((helm_str_t)0xFFFFu)

typedef enum { HELM_ATTENTION_CALM, HELM_ATTENTION_NEW, HELM_ATTENTION_UNKNOWN } helm_attention_t;

typedef enum {
    HELM_KIND_DECISION,
    HELM_KIND_PR_READY,
    HELM_KIND_WORKER_PROBLEM,
    HELM_KIND_HERDR_BLOCKED
} helm_item_kind_t;

typedef enum { HELM_COLOR_RED, HELM_COLOR_AMBER, HELM_COLOR_BLUE, HELM_COLOR_GREEN } helm_color_t;

/* The four actions double as the four key names. */
typedef enum { HELM_ACTION_YES, HELM_ACTION_LATER, HELM_ACTION_HOLD, HELM_ACTION_FOCUS } helm_action_t;
#define HELM_ACTION_COUNT 4
#define HELM_ACTION_BIT(action) ((uint8_t)(1u << (unsigned)(action)))

typedef enum {
    HELM_CHECKS_NONE, /* null or absent */
    HELM_CHECKS_GREEN,
    HELM_CHECKS_RED,
    HELM_CHECKS_PENDING,
    HELM_CHECKS_UNKNOWN
} helm_checks_t;

typedef enum { HELM_RESULT_QUEUED, HELM_RESULT_REPLIED, HELM_RESULT_FAILED } helm_result_state_t;

typedef enum { HELM_TRI_NULL, HELM_TRI_FALSE, HELM_TRI_TRUE } helm_tri_t;

typedef struct {
    bool bridge_ok;
    helm_tri_t firstmate_can_receive;
    helm_str_t posture;      /* or HELM_STR_NULL */
    helm_str_t stale_reason; /* or HELM_STR_NULL */
    bool away; /* firstmate away: chimes muted, YES / LATER / HOLD locked (quiet mode only mutes, bridge side) */
    bool mac_locked; /* the Mac's session is locked: every key locked, SHOW ME too */
} helm_link_t;

typedef struct {
    int32_t decisions;
    int32_t working;
    int32_t queued;
    int32_t prs_ready;
    int32_t landed_today;
    int32_t herdr_working;
    int32_t herdr_blocked;
} helm_counts_t;

typedef struct {
    helm_str_t ref; /* stable id the bridge understands; echoed in `select` and `key` */
    helm_str_t short_id;
    helm_str_t home;
    helm_str_t detail; /* full text, shown only on a knob press */
    helm_str_t pr_url; /* or HELM_STR_NULL */
    helm_str_t project; /* repo name, or HELM_STR_NULL; the knob can filter by it */
    int32_t age_s;
    uint8_t actions; /* HELM_ACTION_BIT set; order and repeats are not kept */
    helm_item_kind_t kind;
    helm_color_t color;
    helm_checks_t checks;
    bool unseen;
} helm_item_t;

/* An integer that may be unknown (null or absent). */
typedef struct {
    bool known;
    int32_t value;
} helm_opt_int_t;

/* What is left of the Claude usage windows. Unknown is never full. */
typedef struct {
    helm_opt_int_t five_hour_left; /* percent, 0 to 100 */
    helm_opt_int_t five_hour_resets_s;
    helm_opt_int_t week_left;
    helm_opt_int_t week_resets_s;
} helm_usage_t;

/* How full the herdr agents' context windows are. Unknown is never empty. */
typedef struct {
    helm_opt_int_t top_used;   /* percent of its window the fullest agent uses, 0 to 100 */
    helm_str_t top_agent;      /* that agent's pane title, or HELM_STR_NULL */
    helm_opt_int_t near_limit; /* agents near their limit, 0 or more */
} helm_context_t;

typedef struct {
    helm_str_t request_id;
    helm_str_t text;
    helm_result_state_t state;
} helm_result_t;

typedef struct {
    int64_t seq; /* +1 on every model sent; a gap means a frame was lost */
    helm_link_t link;
    helm_attention_t attention;
    int32_t unseen;
    helm_counts_t counts;
    uint16_t item_count;
    helm_item_t items[HELM_MAX_ITEMS];
    bool has_result;
    helm_result_t result;
    bool chime; /* play one chime for this model, once */
    helm_usage_t usage;
    helm_context_t context;
    uint16_t strings_used;
    char strings[HELM_STRING_POOL_BYTES];
} helm_model_t;

typedef enum {
    HELM_PARSE_OK = 0,
    HELM_PARSE_SYNTAX,       /* not JSON, or bytes after the top-level object */
    HELM_PARSE_UTF8,         /* invalid UTF-8, a lone surrogate, or U+0000 in a string */
    HELM_PARSE_NOT_MODEL,    /* no "t", or "t" is not "model" */
    HELM_PARSE_MISSING,      /* a required field is absent (or null where not allowed) */
    HELM_PARSE_TYPE,         /* a field has the wrong JSON type */
    HELM_PARSE_ENUM,         /* a string outside its enum */
    HELM_PARSE_RANGE,        /* an integer that does not fit its field, or a usage or context value out of bounds */
    HELM_PARSE_TOO_MANY,     /* more than HELM_MAX_ITEMS items */
    HELM_PARSE_TOO_DEEP,     /* nesting deeper than the parser allows */
    HELM_PARSE_TOO_LARGE     /* over HELM_FRAME_MAX_PAYLOAD bytes */
} helm_parse_status_t;

/*
 * Parse a "model" payload into `out`. On failure `out` holds partial data and
 * must not be used, so parse into a spare model and keep the current one.
 */
helm_parse_status_t helm_model_parse(const uint8_t *json, size_t len, helm_model_t *out);

/* A NUL-terminated string from the model's pool, or NULL for HELM_STR_NULL. */
const char *helm_model_str(const helm_model_t *model, helm_str_t s);

/* Wire names, as in helm/contract.py. */
const char *helm_attention_name(helm_attention_t v);
const char *helm_kind_name(helm_item_kind_t v);
const char *helm_color_name(helm_color_t v);
const char *helm_action_name(helm_action_t v);
const char *helm_checks_name(helm_checks_t v); /* NULL for HELM_CHECKS_NONE */
const char *helm_result_state_name(helm_result_state_t v);
const char *helm_parse_status_name(helm_parse_status_t v);

#ifdef __cplusplus
}
#endif

#endif /* HELM_MODEL_H */
