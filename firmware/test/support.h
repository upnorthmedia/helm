/* Host-only helpers for the tests: build models in memory and write them as
 * codec.encode_model would. The device itself never encodes a model. */
#ifndef HELM_TEST_SUPPORT_H
#define HELM_TEST_SUPPORT_H

#include <stddef.h>
#include <stdint.h>

#include "helm_model.h"

/* Empty model with seq, a healthy link, and no items or result. */
void helm_test_model_init(helm_model_t *m, int64_t seq);

/* Add a string to the pool; aborts when it does not fit. */
helm_str_t helm_test_str(helm_model_t *m, const char *s);

/* The model's payload JSON, byte for byte as helm/wire/codec.py writes it
 * (actions in contract order). Returns 0 when it does not fit. */
size_t helm_test_model_json(const helm_model_t *m, uint8_t *out, size_t cap);

/* hex helpers; return the byte count, or -1 on bad hex or overflow */
long helm_test_from_hex(const char *hex, size_t hex_len, uint8_t *out, size_t cap);
void helm_test_to_hex(const uint8_t *data, size_t len, char *out); /* out needs 2 * len + 1 */

#endif
