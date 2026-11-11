#include "helm_deck.h"

#include <string.h>

static uint32_t since(uint32_t now, uint32_t then)
{
    return now - then; /* unsigned subtraction is correct across a wrap */
}

static void emit(helm_deck_t *deck, const helm_event_t *event)
{
    if (deck->cfg.emit != NULL) {
        deck->cfg.emit(deck->cfg.ctx, event);
    }
}

static void emit_simple(helm_deck_t *deck, helm_event_type_t type)
{
    helm_event_t event;
    memset(&event, 0, sizeof event);
    event.type = type;
    emit(deck, &event);
}

static void emit_key(helm_deck_t *deck, helm_action_t key, helm_key_phase_t phase)
{
    helm_event_t event;
    memset(&event, 0, sizeof event);
    event.type = HELM_EVENT_KEY;
    event.u.key.key = key;
    event.u.key.phase = phase;
    emit(deck, &event);
}

static void send_hello(helm_deck_t *deck, uint32_t now)
{
    helm_event_t event;
    memset(&event, 0, sizeof event);
    event.type = HELM_EVENT_HELLO;
    event.u.hello.fw = deck->cfg.fw != NULL ? deck->cfg.fw : "";
    event.u.hello.caps = deck->cfg.caps;
    event.u.hello.cap_count = deck->cfg.caps != NULL ? deck->cfg.cap_count : 0;
    deck->hello_sent = true;
    deck->last_hello_ms = now;
    emit(deck, &event);
}

/* Copy at most cap - 1 bytes, never splitting a UTF-8 sequence. */
static void copy_display(char *dst, size_t cap, const char *src)
{
    size_t n = src != NULL ? strlen(src) : 0;
    if (n >= cap) {
        n = cap - 1;
        while (n > 0 && ((uint8_t)src[n] & 0xC0u) == 0x80u) {
            n--;
        }
    }
    if (n > 0) {
        memcpy(dst, src, n);
    }
    dst[n] = '\0';
}

const helm_model_t *helm_deck_model(const helm_deck_t *deck)
{
    return deck->has_model ? &deck->models[deck->current] : NULL;
}

static const char *item_ref(const helm_model_t *m, int index)
{
    return helm_model_str(m, m->items[index].ref);
}

const helm_item_t *helm_deck_selected(const helm_deck_t *deck)
{
    const helm_model_t *m = helm_deck_model(deck);
    if (m == NULL || deck->selected < 0 || deck->selected >= m->item_count) {
        return NULL;
    }
    return &m->items[deck->selected];
}

/* Project views */

static const char *item_project(const helm_model_t *m, int index)
{
    const char *p = helm_model_str(m, m->items[index].project);
    return p != NULL && p[0] != '\0' ? p : NULL;
}

static bool in_view_of(const helm_model_t *m, const char *view, int index)
{
    if (view[0] == '\0') {
        return true;
    }
    const char *p = item_project(m, index);
    return p != NULL && strcmp(p, view) == 0;
}

const char *helm_deck_view(const helm_deck_t *deck)
{
    return deck->view[0] != '\0' ? deck->view : NULL;
}

bool helm_deck_has_views(const helm_deck_t *deck)
{
    const helm_model_t *m = helm_deck_model(deck);
    for (int i = 0; m != NULL && i < m->item_count; i++) {
        if (item_project(m, i) != NULL) {
            return true;
        }
    }
    return false;
}

int helm_deck_view_count(const helm_deck_t *deck)
{
    const helm_model_t *m = helm_deck_model(deck);
    int n = 0;
    for (int i = 0; m != NULL && i < m->item_count; i++) {
        n += in_view_of(m, deck->view, i);
    }
    return n;
}

int helm_deck_view_item(const helm_deck_t *deck, int pos)
{
    const helm_model_t *m = helm_deck_model(deck);
    for (int i = 0, n = 0; pos >= 0 && m != NULL && i < m->item_count; i++) {
        if (in_view_of(m, deck->view, i) && n++ == pos) {
            return i;
        }
    }
    return -1;
}

int helm_deck_view_pos(const helm_deck_t *deck, int index)
{
    const helm_model_t *m = helm_deck_model(deck);
    if (m == NULL || index < 0 || index >= m->item_count || !in_view_of(m, deck->view, index)) {
        return -1;
    }
    int pos = 0;
    for (int i = 0; i < index; i++) {
        pos += in_view_of(m, deck->view, i);
    }
    return pos;
}

