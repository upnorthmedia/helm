/*
 * A strict JSON reader that walks the Model schema directly. No token array,
 * no allocation: strings are unescaped straight into the model's pool and
 * unknown values are skipped with a bounded nesting depth.
 */
#include "helm_model.h"

#include <string.h>

#define MAX_DEPTH 16  /* the model nests 4 deep; this leaves room for unknown keys */
#define KEY_BYTES 24  /* longest known key is 21 bytes ("firstmate_can_receive") */
#define ENUM_BYTES 16 /* longest enum value is 14 bytes ("worker_problem") */

typedef struct {
    const uint8_t *p;
    const uint8_t *end;
    helm_model_t *m;
    int depth;
} reader_t;

typedef enum { J_STRING, J_NUMBER, J_OBJECT, J_ARRAY, J_TRUE, J_FALSE, J_NULL, J_END, J_BAD } jtype_t;

#define TRY(expr)                                    \
    do {                                             \
        helm_parse_status_t try_status_ = (expr);    \
        if (try_status_ != HELM_PARSE_OK) {          \
            return try_status_;                      \
        }                                            \
    } while (0)

static const char *const ATTENTION_NAMES[] = {"calm", "new", "unknown"};
static const char *const KIND_NAMES[] = {"decision", "pr_ready", "worker_problem", "herdr_blocked"};
static const char *const COLOR_NAMES[] = {"red", "amber", "blue", "green"};
static const char *const ACTION_NAMES[] = {"yes", "later", "hold", "focus"};
static const char *const CHECKS_NAMES[] = {"green", "red", "pending", "unknown"}; /* from HELM_CHECKS_GREEN */
static const char *const RESULT_NAMES[] = {"queued", "replied", "failed"};

#define COUNT_OF(a) (sizeof(a) / sizeof((a)[0]))

/* Lexing */

static void skip_ws(reader_t *r)
{
    while (r->p < r->end && (*r->p == ' ' || *r->p == '\t' || *r->p == '\n' || *r->p == '\r')) {
        r->p++;
    }
}

static jtype_t peek_type(reader_t *r)
{
    skip_ws(r);
    if (r->p >= r->end) {
        return J_END;
    }
    switch (*r->p) {
    case '"':
        return J_STRING;
    case '{':
        return J_OBJECT;
    case '[':
        return J_ARRAY;
    case 't':
        return J_TRUE;
    case 'f':
        return J_FALSE;
    case 'n':
        return J_NULL;
    default:
        if (*r->p == '-' || (*r->p >= '0' && *r->p <= '9')) {
            return J_NUMBER;
        }
        return J_BAD;
    }
}

static helm_parse_status_t expect_char(reader_t *r, uint8_t c)
{
    skip_ws(r);
    if (r->p >= r->end || *r->p != c) {
        return HELM_PARSE_SYNTAX;
    }
    r->p++;
    return HELM_PARSE_OK;
}

static helm_parse_status_t expect_word(reader_t *r, const char *word)
{
    size_t n = strlen(word);
    if ((size_t)(r->end - r->p) < n || memcmp(r->p, word, n) != 0) {
        return HELM_PARSE_SYNTAX;
    }
    r->p += n;
    return HELM_PARSE_OK;
}

static int hex_value(uint8_t c)
{
    if (c >= '0' && c <= '9') {
        return c - '0';
    }
    if (c >= 'a' && c <= 'f') {
        return c - 'a' + 10;
    }
    if (c >= 'A' && c <= 'F') {
        return c - 'A' + 10;
    }
    return -1;
}

static helm_parse_status_t read_hex4(reader_t *r, uint32_t *out)
{
    if (r->end - r->p < 4) {
        return HELM_PARSE_SYNTAX;
    }
    uint32_t v = 0;
    for (int i = 0; i < 4; i++) {
        int h = hex_value(r->p[i]);
        if (h < 0) {
            return HELM_PARSE_SYNTAX;
        }
        v = (v << 4) | (uint32_t)h;
    }
    r->p += 4;
    *out = v;
    return HELM_PARSE_OK;
}

/* Collects decoded string bytes; `dst` may be NULL to only validate. */
typedef struct {
    char *dst;
    size_t cap;
    size_t len;
    bool overflow;
} sink_t;

static void sink_put(sink_t *s, uint8_t c)
{
    if (s->dst != NULL && s->len < s->cap) {
        s->dst[s->len] = (char)c;
    } else {
        s->overflow = true;
    }
    s->len++;
}

