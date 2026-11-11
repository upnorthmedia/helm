/* SPDX-License-Identifier: MIT */
/* Derived from autonomous-ai/openharness (MIT, Copyright (c) 2026 Autonomous, Inc.); see THIRD_PARTY_NOTICES.md. */
/*
 * The Harness Pro binary frame (D9), byte for byte, matching helm/wire/frame.py.
 *
 * Wire format, little-endian throughout:
 *
 *     A5 48 | ver:u8 | type:u8 | len:u16 | payload[len] | crc16:u16
 *
 * The CRC is CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF, no reflection, no
 * final xor) over ver..payload; the magic is not covered. The decoder mirrors
 * the vendor's resync rules: scan for the magic, treat an impossible length as
 * noise and step one byte, and on a bad CRC drop one byte (not the whole
 * frame) because a real frame may start inside what looked like one.
 *
 * The decoder takes bytes one at a time into a fixed buffer and never
 * allocates. A frame is handed to a callback; its payload pointer is valid
 * only during that call.
 */
#ifndef HELM_FRAME_H
#define HELM_FRAME_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define HELM_FRAME_MAGIC0 0xA5u
#define HELM_FRAME_MAGIC1 0x48u /* 'H', the Harness product byte */
#define HELM_FRAME_VERSION 1u
#define HELM_FRAME_HEADER_BYTES 6u /* magic(2) + ver(1) + type(1) + len(2) */
#define HELM_FRAME_CRC_BYTES 2u
#define HELM_FRAME_MAX_PAYLOAD 8192u
#define HELM_FRAME_MAX (HELM_FRAME_HEADER_BYTES + HELM_FRAME_MAX_PAYLOAD + HELM_FRAME_CRC_BYTES)

#define HELM_FRAME_TYPE_JSON 0x01u /* UTF-8 JSON object with a "t" discriminator */
#define HELM_FRAME_TYPE_LOG 0x04u  /* one log line, device to host, raw bytes */

/* The vendor reader drops a partial frame after 300 ms with no bytes. */
#define HELM_FRAME_PARTIAL_EXPIRY_MS 300u

uint16_t helm_crc16(const uint8_t *data, size_t len);

/*
 * Write a complete frame into `out` and return its length, or 0 when the
 * payload is over HELM_FRAME_MAX_PAYLOAD or `cap` is too small. The payload
 * may already sit at out + HELM_FRAME_HEADER_BYTES (it is moved, not copied,
 * so overlap is fine), which lets a caller build JSON in place.
 */
size_t helm_frame_encode(uint8_t type, const uint8_t *payload, size_t len, uint8_t *out, size_t cap);

typedef struct {
    uint8_t version;
    uint8_t type;
    uint16_t len;
    const uint8_t *payload; /* valid only during the callback */
} helm_frame_t;

typedef void (*helm_frame_cb)(void *ctx, const helm_frame_t *frame);

typedef struct {
    uint8_t buf[HELM_FRAME_MAX];
    size_t len;
    uint32_t corrupt_frames;  /* bad CRC, or a partial frame dropped by expiry */
    uint32_t discarded_bytes; /* every byte that did not end up in a frame */
} helm_decoder_t;

void helm_decoder_init(helm_decoder_t *d);

/* Forget a partial frame; the counters survive (they show a trend). */
void helm_decoder_reset(helm_decoder_t *d);

/* True while part of a frame (or a lone trailing A5) is buffered. */
bool helm_decoder_pending(const helm_decoder_t *d);

/* Feed one byte. Calls `cb` for each frame it completes (a byte can complete
 * more than one, after a bad CRC uncovers frames inside the rejected bytes). */
void helm_decoder_push(helm_decoder_t *d, uint8_t byte, helm_frame_cb cb, void *ctx);

/* helm_decoder_push for each byte in turn. */
void helm_decoder_feed(helm_decoder_t *d, const uint8_t *data, size_t len, helm_frame_cb cb, void *ctx);

/* The link went quiet mid-frame: drop the partial and resync now. Call it
 * when HELM_FRAME_PARTIAL_EXPIRY_MS pass with no new bytes and
 * helm_decoder_pending() is true. */
void helm_decoder_expire(helm_decoder_t *d, helm_frame_cb cb, void *ctx);

#ifdef __cplusplus
}
#endif

#endif /* HELM_FRAME_H */
