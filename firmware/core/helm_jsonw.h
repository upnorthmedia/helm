/*
 * A bounded JSON writer whose output matches Python's
 * json.dumps(obj, separators=(",", ":"), ensure_ascii=False), the encoding
 * helm/wire/codec.py uses, byte for byte.
 *
 * Strings are written as given (UTF-8 passes through). Escaped, as Python
 * does: '"', '\\', the short forms \b \f \n \r \t, and every other byte below
 * 0x20 as \u00XX with lowercase hex. Nothing else is escaped.
 */
#ifndef HELM_JSONW_H
#define HELM_JSONW_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    uint8_t *buf;
    size_t cap;
    size_t len;
    bool overflow; /* set once anything did not fit; len stops growing */
} helm_jsonw_t;

void helm_jsonw_init(helm_jsonw_t *w, uint8_t *buf, size_t cap);
void helm_jsonw_raw(helm_jsonw_t *w, const char *text);
void helm_jsonw_string(helm_jsonw_t *w, const char *s);
void helm_jsonw_int(helm_jsonw_t *w, int64_t v);
void helm_jsonw_bool(helm_jsonw_t *w, bool v);

#ifdef __cplusplus
}
#endif

#endif /* HELM_JSONW_H */