static void sink_put_codepoint(sink_t *s, uint32_t cp)
{
    if (cp < 0x80u) {
        sink_put(s, (uint8_t)cp);
    } else if (cp < 0x800u) {
        sink_put(s, (uint8_t)(0xC0u | (cp >> 6)));
        sink_put(s, (uint8_t)(0x80u | (cp & 0x3Fu)));
    } else if (cp < 0x10000u) {
        sink_put(s, (uint8_t)(0xE0u | (cp >> 12)));
        sink_put(s, (uint8_t)(0x80u | ((cp >> 6) & 0x3Fu)));
        sink_put(s, (uint8_t)(0x80u | (cp & 0x3Fu)));
    } else {
        sink_put(s, (uint8_t)(0xF0u | (cp >> 18)));
        sink_put(s, (uint8_t)(0x80u | ((cp >> 12) & 0x3Fu)));
        sink_put(s, (uint8_t)(0x80u | ((cp >> 6) & 0x3Fu)));
        sink_put(s, (uint8_t)(0x80u | (cp & 0x3Fu)));
    }
}

/* Copy one raw UTF-8 sequence starting with lead byte `c` (already consumed),
 * rejecting overlong forms, surrogates, and code points past U+10FFFF. */
static helm_parse_status_t copy_utf8(reader_t *r, uint8_t c, sink_t *s)
{
    size_t extra;
    uint8_t lo = 0x80u, hi = 0xBFu; /* allowed range of the first continuation byte */
    if (c >= 0xC2u && c <= 0xDFu) {
        extra = 1;
    } else if (c >= 0xE0u && c <= 0xEFu) {
        extra = 2;
        if (c == 0xE0u) {
            lo = 0xA0u;
        } else if (c == 0xEDu) {
            hi = 0x9Fu;
        }
    } else if (c >= 0xF0u && c <= 0xF4u) {
        extra = 3;
        if (c == 0xF0u) {
            lo = 0x90u;
        } else if (c == 0xF4u) {
            hi = 0x8Fu;
        }
    } else {
        return HELM_PARSE_UTF8;
    }
    if ((size_t)(r->end - r->p) < extra) {
        return HELM_PARSE_UTF8;
    }
    if (r->p[0] < lo || r->p[0] > hi) {
        return HELM_PARSE_UTF8;
    }
    for (size_t i = 1; i < extra; i++) {
        if (r->p[i] < 0x80u || r->p[i] > 0xBFu) {
            return HELM_PARSE_UTF8;
        }
    }
    sink_put(s, c);
    for (size_t i = 0; i < extra; i++) {
        sink_put(s, r->p[i]);
    }
    r->p += extra;
    return HELM_PARSE_OK;
}

/*
 * Read a JSON string into the sink (not NUL-terminated). U+0000 is refused:
 * the device keeps C strings, and the bridge never sends it.
 */
static helm_parse_status_t read_string(reader_t *r, sink_t *s)
{
    TRY(expect_char(r, '"'));
    for (;;) {
        if (r->p >= r->end) {
            return HELM_PARSE_SYNTAX;
        }
        uint8_t c = *r->p++;
        if (c == '"') {
            return HELM_PARSE_OK;
        }
        if (c < 0x20u) {
            return HELM_PARSE_SYNTAX;
        }
        if (c >= 0x80u) {
            TRY(copy_utf8(r, c, s));
            continue;
        }
        if (c != '\\') {
            sink_put(s, c);
            continue;
        }
        if (r->p >= r->end) {
            return HELM_PARSE_SYNTAX;
        }
        uint8_t e = *r->p++;
        switch (e) {
        case '"':
        case '\\':
        case '/':
            sink_put(s, e);
            break;
        case 'b':
            sink_put(s, '\b');
            break;
        case 'f':
            sink_put(s, '\f');
            break;
        case 'n':
            sink_put(s, '\n');
            break;
        case 'r':
            sink_put(s, '\r');
            break;
        case 't':
            sink_put(s, '\t');
            break;
        case 'u': {
            uint32_t cp;
            TRY(read_hex4(r, &cp));
            if (cp >= 0xD800u && cp <= 0xDBFFu) {
                uint32_t low;
                if (r->end - r->p < 2 || r->p[0] != '\\' || r->p[1] != 'u') {
                    return HELM_PARSE_UTF8;
                }
                r->p += 2;
                TRY(read_hex4(r, &low));
                if (low < 0xDC00u || low > 0xDFFFu) {
                    return HELM_PARSE_UTF8;
                }
                cp = 0x10000u + ((cp - 0xD800u) << 10) + (low - 0xDC00u);
            } else if (cp >= 0xDC00u && cp <= 0xDFFFu) {
                return HELM_PARSE_UTF8;
            } else if (cp == 0) {
                return HELM_PARSE_UTF8;
            }
            sink_put_codepoint(s, cp);
            break;
        }
        default:
            return HELM_PARSE_SYNTAX;
        }
    }
}

