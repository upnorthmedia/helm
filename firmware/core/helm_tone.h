/*
 * The chime's sound: one short sine tone with a quick rise and a falling
 * tail, as 16-bit mono PCM. Pure computation; the platform plays the
 * samples.
 */
#ifndef HELM_TONE_H
#define HELM_TONE_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define HELM_TONE_ATTACK_MS 3u

/* Samples in a tone of ms milliseconds at sample_rate. */
size_t helm_tone_samples(uint32_t sample_rate, uint32_t ms);

/*
 * Write a tone of hz into out: a linear rise over HELM_TONE_ATTACK_MS to
 * peak, then a squared fall to silence at the end, so it starts and stops
 * without a click. Writes min(cap, helm_tone_samples(...)) samples and
 * returns that count.
 */
size_t helm_tone(int16_t *out, size_t cap, uint32_t sample_rate, uint32_t hz, uint32_t ms, int16_t peak);

#ifdef __cplusplus
}
#endif

#endif /* HELM_TONE_H */