/* "all" plus each distinct project. */
static int count_views(const helm_model_t *m)
{
    int n = 1;
    for (int i = 0; i < m->item_count; i++) {
        const char *p = item_project(m, i);
        bool repeat = false;
        for (int j = 0; p != NULL && j < i && !repeat; j++) {
            const char *q = item_project(m, j);
            repeat = q != NULL && strcmp(p, q) == 0;
        }
        n += p != NULL && !repeat;
    }
    return n;
}

/* The next (dir > 0) or previous project view in byte order; "all" sits
 * before the first project and after the last. */
static void step_view(helm_deck_t *deck, int dir)
{
    const helm_model_t *m = helm_deck_model(deck);
    const char *best = NULL;
    for (int i = 0; i < m->item_count; i++) {
        const char *p = item_project(m, i);
        if (p == NULL) {
            continue;
        }
        int vs_view = deck->view[0] != '\0' ? strcmp(p, deck->view) : dir;
        if (dir > 0 ? vs_view <= 0 : vs_view >= 0) {
            continue;
        }
        if (best == NULL || (dir > 0 ? strcmp(p, best) < 0 : strcmp(p, best) > 0)) {
            best = p;
        }
    }
    copy_display(deck->view, sizeof deck->view, best != NULL ? best : "");
}

/* Select item `index` (or none) and tell the bridge when the ref changes. */
static void select_index(helm_deck_t *deck, int index)
{
    const helm_model_t *m = helm_deck_model(deck);
    const char *old_ref = helm_deck_selected(deck) != NULL ? item_ref(m, deck->selected) : NULL;
    deck->selected = index;
    if (index < 0) {
        return;
    }
    const char *ref = item_ref(m, index);
    if (old_ref != NULL && strcmp(old_ref, ref) == 0) {
        return;
    }
    helm_event_t event;
    memset(&event, 0, sizeof event);
    event.type = HELM_EVENT_SELECT;
    event.u.select.ref = ref;
    emit(deck, &event);
}

/* Link and attention */

static bool model_silent(const helm_deck_t *deck, uint32_t now)
{
    return !deck->has_model || deck->silent || since(now, deck->last_model_ms) > HELM_LINK_TIMEOUT_MS;
}

helm_link_state_t helm_deck_link_state(const helm_deck_t *deck, uint32_t now_ms)
{
    if (!deck->has_model) {
        return HELM_LINK_WAITING;
    }
    if (model_silent(deck, now_ms)) {
        return HELM_LINK_SILENT;
    }
    const helm_model_t *m = helm_deck_model(deck);
    if (!m->link.bridge_ok) {
        return HELM_LINK_BRIDGE_PROBLEM;
    }
    if (m->link.firstmate_can_receive != HELM_TRI_TRUE) {
        return HELM_LINK_FIRSTMATE_NOT_LISTENING;
    }
    return HELM_LINK_OK;
}

helm_attention_t helm_deck_attention(const helm_deck_t *deck, uint32_t now_ms)
{
    if (helm_deck_link_state(deck, now_ms) != HELM_LINK_OK) {
        return HELM_ATTENTION_UNKNOWN;
    }
    return helm_deck_model(deck)->attention;
}

bool helm_deck_key_lit(const helm_deck_t *deck, helm_action_t key, uint32_t now_ms)
{
    if (deck->holding) {
        return key == deck->hold_key;
    }
    if (deck->screen == HELM_SCREEN_RESULT || helm_deck_link_state(deck, now_ms) != HELM_LINK_OK) {
        return false;
    }
    const helm_item_t *item = helm_deck_selected(deck);
    const helm_link_t *link = &helm_deck_model(deck)->link;
    if (item == NULL || link->mac_locked || (key != HELM_ACTION_FOCUS && link->away)) {
        return false;
    }
    return (item->actions & HELM_ACTION_BIT(key)) != 0;
}

uint32_t helm_deck_hold_progress_permille(const helm_deck_t *deck, uint32_t now_ms)
{
    if (!deck->holding) {
        return 0;
    }
    uint32_t held = since(now_ms, deck->hold_started_ms);
    return held >= HELM_HOLD_MS ? 1000u : held * 1000u / HELM_HOLD_MS;
}

bool helm_deck_sweeping(const helm_deck_t *deck, uint32_t now_ms)
{
    return deck->sweeping && since(now_ms, deck->sweep_started_ms) < HELM_SWEEP_MS;
}

bool helm_deck_take_chime(helm_deck_t *deck)
{
    if (deck->chimes == 0) {
        return false;
    }
    deck->chimes--;
    return true;
}

int helm_deck_list_first(const helm_deck_t *deck, int rows)
{
    int count = helm_deck_view_count(deck);
    int sel = helm_deck_view_pos(deck, deck->selected);
    sel = sel < 0 ? 0 : sel;
    int first = sel - rows / 2;
    if (first > count - rows) {
        first = count - rows;
    }
    return first < 0 ? 0 : first;
}