/*
 * Read a JSON number. `is_int` is false for a fraction or exponent; `fits` is
 * false when an integer is outside int64.
 */
static helm_parse_status_t read_number(reader_t *r, int64_t *value, bool *is_int, bool *fits)
{
    skip_ws(r);
    bool negative = false;
    uint64_t mag = 0;
    *is_int = true;
    *fits = true;
    if (r->p < r->end && *r->p == '-') {
        negative = true;
        r->p++;
    }
    if (r->p >= r->end || *r->p < '0' || *r->p > '9') {
        return HELM_PARSE_SYNTAX;
    }
    if (*r->p == '0') {
        r->p++;
    } else {
        while (r->p < r->end && *r->p >= '0' && *r->p <= '9') {
            uint64_t digit = (uint64_t)(*r->p - '0');
            if (mag > (UINT64_MAX - digit) / 10u) {
                *fits = false;
            } else {
                mag = mag * 10u + digit;
            }
            r->p++;
        }
    }
    if (r->p < r->end && *r->p == '.') {
        *is_int = false;
        r->p++;
        if (r->p >= r->end || *r->p < '0' || *r->p > '9') {
            return HELM_PARSE_SYNTAX;
        }
        while (r->p < r->end && *r->p >= '0' && *r->p <= '9') {
            r->p++;
        }
    }
    if (r->p < r->end && (*r->p == 'e' || *r->p == 'E')) {
        *is_int = false;
        r->p++;
        if (r->p < r->end && (*r->p == '+' || *r->p == '-')) {
            r->p++;
        }
        if (r->p >= r->end || *r->p < '0' || *r->p > '9') {
            return HELM_PARSE_SYNTAX;
        }
        while (r->p < r->end && *r->p >= '0' && *r->p <= '9') {
            r->p++;
        }
    }
    if (*fits) {
        if (negative) {
            if (mag > (uint64_t)INT64_MAX + 1u) {
                *fits = false;
            } else {
                *value = (mag == (uint64_t)INT64_MAX + 1u) ? INT64_MIN : -(int64_t)mag;
            }
        } else if (mag > (uint64_t)INT64_MAX) {
            *fits = false;
        } else {
            *value = (int64_t)mag;
        }
    }
    return HELM_PARSE_OK;
}

/* Objects and arrays */

static helm_parse_status_t open_container(reader_t *r, uint8_t c)
{
    TRY(expect_char(r, c));
    if (++r->depth > MAX_DEPTH) {
        return HELM_PARSE_TOO_DEEP;
    }
    return HELM_PARSE_OK;
}

/*
 * Advance to the next key of an open object. Sets *more to false at the
 * closing brace. A key longer than `cap` - 1 comes back empty, which matches
 * no known key, so its value is skipped. A closing brace is only accepted
 * first or after a value; after a comma a key must follow.
 */
static helm_parse_status_t next_key(reader_t *r, bool *first, char *key, size_t cap, bool *more)
{
    skip_ws(r);
    if (r->p < r->end && *r->p == '}') {
        r->p++;
        r->depth--;
        *more = false;
        return HELM_PARSE_OK;
    }
    if (!*first) {
        TRY(expect_char(r, ','));
    }
    *first = false;
    if (peek_type(r) != J_STRING) {
        return HELM_PARSE_SYNTAX;
    }
    sink_t s = {key, cap - 1, 0, false};
    TRY(read_string(r, &s));
    key[s.overflow ? 0 : s.len] = '\0';
    TRY(expect_char(r, ':'));
    *more = true;
    return HELM_PARSE_OK;
}

/* Advance to the next element of an open array (same rules as next_key). */
static helm_parse_status_t next_element(reader_t *r, bool *first, bool *more)
{
    skip_ws(r);
    if (r->p < r->end && *r->p == ']') {
        r->p++;
        r->depth--;
        *more = false;
        return HELM_PARSE_OK;
    }
    if (!*first) {
        TRY(expect_char(r, ','));
    }
    *first = false;
    *more = true;
    return HELM_PARSE_OK;
}

