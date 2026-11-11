// Compile check only: the core headers are usable from C++.
#include "helm_controls.h"
#include "helm_deck.h"
#include "helm_event.h"
#include "helm_frame.h"
#include "helm_jsonw.h"
#include "helm_knob.h"
#include "helm_lights.h"
#include "helm_model.h"
#include "helm_tone.h"

int helm_cxx_headers_compile(void)
{
    helm_event_t event{};
    event.type = HELM_EVENT_SEEN;
    return static_cast<int>(sizeof(helm_deck_t) > 0 && sizeof(helm_knob_t) > 0 && sizeof(helm_lights_t) > 0 &&
                            event.type == HELM_EVENT_SEEN);
}
