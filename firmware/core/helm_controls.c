#include "helm_controls.h"

bool helm_debounce(helm_debounce_t *d, bool raw, uint32_t now_ms, uint32_t settle_ms)
{
    if (raw != d->raw) {
        d->raw = raw;
        d->since = now_ms;
        return false;
    }
    if (raw != d->down && now_ms - d->since >= settle_ms) {
        d->down = raw;
        return true;
    }
    return false;
}

helm_press_t helm_button(helm_button_t *b, bool raw, uint32_t now_ms, uint32_t settle_ms, uint32_t long_ms)
{
    if (helm_debounce(&b->switch_state, raw, now_ms, settle_ms)) {
        if (b->switch_state.down) {
            b->down_ms = now_ms;
            b->long_sent = false;
        } else if (!b->long_sent) {
            return HELM_PRESS_SHORT;
        }
        return HELM_PRESS_NONE;
    }
    if (b->switch_state.down && !b->long_sent && now_ms - b->down_ms >= long_ms) {
        b->long_sent = true;
        return HELM_PRESS_LONG;
    }
    return HELM_PRESS_NONE;
}