static helm_parse_status_t skip_value(reader_t *r)
{
    bool first = true, more = true;
    switch (peek_type(r)) {
    case J_STRING: {
        sink_t s = {NULL, 0, 0, false};
        return read_string(r, &s);
    }
    case J_NUMBER: {
        int64_t v;
        bool is_int, fits;
        return read_number(r, &v, &is_int, &fits);
    }
    case J_TRUE:
        return expect_word(r, "true");
    case J_FALSE:
        return expect_word(r, "false");
    case J_NULL:
        return expect_word(r, "null");
    case J_OBJECT: {
        char key[2];
        TRY(open_container(r, '{'));
        for (;;) {
            TRY(next_key(r, &first, key, sizeof key, &more));
            if (!more) {
                return HELM_PARSE_OK;
            }
            TRY(skip_value(r));
        }
    }
    case J_ARRAY:
        TRY(open_container(r, '['));
        for (;;) {
            TRY(next_element(r, &first, &more));
            if (!more) {
                return HELM_PARSE_OK;
            }
            TRY(skip_value(r));
        }
    default:
        return HELM_PARSE_SYNTAX;
    }
}

/* Typed fields. Each sets *present to false for null, as codec._get treats
 * null like a missing key. */

static helm_parse_status_t read_null(reader_t *r, bool *present)
{
    *present = false;
    return expect_word(r, "null");
}

static helm_parse_status_t field_bool(reader_t *r, bool *out, bool *present)
{
    switch (peek_type(r)) {
    case J_NULL:
        return read_null(r, present);
    case J_TRUE:
        *out = true;
        *present = true;
        return expect_word(r, "true");
    case J_FALSE:
        *out = false;
        *present = true;
        return expect_word(r, "false");
    case J_BAD:
    case J_END:
        return HELM_PARSE_SYNTAX;
    default:
        return HELM_PARSE_TYPE;
    }
}

static helm_parse_status_t field_int(reader_t *r, int64_t lo, int64_t hi, int64_t *out, bool *present)
{
    jtype_t t = peek_type(r);
    if (t == J_NULL) {
        return read_null(r, present);
    }
    if (t == J_BAD || t == J_END) {
        return HELM_PARSE_SYNTAX;
    }
    if (t != J_NUMBER) {
        return HELM_PARSE_TYPE;
    }
    int64_t v = 0;
    bool is_int, fits;
    TRY(read_number(r, &v, &is_int, &fits));
    if (!is_int) {
        return HELM_PARSE_TYPE;
    }
    if (!fits || v < lo || v > hi) {
        return HELM_PARSE_RANGE;
    }
    *out = v;
    *present = true;
    return HELM_PARSE_OK;
}

static helm_parse_status_t field_i32(reader_t *r, int32_t *out, bool *present)
{
    int64_t v = 0;
    TRY(field_int(r, INT32_MIN, INT32_MAX, &v, present));
    if (*present) {
        *out = (int32_t)v;
    }
    return HELM_PARSE_OK;
}

/* A string into the model's pool. */
static helm_parse_status_t field_str(reader_t *r, helm_str_t *out, bool *present)
{
    jtype_t t = peek_type(r);
    if (t == J_NULL) {
        *out = HELM_STR_NULL;
        return read_null(r, present);
    }
    if (t == J_BAD || t == J_END) {
        return HELM_PARSE_SYNTAX;
    }
    if (t != J_STRING) {
        return HELM_PARSE_TYPE;
    }
    helm_model_t *m = r->m;
    size_t used = m->strings_used;
    sink_t s = {m->strings + used, sizeof m->strings - used, 0, false};
    TRY(read_string(r, &s));
    /* Unreachable for a payload within HELM_FRAME_MAX_PAYLOAD; kept as a guard. */
    if (s.overflow || s.len + 1 > sizeof m->strings - used) {
        return HELM_PARSE_TOO_LARGE;
    }
    m->strings[used + s.len] = '\0';
    m->strings_used = (uint16_t)(used + s.len + 1);
    *out = (helm_str_t)used;
    *present = true;
    return HELM_PARSE_OK;
}

/* A string checked against `names`; *index is its position. */
static helm_parse_status_t field_enum(reader_t *r, const char *const *names, size_t count, int *index, bool *present)
{
    jtype_t t = peek_type(r);
    if (t == J_NULL) {
        return read_null(r, present);
    }
    if (t == J_BAD || t == J_END) {
        return HELM_PARSE_SYNTAX;
    }
    if (t != J_STRING) {
        return HELM_PARSE_TYPE;
    }
    char buf[ENUM_BYTES];
    sink_t s = {buf, sizeof buf - 1, 0, false};
    TRY(read_string(r, &s));
    if (!s.overflow) {
        buf[s.len] = '\0';
        for (size_t i = 0; i < count; i++) {
            if (strcmp(buf, names[i]) == 0) {
                *index = (int)i;
                *present = true;
                return HELM_PARSE_OK;
            }
        }
    }
    return HELM_PARSE_ENUM;
}