void helm_deck_clamp_detail_scroll(helm_deck_t *deck, int32_t total_lines, int32_t visible_lines)
{
    int32_t max_first = total_lines > visible_lines ? total_lines - visible_lines : 0;
    if (deck->detail_scroll > max_first) {
        deck->detail_scroll = max_first;
    }
}

/* Inputs from the bridge */

static void on_model(helm_deck_t *deck, uint32_t now)
{
    const helm_model_t *prev = helm_deck_model(deck);
    const helm_model_t *m = &deck->models[deck->current ^ 1u];

    /* A view whose project left the model goes back to "all". */
    bool view_found = deck->view[0] == '\0';
    for (int i = 0; !view_found && i < m->item_count; i++) {
        view_found = in_view_of(m, deck->view, i);
    }
    if (!view_found) {
        deck->view[0] = '\0';
    }

    /* Selection follows the ref, not the row, across a reorder, while it stays in the view. */
    int selected = -1;
    if (prev != NULL && helm_deck_selected(deck) != NULL) {
        const char *ref = item_ref(prev, deck->selected);
        for (int i = 0; i < m->item_count; i++) {
            if (strcmp(item_ref(m, i), ref) == 0 && in_view_of(m, deck->view, i)) {
                selected = i;
                break;
            }
        }
    }
    bool landed = prev != NULL && m->counts.landed_today > prev->counts.landed_today;

    deck->current ^= 1u;
    deck->has_model = true;
    deck->silent = false;
    deck->last_model_ms = now;
    deck->selected = selected;

    if (m->chime && !(deck->chime_seq_known && deck->chime_seq == m->seq)) {
        deck->chime_seq_known = true;
        deck->chime_seq = m->seq;
        if (!deck->muted && !m->link.away) {
            deck->chimes++;
        }
    }
    if (landed) {
        deck->sweeping = true;
        deck->sweep_started_ms = now;
    }
    /* The held item left the list: cancel rather than let the hold land on
     * whatever gets selected next (sim/state.py does the same). Firstmate
     * going away, or the Mac locking, locks the keys, so it cancels a hold too. */
    if (deck->holding && (selected < 0 || m->link.away || m->link.mac_locked)) {
        deck->holding = false;
        deck->screen = deck->hold_return;
        emit_key(deck, deck->hold_key, HELM_KEY_UP);
    }
    if (selected < 0) {
        int first = helm_deck_view_item(deck, 0);
        if (first >= 0) {
            select_index(deck, first);
        }
    }
    if ((deck->screen == HELM_SCREEN_LIST || deck->screen == HELM_SCREEN_DETAIL) && helm_deck_view_count(deck) == 0) {
        deck->screen = HELM_SCREEN_HOME;
    }
    if (deck->screen == HELM_SCREEN_DETAIL && helm_deck_selected(deck) == NULL) {
        deck->screen = HELM_SCREEN_LIST;
    }
    if (deck->pending && m->has_result && m->seq > deck->pending_seq_after) {
        deck->pending_has_result = true;
        deck->pending_state = m->result.state;
        copy_display(deck->pending_text, sizeof deck->pending_text, helm_model_str(m, m->result.text));
        if (m->result.state != HELM_RESULT_QUEUED && !deck->pending_final) {
            deck->pending_final = true;
            deck->pending_final_ms = now;
        }
    }
}

typedef struct {
    helm_deck_t *deck;
    uint32_t now;
} frame_ctx_t;

static void on_frame(void *ctx, const helm_frame_t *frame)
{
    frame_ctx_t *fc = (frame_ctx_t *)ctx;
    helm_deck_t *deck = fc->deck;
    if (frame->type != HELM_FRAME_TYPE_JSON) {
        return;
    }
    helm_model_t *next = &deck->models[deck->current ^ 1u];
    helm_parse_status_t status = helm_model_parse(frame->payload, frame->len, next);
    if (status != HELM_PARSE_OK) {
        deck->bad_messages++;
        deck->last_parse_error = status;
        return;
    }
    bool went_back = deck->have_seq && next->seq < deck->last_seq;
    if (deck->have_seq && next->seq != deck->last_seq + 1) {
        deck->seq_gaps++;
        deck->resync_pending = true;
    }
    /* A bridge that opened the port after our hello flushed it, or one whose
     * seq went backwards (it restarted), has not heard from us yet. */
    if (model_silent(deck, fc->now) || went_back) {
        send_hello(deck, fc->now);
    }
    deck->have_seq = true;
    deck->last_seq = next->seq;
    on_model(deck, fc->now);
}

