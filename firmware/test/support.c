#include "support.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "helm_jsonw.h"

void helm_test_model_init(helm_model_t *m, int64_t seq)
{
    memset(m, 0, sizeof *m);
    m->seq = seq;
    m->link.bridge_ok = true;
    m->link.firstmate_can_receive = HELM_TRI_TRUE;
    m->link.posture = HELM_STR_NULL;
    m->link.stale_reason = HELM_STR_NULL;
    m->attention = HELM_ATTENTION_CALM;
    m->context.top_agent = HELM_STR_NULL;
}

helm_str_t helm_test_str(helm_model_t *m, const char *s)
{
    size_t n = strlen(s) + 1;
    if (m->strings_used + n > sizeof m->strings) {
        fprintf(stderr, "helm_test_str: pool full\n");
        abort();
    }
    helm_str_t at = m->strings_used;
    memcpy(m->strings + at, s, n);
    m->strings_used = (uint16_t)(at + n);
    return at;
}

static void put_str_or_null(helm_jsonw_t *w, const helm_model_t *m, helm_str_t s)
{
    const char *text = helm_model_str(m, s);
    if (text == NULL) {
        helm_jsonw_raw(w, "null");
    } else {
        helm_jsonw_string(w, text);
    }
}

static void put_opt_int(helm_jsonw_t *w, helm_opt_int_t v)
{
    if (v.known) {
        helm_jsonw_int(w, v.value);
    } else {
        helm_jsonw_raw(w, "null");
    }
}

