/*
 * The deck's lights, worked out from the deck state: the four key lights,
 * the 8-light bar, and the knob's own light. A port of the simulator's light
 * bar and key faces (sim/render.py, _light_bar and _keys), with one
 * difference: a physical light fades toward black, not toward the
 * simulator's grey "off" key face.
 *
 * Pure computation, no hardware: the platform sends the colors to its lights.
 */
#ifndef HELM_LIGHTS_H
#define HELM_LIGHTS_H

#include <stdbool.h>
#include <stdint.h>

#include "helm_deck.h"

#ifdef __cplusplus
extern "C" {
#endif

#define HELM_BAR_LIGHTS 8
#define HELM_PULSE_PERIOD_MS 1400u /* the "new" pulse, as in the simulator */
#define HELM_SWEEP_STEP_MS 100u    /* the green sweep's head moves one light per step */
#define HELM_GAUGE_TRACK_PERMILLE 30u /* calm: the unlit part of the usage gauge, white at 3 % */
#define HELM_CONTEXT_HINT_PERMILLE 300u /* calm: the last light, amber, when an agent is near its context limit */
#define HELM_TINT_COUNT 4 /* tint 0 is an item with no project; 1 to 3 come from the project's name */

typedef struct {
    uint8_t r, g, b;
} helm_rgb_t;

typedef struct {
    helm_rgb_t keys[HELM_ACTION_COUNT]; /* indexed by helm_action_t */
    helm_rgb_t bar[HELM_BAR_LIGHTS];    /* left to right */
    helm_rgb_t knob;                    /* lit while the chime is muted */
} helm_lights_t;

/*
 * Project tints. A tint never changes a light's hue: it mixes pure white
 * into the kind's color (0, 18, 36, or 54 %), so red, amber, blue, and green
 * read as themselves at every tint, only paler. Hue tints were tried and
 * dropped: red and amber sit 38 degrees apart, and any hue but cyan pulls
 * one toward the other. Paleness is also independent of the "new" pulse,
 * which changes brightness. An item with no project gets tint 0; a project
 * gets 1 + (32-bit FNV-1a of its UTF-8 bytes) % 3, the same in
 * sim/render.py, so a project keeps its tint from day to day.
 */
int helm_lights_project_tint(const char *project);
helm_rgb_t helm_lights_tint(helm_rgb_t color, int tint);

/*
 * Every color is scaled by brightness / 255, a cap on the whole deck's light
 * (twelve RGB lights at full white draw far more than the deck needs).
 *
 * Bar, in order of precedence:
 *   sweep   (2 s after something lands): a green head runs left to right
 *   unknown (link down or firstmate not listening): all amber at 55 %
 *   new     (something unseen): one light per unseen item in its kind's
 *           color, tinted by its project, pulsing between 55 % and 100 %
 *           every 1.4 s; the rest off
 *   calm:   the usage gauge: what is left of the tighter Claude window
 *           (5 hour or week), as ceil(left * 8 / 100) lights in white at
 *           12 % from the left, the rest a white track at 3 %. When either
 *           window is unknown no light is lit, only the track: unknown never
 *           looks full. While some herdr agent is near its context limit,
 *           the last light is amber at 30 % instead (an unknown context
 *           gauge shows no hint).
 * Keys: lit at 75 % in their own color (YES green, LATER blue, HOLD amber,
 * SHOW ME white) only when helm_deck_key_lit says the action applies.
 * Knob: red at 35 % while muted, else off.
 *
 * The pulse and sweep follow now_ms modulo their period, so they stay smooth
 * however long the deck has been up.
 */
/* Lights the calm bar fills for the model's usage, 0 to 8, or -1 when unknown. */
int helm_lights_gauge(const helm_model_t *m);
/* True when the calm bar shows the context hint: some agent is near its limit. */
bool helm_lights_context_hint(const helm_model_t *m);

void helm_lights_compute(const helm_deck_t *deck, uint32_t now_ms, uint8_t brightness, helm_lights_t *out);

#ifdef __cplusplus
}
#endif

#endif /* HELM_LIGHTS_H */
