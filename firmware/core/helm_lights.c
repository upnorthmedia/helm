#include "helm_lights.h"

#include <math.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

/* Colors from sim/render.py COLORS. */
static const helm_rgb_t RED = {0xef, 0x4b, 0x4b};
static const helm_rgb_t AMBER = {0xf0, 0xa9, 0x2e};
static const helm_rgb_t BLUE = {0x4c, 0x9e, 0xf5};
static const helm_rgb_t GREEN = {0x43, 0xc2, 0x6b};
static const helm_rgb_t WHITE = {0xe9, 0xed, 0xf2};
static const helm_rgb_t OFF = {0, 0, 0};

static uint8_t channel(uint8_t c, float f)
{
    return (uint8_t)lroundf((float)c * f);
}

/* c at fraction f (clamped to 0..1) of full, under the brightness cap. */
static helm_rgb_t scale(helm_rgb_t c, float f, uint8_t brightness)
{
    f = f < 0.0f ? 0.0f : (f > 1.0f ? 1.0f : f);
    f *= (float)brightness / 255.0f;
    return (helm_rgb_t){channel(c.r, f), channel(c.g, f), channel(c.b, f)};
}

static helm_rgb_t item_color(helm_color_t color)
{
    switch (color) {
    case HELM_COLOR_RED:
        return RED;
    case HELM_COLOR_AMBER:
        return AMBER;
    case HELM_COLOR_BLUE:
        return BLUE;
    case HELM_COLOR_GREEN:
        return GREEN;
    }
    return WHITE;
}

static helm_rgb_t key_color(helm_action_t key)
{
    switch (key) {
    case HELM_ACTION_YES:
        return GREEN;
    case HELM_ACTION_LATER:
        return BLUE;
    case HELM_ACTION_HOLD:
        return AMBER;
    case HELM_ACTION_FOCUS:
        return WHITE;
    }
    return WHITE;
}

/* White mixed in per tint, in permille. Pure white keeps the hue exactly. */
static const uint32_t TINT_WHITE_PERMILLE[HELM_TINT_COUNT] = {0u, 180u, 360u, 540u};

int helm_lights_project_tint(const char *project)
{
    if (project == NULL || project[0] == '\0') {
        return 0;
    }
    uint32_t hash = 2166136261u; /* FNV-1a, 32 bit */
    for (const unsigned char *p = (const unsigned char *)project; *p != '\0'; p++) {
        hash = (hash ^ *p) * 16777619u;
    }
    return 1 + (int)(hash % (HELM_TINT_COUNT - 1));
}

static uint8_t whiten(uint8_t c, uint32_t permille)
{
    return (uint8_t)(c + ((255u - c) * permille + 500u) / 1000u);
}

helm_rgb_t helm_lights_tint(helm_rgb_t color, int tint)
{
    uint32_t p = tint > 0 && tint < HELM_TINT_COUNT ? TINT_WHITE_PERMILLE[tint] : 0u;
    return (helm_rgb_t){whiten(color.r, p), whiten(color.g, p), whiten(color.b, p)};
}

bool helm_lights_context_hint(const helm_model_t *m)
{
    return m != NULL && m->context.near_limit.known && m->context.near_limit.value > 0;
}

int helm_lights_gauge(const helm_model_t *m)
{
    if (m == NULL || !m->usage.five_hour_left.known || !m->usage.week_left.known) {
        return -1;
    }
    int32_t left = m->usage.five_hour_left.value < m->usage.week_left.value ? m->usage.five_hour_left.value
                                                                            : m->usage.week_left.value;
    left = left < 0 ? 0 : (left > 100 ? 100 : left);
    return (int)((left * HELM_BAR_LIGHTS + 99) / 100); /* rounded up, so a little left still shows */
}

void helm_lights_compute(const helm_deck_t *deck, uint32_t now_ms, uint8_t brightness, helm_lights_t *out)
{
    for (int k = 0; k < HELM_ACTION_COUNT; k++) {
        helm_action_t key = (helm_action_t)k;
        out->keys[k] = helm_deck_key_lit(deck, key, now_ms) ? scale(key_color(key), 0.75f, brightness) : OFF;
    }
    out->knob = deck->muted ? scale(RED, 0.35f, brightness) : OFF;

    helm_rgb_t *bar = out->bar;
    helm_attention_t attention = helm_deck_attention(deck, now_ms);
    if (helm_deck_sweeping(deck, now_ms)) {
        /* sim: head = (now * 10) % (LED_COUNT + 3), now in seconds */
        uint32_t period = HELM_SWEEP_STEP_MS * (HELM_BAR_LIGHTS + 3);
        float head = (float)(now_ms % period) / (float)HELM_SWEEP_STEP_MS;
        for (int i = 0; i < HELM_BAR_LIGHTS; i++) {
            float d = fabsf((float)i - head) / 2.5f;
            bar[i] = scale(GREEN, 1.0f - (d > 1.0f ? 1.0f : d), brightness);
        }
    } else if (attention == HELM_ATTENTION_UNKNOWN) {
        for (int i = 0; i < HELM_BAR_LIGHTS; i++) {
            bar[i] = scale(AMBER, 0.55f, brightness);
        }
    } else if (attention == HELM_ATTENTION_NEW) {
        float phase = (float)(now_ms % HELM_PULSE_PERIOD_MS) / (float)HELM_PULSE_PERIOD_MS;
        float pulse = 0.55f + 0.45f * (0.5f + 0.5f * sinf(phase * 2.0f * (float)M_PI));
        const helm_model_t *m = helm_deck_model(deck);
        int n = 0;
        for (int i = 0; m != NULL && i < m->item_count && n < HELM_BAR_LIGHTS; i++) {
            if (m->items[i].unseen) {
                int tint = helm_lights_project_tint(helm_model_str(m, m->items[i].project));
                bar[n++] = scale(helm_lights_tint(item_color(m->items[i].color), tint), pulse, brightness);
            }
        }
        while (n < HELM_BAR_LIGHTS) {
            bar[n++] = OFF;
        }
    } else {
        const helm_model_t *m = helm_deck_model(deck);
        int lit = helm_lights_gauge(m);
        for (int i = 0; i < HELM_BAR_LIGHTS; i++) {
            bar[i] = scale(WHITE, i < lit ? 0.12f : (float)HELM_GAUGE_TRACK_PERMILLE / 1000.0f, brightness);
        }
        if (helm_lights_context_hint(m)) {
            bar[HELM_BAR_LIGHTS - 1] = scale(AMBER, (float)HELM_CONTEXT_HINT_PERMILLE / 1000.0f, brightness);
        }
    }
}
