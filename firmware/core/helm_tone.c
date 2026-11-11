#include "helm_tone.h"

#include <math.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

size_t helm_tone_samples(uint32_t sample_rate, uint32_t ms)
{
    return (size_t)((uint64_t)sample_rate * ms / 1000u);
}

size_t helm_tone(int16_t *out, size_t cap, uint32_t sample_rate, uint32_t hz, uint32_t ms, int16_t peak)
{
    size_t n = helm_tone_samples(sample_rate, ms);
    if (n > cap) {
        n = cap;
    }
    size_t attack = helm_tone_samples(sample_rate, HELM_TONE_ATTACK_MS);
    if (attack > n) {
        attack = n;
    }
    size_t total = helm_tone_samples(sample_rate, ms);
    for (size_t i = 0; i < n; i++) {
        float env;
        if (i < attack) {
            env = (float)i / (float)attack;
        } else {
            float rest = (float)(total - i) / (float)(total - attack); /* 1 down to 0 */
            env = rest * rest;
        }
        double phase = 2.0 * M_PI * (double)hz * (double)i / (double)sample_rate;
        out[i] = (int16_t)lroundf(env * (float)peak * (float)sin(phase));
    }
    return n;
}
