#include "helm_jsonw.h"

void helm_jsonw_init(helm_jsonw_t *w, uint8_t *buf, size_t cap)
{
    w->buf = buf;
    w->cap = cap;
    w->len = 0;
    w->overflow = false;
}

static void put(helm_jsonw_t *w, uint8_t c)
{
    if (w->overflow || w->len >= w->cap) {
        w->overflow = true;
        return;
    }
    w->buf[w->len++] = c;
}

void helm_jsonw_raw(helm_jsonw_t *w, const char *text)
{
    while (*text != '\0') {
        put(w, (uint8_t)*text++);
    }
}

void helm_jsonw_string(helm_jsonw_t *w, const char *s)
{
    static const char hex[] = "0123456789abcdef";
    put(w, '"');
    for (const uint8_t *p = (const uint8_t *)s; *p != '\0'; p++) {
        uint8_t c = *p;
        switch (c) {
        case '"':
            helm_jsonw_raw(w, "\\\"");
            break;
        case '\\':
            helm_jsonw_raw(w, "\\\\");
            break;
        case '\b':
            helm_jsonw_raw(w, "\\b");
            break;
        case '\f':
            helm_jsonw_raw(w, "\\f");
            break;
        case '\n':
            helm_jsonw_raw(w, "\\n");
            break;
        case '\r':
            helm_jsonw_raw(w, "\\r");
            break;
        case '\t':
            helm_jsonw_raw(w, "\\t");
            break;
        default:
            if (c < 0x20u) {
                helm_jsonw_raw(w, "\\u00");
                put(w, (uint8_t)hex[c >> 4]);
                put(w, (uint8_t)hex[c & 0x0Fu]);
            } else {
                put(w, c);
            }
        }
    }
    put(w, '"');
}

void helm_jsonw_int(helm_jsonw_t *w, int64_t v)
{
    char digits[20];
    int n = 0;
    /* Work in unsigned so INT64_MIN does not overflow. */
    uint64_t mag = v < 0 ? (uint64_t)0 - (uint64_t)v : (uint64_t)v;
    if (v < 0) {
        put(w, '-');
    }
    do {
        digits[n++] = (char)('0' + (int)(mag % 10u));
        mag /= 10u;
    } while (mag != 0);
    while (n > 0) {
        put(w, (uint8_t)digits[--n]);
    }
}

void helm_jsonw_bool(helm_jsonw_t *w, bool v)
{
    helm_jsonw_raw(w, v ? "true" : "false");
}