size_t helm_test_model_json(const helm_model_t *m, uint8_t *out, size_t cap)
{
    helm_jsonw_t w;
    helm_jsonw_init(&w, out, cap);
    helm_jsonw_raw(&w, "{\"t\":\"model\",\"seq\":");
    helm_jsonw_int(&w, m->seq);
    helm_jsonw_raw(&w, ",\"link\":{\"bridge_ok\":");
    helm_jsonw_bool(&w, m->link.bridge_ok);
    helm_jsonw_raw(&w, ",\"firstmate_can_receive\":");
    helm_jsonw_raw(&w, m->link.firstmate_can_receive == HELM_TRI_NULL ? "null"
                       : m->link.firstmate_can_receive == HELM_TRI_TRUE ? "true" : "false");
    helm_jsonw_raw(&w, ",\"posture\":");
    put_str_or_null(&w, m, m->link.posture);
    helm_jsonw_raw(&w, ",\"stale_reason\":");
    put_str_or_null(&w, m, m->link.stale_reason);
    helm_jsonw_raw(&w, ",\"away\":");
    helm_jsonw_bool(&w, m->link.away);
    helm_jsonw_raw(&w, ",\"mac_locked\":");
    helm_jsonw_bool(&w, m->link.mac_locked);
    helm_jsonw_raw(&w, "},\"attention\":");
    helm_jsonw_string(&w, helm_attention_name(m->attention));
    helm_jsonw_raw(&w, ",\"unseen\":");
    helm_jsonw_int(&w, m->unseen);
    helm_jsonw_raw(&w, ",\"counts\":{\"decisions\":");
    helm_jsonw_int(&w, m->counts.decisions);
    helm_jsonw_raw(&w, ",\"working\":");
    helm_jsonw_int(&w, m->counts.working);
    helm_jsonw_raw(&w, ",\"queued\":");
    helm_jsonw_int(&w, m->counts.queued);
    helm_jsonw_raw(&w, ",\"prs_ready\":");
    helm_jsonw_int(&w, m->counts.prs_ready);
    helm_jsonw_raw(&w, ",\"landed_today\":");
    helm_jsonw_int(&w, m->counts.landed_today);
    helm_jsonw_raw(&w, ",\"herdr_working\":");
    helm_jsonw_int(&w, m->counts.herdr_working);
    helm_jsonw_raw(&w, ",\"herdr_blocked\":");
    helm_jsonw_int(&w, m->counts.herdr_blocked);
    helm_jsonw_raw(&w, "},\"items\":[");
    for (int i = 0; i < m->item_count; i++) {
        const helm_item_t *it = &m->items[i];
        helm_jsonw_raw(&w, i == 0 ? "{\"ref\":" : ",{\"ref\":");
        helm_jsonw_string(&w, helm_model_str(m, it->ref));
        helm_jsonw_raw(&w, ",\"kind\":");
        helm_jsonw_string(&w, helm_kind_name(it->kind));
        helm_jsonw_raw(&w, ",\"color\":");
        helm_jsonw_string(&w, helm_color_name(it->color));
        helm_jsonw_raw(&w, ",\"short_id\":");
        helm_jsonw_string(&w, helm_model_str(m, it->short_id));
        helm_jsonw_raw(&w, ",\"age_s\":");
        helm_jsonw_int(&w, it->age_s);
        helm_jsonw_raw(&w, ",\"unseen\":");
        helm_jsonw_bool(&w, it->unseen);
        helm_jsonw_raw(&w, ",\"home\":");
        helm_jsonw_string(&w, helm_model_str(m, it->home));
        helm_jsonw_raw(&w, ",\"detail\":");
        helm_jsonw_string(&w, helm_model_str(m, it->detail));
        helm_jsonw_raw(&w, ",\"actions\":[");
        bool first = true;
        for (int a = 0; a < HELM_ACTION_COUNT; a++) {
            if (it->actions & HELM_ACTION_BIT(a)) {
                if (!first) {
                    helm_jsonw_raw(&w, ",");
                }
                helm_jsonw_string(&w, helm_action_name((helm_action_t)a));
                first = false;
            }
        }
        helm_jsonw_raw(&w, "],\"pr_url\":");
        put_str_or_null(&w, m, it->pr_url);
        helm_jsonw_raw(&w, ",\"checks\":");
        if (it->checks == HELM_CHECKS_NONE) {
            helm_jsonw_raw(&w, "null");
        } else {
            helm_jsonw_string(&w, helm_checks_name(it->checks));
        }
        helm_jsonw_raw(&w, ",\"project\":");
        put_str_or_null(&w, m, it->project);
        helm_jsonw_raw(&w, "}");
    }
    helm_jsonw_raw(&w, "],\"result\":");
    if (m->has_result) {
        helm_jsonw_raw(&w, "{\"request_id\":");
        helm_jsonw_string(&w, helm_model_str(m, m->result.request_id));
        helm_jsonw_raw(&w, ",\"state\":");
        helm_jsonw_string(&w, helm_result_state_name(m->result.state));
        helm_jsonw_raw(&w, ",\"text\":");
        helm_jsonw_string(&w, helm_model_str(m, m->result.text));
        helm_jsonw_raw(&w, "}");
    } else {
        helm_jsonw_raw(&w, "null");
    }
    helm_jsonw_raw(&w, ",\"chime\":");
    helm_jsonw_bool(&w, m->chime);
    const char *usage_keys[] = {"five_hour_left", "five_hour_resets_s", "week_left", "week_resets_s"};
    const helm_opt_int_t *usage[] = {&m->usage.five_hour_left, &m->usage.five_hour_resets_s, &m->usage.week_left,
                                     &m->usage.week_resets_s};
    for (int i = 0; i < 4; i++) {
        helm_jsonw_raw(&w, i == 0 ? ",\"usage\":{\"" : ",\"");
        helm_jsonw_raw(&w, usage_keys[i]);
        helm_jsonw_raw(&w, "\":");
        if (usage[i]->known) {
            helm_jsonw_int(&w, usage[i]->value);
        } else {
            helm_jsonw_raw(&w, "null");
        }
    }
    helm_jsonw_raw(&w, "},\"context\":{\"top_used\":");
    put_opt_int(&w, m->context.top_used);
    helm_jsonw_raw(&w, ",\"top_agent\":");
    put_str_or_null(&w, m, m->context.top_agent);
    helm_jsonw_raw(&w, ",\"near_limit\":");
    put_opt_int(&w, m->context.near_limit);
    helm_jsonw_raw(&w, "}}");
    return w.overflow ? 0 : w.len;
}

static int nibble(char c)
{
    if (c >= '0' && c <= '9') {
        return c - '0';
    }
    if (c >= 'a' && c <= 'f') {
        return c - 'a' + 10;
    }
    if (c >= 'A' && c <= 'F') {
        return c - 'A' + 10;
    }
    return -1;
}

long helm_test_from_hex(const char *hex, size_t hex_len, uint8_t *out, size_t cap)
{
    if (hex_len % 2 != 0 || hex_len / 2 > cap) {
        return -1;
    }
    for (size_t i = 0; i < hex_len / 2; i++) {
        int hi = nibble(hex[2 * i]), lo = nibble(hex[2 * i + 1]);
        if (hi < 0 || lo < 0) {
            return -1;
        }
        out[i] = (uint8_t)((hi << 4) | lo);
    }
    return (long)(hex_len / 2);
}

void helm_test_to_hex(const uint8_t *data, size_t len, char *out)
{
    static const char digits[] = "0123456789abcdef";
    for (size_t i = 0; i < len; i++) {
        out[2 * i] = digits[data[i] >> 4];
        out[2 * i + 1] = digits[data[i] & 0x0Fu];
    }
    out[2 * len] = '\0';
}
