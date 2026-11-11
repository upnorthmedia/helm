#include "helm_event.h"

#include "helm_frame.h"
#include "helm_jsonw.h"

const char *helm_event_type_name(helm_event_type_t type)
{
    static const char *const names[] = {"hello", "key", "knob", "knob_press", "select", "seen", "resync"};
    return (size_t)type < sizeof names / sizeof names[0] ? names[type] : "?";
}

const char *helm_key_phase_name(helm_key_phase_t phase)
{
    static const char *const names[] = {"down", "up", "held"};
    return (size_t)phase < sizeof names / sizeof names[0] ? names[phase] : "?";
}

size_t helm_event_payload(const helm_event_t *event, uint8_t *out, size_t cap)
{
    helm_jsonw_t w;
    helm_jsonw_init(&w, out, cap);
    helm_jsonw_raw(&w, "{\"t\":");
    helm_jsonw_string(&w, helm_event_type_name(event->type));
    switch (event->type) {
    case HELM_EVENT_HELLO:
        helm_jsonw_raw(&w, ",\"fw\":");
        helm_jsonw_string(&w, event->u.hello.fw);
        helm_jsonw_raw(&w, ",\"caps\":[");
        for (size_t i = 0; i < event->u.hello.cap_count; i++) {
            if (i > 0) {
                helm_jsonw_raw(&w, ",");
            }
            helm_jsonw_string(&w, event->u.hello.caps[i]);
        }
        helm_jsonw_raw(&w, "],\"product\":");
        helm_jsonw_string(&w, HELM_PRODUCT);
        break;
    case HELM_EVENT_KEY:
        helm_jsonw_raw(&w, ",\"key\":");
        helm_jsonw_string(&w, helm_action_name(event->u.key.key));
        helm_jsonw_raw(&w, ",\"phase\":");
        helm_jsonw_string(&w, helm_key_phase_name(event->u.key.phase));
        helm_jsonw_raw(&w, ",\"ref\":");
        if (event->u.key.ref != NULL) {
            helm_jsonw_string(&w, event->u.key.ref);
        } else {
            helm_jsonw_raw(&w, "null");
        }
        break;
    case HELM_EVENT_KNOB:
        helm_jsonw_raw(&w, ",\"delta\":");
        helm_jsonw_int(&w, event->u.knob.delta);
        break;
    case HELM_EVENT_KNOB_PRESS:
        helm_jsonw_raw(&w, ",\"long\":");
        helm_jsonw_bool(&w, event->u.knob_press.long_press);
        break;
    case HELM_EVENT_SELECT:
        helm_jsonw_raw(&w, ",\"ref\":");
        helm_jsonw_string(&w, event->u.select.ref);
        break;
    case HELM_EVENT_SEEN:
    case HELM_EVENT_RESYNC:
        break;
    }
    helm_jsonw_raw(&w, "}");
    return w.overflow ? 0 : w.len;
}

size_t helm_event_frame(const helm_event_t *event, uint8_t *out, size_t cap)
{
    if (cap < HELM_FRAME_HEADER_BYTES + HELM_FRAME_CRC_BYTES) {
        return 0;
    }
    size_t room = cap - HELM_FRAME_HEADER_BYTES - HELM_FRAME_CRC_BYTES;
    if (room > HELM_FRAME_MAX_PAYLOAD) {
        room = HELM_FRAME_MAX_PAYLOAD;
    }
    size_t len = helm_event_payload(event, out + HELM_FRAME_HEADER_BYTES, room);
    if (len == 0) {
        return 0;
    }
    return helm_frame_encode(HELM_FRAME_TYPE_JSON, out + HELM_FRAME_HEADER_BYTES, len, out, cap);
}