/* An object field: true when the value is an object (now open), false for null. */
static helm_parse_status_t field_object(reader_t *r, bool *present)
{
    jtype_t t = peek_type(r);
    if (t == J_NULL) {
        return read_null(r, present);
    }
    if (t == J_BAD || t == J_END) {
        return HELM_PARSE_SYNTAX;
    }
    if (t != J_OBJECT) {
        return HELM_PARSE_TYPE;
    }
    *present = true;
    return open_container(r, '{');
}

static helm_parse_status_t field_array(reader_t *r, bool *present)
{
    jtype_t t = peek_type(r);
    if (t == J_NULL) {
        return read_null(r, present);
    }
    if (t == J_BAD || t == J_END) {
        return HELM_PARSE_SYNTAX;
    }
    if (t != J_ARRAY) {
        return HELM_PARSE_TYPE;
    }
    *present = true;
    return open_container(r, '[');
}

/* Presence tracking: bit i set when required field i was seen non-null. */
#define SEEN(bits, i, present) ((present) ? ((bits) | (1u << (i))) : ((bits) & ~(1u << (i))))
#define ALL(n) ((1u << (n)) - 1u)

static helm_parse_status_t parse_link(reader_t *r, helm_link_t *link)
{
    bool first = true, more, present = false;
    bool bridge_ok_seen = false;
    char key[KEY_BYTES];
    link->firstmate_can_receive = HELM_TRI_NULL;
    link->posture = HELM_STR_NULL;
    link->stale_reason = HELM_STR_NULL;
    link->away = false;
    link->mac_locked = false;
    for (;;) {
        TRY(next_key(r, &first, key, sizeof key, &more));
        if (!more) {
            break;
        }
        if (strcmp(key, "bridge_ok") == 0) {
            TRY(field_bool(r, &link->bridge_ok, &present));
            bridge_ok_seen = present;
        } else if (strcmp(key, "firstmate_can_receive") == 0) {
            bool v = false;
            TRY(field_bool(r, &v, &present));
            link->firstmate_can_receive = !present ? HELM_TRI_NULL : (v ? HELM_TRI_TRUE : HELM_TRI_FALSE);
        } else if (strcmp(key, "posture") == 0) {
            TRY(field_str(r, &link->posture, &present));
        } else if (strcmp(key, "stale_reason") == 0) {
            TRY(field_str(r, &link->stale_reason, &present));
        } else if (strcmp(key, "away") == 0) {
            bool v = false;
            TRY(field_bool(r, &v, &present));
            link->away = present && v; /* null is false, as codec reads it */
        } else if (strcmp(key, "mac_locked") == 0) {
            bool v = false;
            TRY(field_bool(r, &v, &present));
            link->mac_locked = present && v;
        } else {
            TRY(skip_value(r));
        }
    }
    return bridge_ok_seen ? HELM_PARSE_OK : HELM_PARSE_MISSING;
}

static const char *const COUNT_KEYS[] = {
    "decisions", "working", "queued", "prs_ready", "landed_today", "herdr_working", "herdr_blocked",
};

static helm_parse_status_t parse_counts(reader_t *r, helm_counts_t *counts)
{
    int32_t *slots[] = {
        &counts->decisions,    &counts->working,       &counts->queued,        &counts->prs_ready,
        &counts->landed_today, &counts->herdr_working, &counts->herdr_blocked,
    };
    bool first = true, more, present = false;
    unsigned seen = 0;
    char key[KEY_BYTES];
    for (;;) {
        TRY(next_key(r, &first, key, sizeof key, &more));
        if (!more) {
            break;
        }
        size_t i = 0;
        while (i < COUNT_OF(COUNT_KEYS) && strcmp(key, COUNT_KEYS[i]) != 0) {
            i++;
        }
        if (i == COUNT_OF(COUNT_KEYS)) {
            TRY(skip_value(r));
            continue;
        }
        TRY(field_i32(r, slots[i], &present));
        seen = SEEN(seen, i, present);
    }
    return seen == ALL(COUNT_OF(COUNT_KEYS)) ? HELM_PARSE_OK : HELM_PARSE_MISSING;
}

static helm_parse_status_t parse_actions(reader_t *r, uint8_t *actions)
{
    bool first = true, more, present = false;
    *actions = 0;
    for (;;) {
        TRY(next_element(r, &first, &more));
        if (!more) {
            return HELM_PARSE_OK;
        }
        int a = 0;
        jtype_t t = peek_type(r);
        if (t == J_NULL) {
            /* codec: `None not in ACTIONS`, an unknown action */
            TRY(read_null(r, &present));
            return HELM_PARSE_ENUM;
        }
        TRY(field_enum(r, ACTION_NAMES, COUNT_OF(ACTION_NAMES), &a, &present));
        *actions = (uint8_t)(*actions | HELM_ACTION_BIT(a));
    }
}