/* A seq gap or a bad CRC means a model was lost: ask for it, at most every 2 s. */
static void check_resync(helm_deck_t *deck, uint32_t now)
{
    if (deck->decoder.corrupt_frames != deck->corrupt_seen) {
        deck->corrupt_seen = deck->decoder.corrupt_frames;
        deck->resync_pending = true;
    }
    if (deck->resync_pending && (!deck->resync_sent || since(now, deck->last_resync_ms) >= HELM_RESYNC_MIN_INTERVAL_MS)) {
        deck->resync_pending = false;
        deck->resync_sent = true;
        deck->last_resync_ms = now;
        emit_simple(deck, HELM_EVENT_RESYNC);
    }
}

void helm_deck_rx(helm_deck_t *deck, const uint8_t *data, size_t len, uint32_t now_ms)
{
    if (len == 0) {
        return;
    }
    deck->last_rx_ms = now_ms;
    frame_ctx_t fc = {deck, now_ms};
    helm_decoder_feed(&deck->decoder, data, len, on_frame, &fc);
    check_resync(deck, now_ms);
}

static void leave_result(helm_deck_t *deck)
{
    deck->pending = false;
    deck->screen = HELM_SCREEN_HOME;
}

void helm_deck_tick(helm_deck_t *deck, uint32_t now_ms)
{
    if (helm_decoder_pending(&deck->decoder) && since(now_ms, deck->last_rx_ms) >= HELM_FRAME_PARTIAL_EXPIRY_MS) {
        frame_ctx_t fc = {deck, now_ms};
        helm_decoder_expire(&deck->decoder, on_frame, &fc);
    }
    check_resync(deck, now_ms);

    if (deck->has_model && since(now_ms, deck->last_model_ms) > HELM_LINK_TIMEOUT_MS) {
        deck->silent = true;
    }
    /* Say hello first, then until a bridge answers, and again whenever it goes quiet. */
    if (model_silent(deck, now_ms) && (!deck->hello_sent || since(now_ms, deck->last_hello_ms) >= HELM_HELLO_EVERY_MS)) {
        send_hello(deck, now_ms);
    }

    if (deck->holding && since(now_ms, deck->hold_started_ms) >= HELM_HOLD_MS) {
        const helm_model_t *m = helm_deck_model(deck);
        const helm_item_t *item = helm_deck_selected(deck);
        deck->holding = false;
        emit_key(deck, deck->hold_key, HELM_KEY_HELD);
        deck->pending = true;
        deck->pending_key = deck->hold_key;
        deck->pending_seq_after = m != NULL ? m->seq : -1;
        copy_display(deck->pending_short_id, sizeof deck->pending_short_id,
                     item != NULL ? helm_model_str(m, item->short_id) : "");
        deck->pending_has_result = false;
        deck->pending_text[0] = '\0';
        deck->pending_final = false;
        deck->screen = HELM_SCREEN_RESULT;
    }
    if (deck->screen == HELM_SCREEN_RESULT && deck->pending && deck->pending_final &&
        since(now_ms, deck->pending_final_ms) >= HELM_RESULT_LINGER_MS) {
        leave_result(deck);
    }
    if (deck->sweeping && since(now_ms, deck->sweep_started_ms) >= HELM_SWEEP_MS) {
        deck->sweeping = false;
    }
}

/* Inputs from the controls */

/* Any touch marks new items seen, once per model. */
static void touch(helm_deck_t *deck)
{
    const helm_model_t *m = helm_deck_model(deck);
    if (m != NULL && m->unseen > 0 && !(deck->seen_sent && deck->seen_sent_for == m->seq)) {
        deck->seen_sent = true;
        deck->seen_sent_for = m->seq;
        emit_simple(deck, HELM_EVENT_SEEN);
    }
}

/* Move within the view; turning up from the first row goes back to Home. */
static void move_selection(helm_deck_t *deck, int32_t delta)
{
    int count = helm_deck_view_count(deck);
    if (count == 0) {
        return;
    }
    int pos = helm_deck_view_pos(deck, deck->selected);
    pos = pos < 0 ? 0 : pos;
    if (pos == 0 && delta < 0) {
        deck->screen = HELM_SCREEN_HOME;
        return;
    }
    int64_t i = (int64_t)pos + delta;
    if (i < 0) {
        i = 0;
    }
    if (i > count - 1) {
        i = count - 1;
    }
    select_index(deck, helm_deck_view_item(deck, (int)i));
}