enum { I_REF, I_KIND, I_COLOR, I_SHORT_ID, I_AGE, I_UNSEEN, I_HOME, I_DETAIL, I_ACTIONS, I_REQUIRED };

static helm_parse_status_t parse_item(reader_t *r, helm_item_t *item)
{
    bool first = true, more, present = false;
    unsigned seen = 0;
    char key[KEY_BYTES];
    memset(item, 0, sizeof *item);
    item->pr_url = HELM_STR_NULL;
    item->project = HELM_STR_NULL;
    item->checks = HELM_CHECKS_NONE;
    for (;;) {
        TRY(next_key(r, &first, key, sizeof key, &more));
        if (!more) {
            break;
        }
        int e = 0;
        if (strcmp(key, "ref") == 0) {
            TRY(field_str(r, &item->ref, &present));
            seen = SEEN(seen, I_REF, present);
        } else if (strcmp(key, "kind") == 0) {
            TRY(field_enum(r, KIND_NAMES, COUNT_OF(KIND_NAMES), &e, &present));
            item->kind = (helm_item_kind_t)e;
            seen = SEEN(seen, I_KIND, present);
        } else if (strcmp(key, "color") == 0) {
            TRY(field_enum(r, COLOR_NAMES, COUNT_OF(COLOR_NAMES), &e, &present));
            item->color = (helm_color_t)e;
            seen = SEEN(seen, I_COLOR, present);
        } else if (strcmp(key, "short_id") == 0) {
            TRY(field_str(r, &item->short_id, &present));
            seen = SEEN(seen, I_SHORT_ID, present);
        } else if (strcmp(key, "age_s") == 0) {
            TRY(field_i32(r, &item->age_s, &present));
            seen = SEEN(seen, I_AGE, present);
        } else if (strcmp(key, "unseen") == 0) {
            TRY(field_bool(r, &item->unseen, &present));
            seen = SEEN(seen, I_UNSEEN, present);
        } else if (strcmp(key, "home") == 0) {
            TRY(field_str(r, &item->home, &present));
            seen = SEEN(seen, I_HOME, present);
        } else if (strcmp(key, "detail") == 0) {
            TRY(field_str(r, &item->detail, &present));
            seen = SEEN(seen, I_DETAIL, present);
        } else if (strcmp(key, "actions") == 0) {
            present = false;
            TRY(field_array(r, &present));
            if (present) {
                TRY(parse_actions(r, &item->actions));
            }
            seen = SEEN(seen, I_ACTIONS, present);
        } else if (strcmp(key, "pr_url") == 0) {
            TRY(field_str(r, &item->pr_url, &present));
        } else if (strcmp(key, "project") == 0) {
            TRY(field_str(r, &item->project, &present));
        } else if (strcmp(key, "checks") == 0) {
            present = false;
            TRY(field_enum(r, CHECKS_NAMES, COUNT_OF(CHECKS_NAMES), &e, &present));
            item->checks = present ? (helm_checks_t)(HELM_CHECKS_GREEN + e) : HELM_CHECKS_NONE;
        } else {
            TRY(skip_value(r));
        }
    }
    return seen == ALL(I_REQUIRED) ? HELM_PARSE_OK : HELM_PARSE_MISSING;
}

static helm_parse_status_t parse_items(reader_t *r, helm_model_t *m)
{
    bool first = true, more, present = false;
    m->item_count = 0;
    for (;;) {
        TRY(next_element(r, &first, &more));
        if (!more) {
            return HELM_PARSE_OK;
        }
        if (m->item_count == HELM_MAX_ITEMS) {
            return HELM_PARSE_TOO_MANY;
        }
        present = false;
        TRY(field_object(r, &present));
        if (!present) {
            return HELM_PARSE_TYPE; /* codec: "item is not an object" */
        }
        TRY(parse_item(r, &m->items[m->item_count]));
        m->item_count++;
    }
}

enum { R_REQUEST_ID, R_STATE, R_TEXT, R_REQUIRED };

static helm_parse_status_t parse_result(reader_t *r, helm_result_t *res)
{
    bool first = true, more, present = false;
    unsigned seen = 0;
    char key[KEY_BYTES];
    for (;;) {
        TRY(next_key(r, &first, key, sizeof key, &more));
        if (!more) {
            break;
        }
        int e = 0;
        if (strcmp(key, "request_id") == 0) {
            TRY(field_str(r, &res->request_id, &present));
            seen = SEEN(seen, R_REQUEST_ID, present);
        } else if (strcmp(key, "state") == 0) {
            TRY(field_enum(r, RESULT_NAMES, COUNT_OF(RESULT_NAMES), &e, &present));
            res->state = (helm_result_state_t)e;
            seen = SEEN(seen, R_STATE, present);
        } else if (strcmp(key, "text") == 0) {
            TRY(field_str(r, &res->text, &present));
            seen = SEEN(seen, R_TEXT, present);
        } else {
            TRY(skip_value(r));
        }
    }
    return seen == ALL(R_REQUIRED) ? HELM_PARSE_OK : HELM_PARSE_MISSING;
}

/* Bounds as in codec.USAGE_BOUNDS: percent left 0 to 100, resets never negative. */
static const struct {
    const char *key;
    int32_t hi;
} USAGE_FIELDS[] = {
    {"five_hour_left", 100},
    {"five_hour_resets_s", INT32_MAX},
    {"week_left", 100},
    {"week_resets_s", INT32_MAX},
};

static helm_parse_status_t parse_usage(reader_t *r, helm_usage_t *usage)
{
    helm_opt_int_t *slots[] = {&usage->five_hour_left, &usage->five_hour_resets_s, &usage->week_left,
                               &usage->week_resets_s};
    bool first = true, more, present = false;
    char key[KEY_BYTES];
    for (;;) {
        TRY(next_key(r, &first, key, sizeof key, &more));
        if (!more) {
            return HELM_PARSE_OK;
        }
        size_t i = 0;
        while (i < COUNT_OF(USAGE_FIELDS) && strcmp(key, USAGE_FIELDS[i].key) != 0) {
            i++;
        }
        if (i == COUNT_OF(USAGE_FIELDS)) {
            TRY(skip_value(r));
            continue;
        }
        int64_t v = 0;
        present = false;
        TRY(field_int(r, 0, USAGE_FIELDS[i].hi, &v, &present));
        slots[i]->known = present;
        slots[i]->value = present ? (int32_t)v : 0;
    }
}

static void context_unknown(helm_context_t *context)
{
    memset(context, 0, sizeof *context);
    context->top_agent = HELM_STR_NULL;
}

/* Bounds as codec.CONTEXT_BOUNDS: a percent used, and a count. */
static helm_parse_status_t parse_context(reader_t *r, helm_context_t *context)
{
    bool first = true, more, present = false;
    char key[KEY_BYTES];
    for (;;) {
        TRY(next_key(r, &first, key, sizeof key, &more));
        if (!more) {
            return HELM_PARSE_OK;
        }
        helm_opt_int_t *slot = NULL;
        int64_t hi = 0;
        if (strcmp(key, "top_used") == 0) {
            slot = &context->top_used;
            hi = 100;
        } else if (strcmp(key, "near_limit") == 0) {
            slot = &context->near_limit;
            hi = INT32_MAX;
        } else if (strcmp(key, "top_agent") == 0) {
            TRY(field_str(r, &context->top_agent, &present));
            continue;
        } else {
            TRY(skip_value(r));
            continue;
        }
        int64_t v = 0;
        present = false;
        TRY(field_int(r, 0, hi, &v, &present));
        slot->known = present;
        slot->value = present ? (int32_t)v : 0;
    }
}

enum { M_SEQ, M_LINK, M_ATTENTION, M_UNSEEN, M_COUNTS, M_ITEMS, M_CHIME, M_REQUIRED };