/* Turn through the project views and select the first item in the new one. */
static void turn_views(helm_deck_t *deck, int32_t delta)
{
    const helm_model_t *m = helm_deck_model(deck);
    int64_t steps = delta < 0 ? -(int64_t)delta : delta;
    steps %= count_views(m);
    for (int64_t n = 0; n < steps; n++) {
        step_view(deck, delta > 0 ? 1 : -1);
    }
    int first = helm_deck_view_item(deck, 0);
    if (first < 0) {
        deck->selected = -1;
    } else {
        select_index(deck, first);
    }
}

void helm_deck_knob(helm_deck_t *deck, int32_t delta, uint32_t now_ms)
{
    (void)now_ms;
    if (delta == 0) {
        return;
    }
    touch(deck);
    helm_event_t event;
    memset(&event, 0, sizeof event);
    event.type = HELM_EVENT_KNOB;
    event.u.knob.delta = delta;
    emit(deck, &event);
    if (deck->holding) {
        return;
    }
    switch (deck->screen) {
    case HELM_SCREEN_RESULT:
        leave_result(deck);
        break;
    case HELM_SCREEN_HOME:
        if (helm_deck_has_views(deck)) {
            turn_views(deck, delta);
        } else if (helm_deck_view_count(deck) > 0) {
            deck->screen = HELM_SCREEN_LIST;
        }
        break;
    case HELM_SCREEN_LIST:
        move_selection(deck, delta);
        break;
    case HELM_SCREEN_DETAIL: {
        int64_t scroll = (int64_t)deck->detail_scroll + delta;
        deck->detail_scroll = scroll < 0 ? 0 : (scroll > INT32_MAX ? INT32_MAX : (int32_t)scroll);
        break;
    }
    case HELM_SCREEN_CONFIRM:
        break;
    }
}

void helm_deck_knob_press(helm_deck_t *deck, bool long_press, uint32_t now_ms)
{
    (void)now_ms;
    touch(deck);
    helm_event_t event;
    memset(&event, 0, sizeof event);
    event.type = HELM_EVENT_KNOB_PRESS;
    event.u.knob_press.long_press = long_press;
    emit(deck, &event);
    if (long_press) {
        deck->muted = !deck->muted;
        return;
    }
    if (deck->holding) {
        return;
    }
    switch (deck->screen) {
    case HELM_SCREEN_HOME:
        if (helm_deck_view_count(deck) > 0) {
            deck->screen = HELM_SCREEN_LIST;
        }
        break;
    case HELM_SCREEN_LIST:
        if (helm_deck_selected(deck) != NULL) {
            deck->screen = HELM_SCREEN_DETAIL;
            deck->detail_scroll = 0;
        }
        break;
    case HELM_SCREEN_DETAIL:
        deck->screen = HELM_SCREEN_LIST;
        break;
    case HELM_SCREEN_RESULT:
        leave_result(deck);
        break;
    case HELM_SCREEN_CONFIRM:
        break;
    }
}

void helm_deck_key_down(helm_deck_t *deck, helm_action_t key, uint32_t now_ms)
{
    touch(deck);
    if (deck->holding || !helm_deck_key_lit(deck, key, now_ms)) {
        return;
    }
    emit_key(deck, key, HELM_KEY_DOWN);
    if (key != HELM_ACTION_FOCUS) {
        deck->holding = true;
        deck->hold_key = key;
        deck->hold_started_ms = now_ms;
        deck->hold_return = deck->screen;
        deck->screen = HELM_SCREEN_CONFIRM;
    }
}

void helm_deck_key_up(helm_deck_t *deck, helm_action_t key, uint32_t now_ms)
{
    if (key == HELM_ACTION_FOCUS) {
        /* SHOW ME is a tap. */
        if (!deck->holding && helm_deck_key_lit(deck, HELM_ACTION_FOCUS, now_ms)) {
            emit_key(deck, HELM_ACTION_FOCUS, HELM_KEY_UP);
        }
        return;
    }
    if (!deck->holding || deck->hold_key != key) {
        return;
    }
    /* Released before the fill bar completed: nothing is sent but the up. */
    deck->holding = false;
    deck->screen = deck->hold_return;
    emit_key(deck, key, HELM_KEY_UP);
}

void helm_deck_init(helm_deck_t *deck, const helm_deck_config_t *cfg)
{
    memset(deck, 0, sizeof *deck);
    if (cfg != NULL) {
        deck->cfg = *cfg;
    }
    helm_decoder_init(&deck->decoder);
    deck->screen = HELM_SCREEN_HOME;
    deck->selected = -1;
    deck->last_parse_error = HELM_PARSE_OK;
}