static helm_parse_status_t parse_top(reader_t *r, helm_model_t *m)
{
    bool first = true, more, present = false;
    unsigned seen = 0;
    bool t_is_model = false;
    bool t_is_string = false;
    char key[KEY_BYTES];
    if (peek_type(r) != J_OBJECT) {
        /* Valid JSON that is not an object: codec says "not an object with a string 't'". */
        TRY(skip_value(r));
        skip_ws(r);
        return r->p == r->end ? HELM_PARSE_NOT_MODEL : HELM_PARSE_SYNTAX;
    }
    TRY(open_container(r, '{'));
    for (;;) {
        TRY(next_key(r, &first, key, sizeof key, &more));
        if (!more) {
            break;
        }
        int e = 0;
        if (strcmp(key, "t") == 0) {
            if (peek_type(r) == J_STRING) {
                char t[8];
                sink_t s = {t, sizeof t - 1, 0, false};
                TRY(read_string(r, &s));
                t_is_string = true;
                t_is_model = !s.overflow && s.len == 5 && memcmp(t, "model", 5) == 0;
            } else {
                TRY(skip_value(r));
                t_is_string = false;
                t_is_model = false;
            }
        } else if (strcmp(key, "seq") == 0) {
            present = false;
            TRY(field_int(r, INT64_MIN, INT64_MAX, &m->seq, &present));
            seen = SEEN(seen, M_SEQ, present);
        } else if (strcmp(key, "link") == 0) {
            present = false;
            TRY(field_object(r, &present));
            if (present) {
                TRY(parse_link(r, &m->link));
            }
            seen = SEEN(seen, M_LINK, present);
        } else if (strcmp(key, "attention") == 0) {
            TRY(field_enum(r, ATTENTION_NAMES, COUNT_OF(ATTENTION_NAMES), &e, &present));
            m->attention = (helm_attention_t)e;
            seen = SEEN(seen, M_ATTENTION, present);
        } else if (strcmp(key, "unseen") == 0) {
            TRY(field_i32(r, &m->unseen, &present));
            seen = SEEN(seen, M_UNSEEN, present);
        } else if (strcmp(key, "counts") == 0) {
            present = false;
            TRY(field_object(r, &present));
            if (present) {
                TRY(parse_counts(r, &m->counts));
            }
            seen = SEEN(seen, M_COUNTS, present);
        } else if (strcmp(key, "items") == 0) {
            present = false;
            TRY(field_array(r, &present));
            if (present) {
                TRY(parse_items(r, m));
            }
            seen = SEEN(seen, M_ITEMS, present);
        } else if (strcmp(key, "result") == 0) {
            present = false;
            TRY(field_object(r, &present));
            m->has_result = present;
            if (present) {
                TRY(parse_result(r, &m->result));
            }
        } else if (strcmp(key, "chime") == 0) {
            TRY(field_bool(r, &m->chime, &present));
            seen = SEEN(seen, M_CHIME, present);
        } else if (strcmp(key, "usage") == 0) {
            present = false;
            memset(&m->usage, 0, sizeof m->usage);
            TRY(field_object(r, &present));
            if (present) {
                TRY(parse_usage(r, &m->usage));
            }
        } else if (strcmp(key, "context") == 0) {
            present = false;
            context_unknown(&m->context);
            TRY(field_object(r, &present));
            if (present) {
                TRY(parse_context(r, &m->context));
            }
        } else {
            TRY(skip_value(r));
        }
    }
    skip_ws(r);
    if (r->p != r->end) {
        return HELM_PARSE_SYNTAX;
    }
    if (!t_is_string || !t_is_model) {
        return HELM_PARSE_NOT_MODEL;
    }
    return seen == ALL(M_REQUIRED) ? HELM_PARSE_OK : HELM_PARSE_MISSING;
}

helm_parse_status_t helm_model_parse(const uint8_t *json, size_t len, helm_model_t *out)
{
    if (len > HELM_FRAME_MAX_PAYLOAD) {
        return HELM_PARSE_TOO_LARGE;
    }
    reader_t r = {json, json + len, out, 0};
    out->item_count = 0;
    out->has_result = false;
    memset(&out->usage, 0, sizeof out->usage); /* absent: all unknown */
    context_unknown(&out->context);
    out->strings_used = 0;
    return parse_top(&r, out);
}

const char *helm_model_str(const helm_model_t *model, helm_str_t s)
{
    if (s == HELM_STR_NULL || s >= model->strings_used) {
        return NULL;
    }
    return model->strings + s;
}

#define NAME_OF(table, v) (((size_t)(v) < COUNT_OF(table)) ? (table)[(size_t)(v)] : "?")

const char *helm_attention_name(helm_attention_t v)
{
    return NAME_OF(ATTENTION_NAMES, v);
}

const char *helm_kind_name(helm_item_kind_t v)
{
    return NAME_OF(KIND_NAMES, v);
}

const char *helm_color_name(helm_color_t v)
{
    return NAME_OF(COLOR_NAMES, v);
}

const char *helm_action_name(helm_action_t v)
{
    return NAME_OF(ACTION_NAMES, v);
}

const char *helm_checks_name(helm_checks_t v)
{
    if (v == HELM_CHECKS_NONE) {
        return NULL;
    }
    return NAME_OF(CHECKS_NAMES, (size_t)v - 1u);
}

const char *helm_result_state_name(helm_result_state_t v)
{
    return NAME_OF(RESULT_NAMES, v);
}

const char *helm_parse_status_name(helm_parse_status_t v)
{
    static const char *const names[] = {
        "ok", "syntax", "utf8", "not_model", "missing", "type", "enum", "range", "too_many", "too_deep", "too_large",
    };
    return NAME_OF(names, v);
}
