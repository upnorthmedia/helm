#include "ui.h"

#include <stdio.h>
#include <string.h>

#include "helm_lights.h"
#include "lvgl.h"
#include "sdkconfig.h"

/* The LCD-5's 720 x 1280 panel turned landscape (main.c turns it). */
#define SCREEN_W 1280
#define SCREEN_H 720

#if CONFIG_HELM_TOUCH_KEYS
#define TOUCH_KEYS 1
#define KEYBAR_Y 628 /* the on-screen keys take the bottom 92 px */
#else
#define TOUCH_KEYS 0
#define KEYBAR_Y SCREEN_H
#endif

/* Touch gestures */
#define DRAG_START_PX 12   /* movement before a press counts as a swipe */
#define KNOB_STEP_PX 48    /* swipe distance per knob step */
#define LONG_PRESS_MS 800  /* long press = the knob's long press (mute) */

#define VIEW_LABEL_W 260 /* the project view's label in the status strip */

/* Layout, from sim/render.py */
#define COLUMN_X0 740 /* Home's right column: the view's items */
#define COLUMN_X1 (SCREEN_W - 40)
#define COLUMN_ROWS 5
#define COLUMN_TOP 132
#define COLUMN_ROW_H 84
#define COLUMN_PITCH 90
#define LIST_ROWS_MAX 6
#define LIST_TOP 132
#define LIST_ROW_H 80
#define LIST_PITCH 86 /* row plus gap */

/* Colors, from sim/render.py COLORS */
#define C_SCREEN 0x0f1115
#define C_PANEL 0x1a1d23
#define C_PANEL_HI 0x262a32
#define C_TEXT 0xebe8e3
#define C_DIM 0x8b919b
#define C_FAINT 0x4a4f58
#define C_OFF 0x2a2d33
#define C_RED 0xef4b4b
#define C_AMBER 0xf0a92e
#define C_BLUE 0x4c9ef5
#define C_GREEN 0x43c26b
#define C_WHITE 0xe9edf2

static const char *const KEY_LABELS[HELM_ACTION_COUNT] = {"YES", "LATER", "HOLD", "SHOW ME"};
static const uint32_t KEY_COLORS[HELM_ACTION_COUNT] = {C_GREEN, C_BLUE, C_AMBER, C_WHITE};

typedef enum { A_NW, A_N, A_NE, A_W, A_CENTER, A_E } anchor_t;

/* What the content shows; it is rebuilt only when this changes. */
typedef struct {
    helm_screen_t screen;
    bool has_model;
    uint32_t model_ms; /* changes with every model received */
    int selected;
    int32_t detail_scroll;
    helm_link_state_t link;
    helm_attention_t attention;
    bool muted;
    bool holding;
    helm_action_t hold_key;
    bool pending_has_result;
    helm_result_state_t pending_state;
    bool waited; /* the result screen has waited 10 s with no answer */
    char view[HELM_VIEW_BYTES];
} signature_t;

static ui_post_fn s_post;
static lv_obj_t *s_content; /* everything above the keys; also the touch surface */
static lv_obj_t *s_fill;    /* the confirm fill bar, while on the confirm screen */
static bool s_built;
static signature_t s_sig;

/* Written by ui_render, read by the touch handlers; both run under the display lock. */
static bool s_on_list;
static int s_list_items[LIST_ROWS_MAX]; /* the item index on each row shown */
static int s_list_shown;
static bool s_on_result;
static uint32_t s_result_since;

static struct {
    bool active; /* the press started on the content (LVGL sends no PRESSED to a
                  * finger dragged in from a key, only PRESSING and the rest) */
    int32_t press_y;
    int32_t step_y;
    bool dragged;
    bool tap; /* set on release: the press was a tap on the content (LVGL sends
               * RELEASED before SHORT_CLICKED) */
} s_touch;

/* Drawing helpers */

/* lv_obj_set_clickable and friends arrived in LVGL 9.6; the board package pins 9.5. */
static void set_flag(lv_obj_t *o, lv_obj_flag_t flag, bool on)
{
    if (on) {
        lv_obj_add_flag(o, flag);
    } else {
        lv_obj_remove_flag(o, flag);
    }
}

/* The nearest built-in Montserrat size (enabled in sdkconfig.defaults). The
 * simulator's Menlo sizes above 48 use 48. */
static const lv_font_t *font(int px)
{
    if (px <= 14) return &lv_font_montserrat_14;
    if (px <= 18) return &lv_font_montserrat_18;
    if (px <= 20) return &lv_font_montserrat_20;
    if (px <= 22) return &lv_font_montserrat_22;
    if (px <= 24) return &lv_font_montserrat_24;
    if (px <= 26) return &lv_font_montserrat_26;
    if (px <= 28) return &lv_font_montserrat_28;
    if (px <= 30) return &lv_font_montserrat_30;
    if (px <= 32) return &lv_font_montserrat_32;
    if (px <= 34) return &lv_font_montserrat_34;
    if (px <= 40) return &lv_font_montserrat_40;
    return &lv_font_montserrat_48;
}

static lv_obj_t *rect(lv_obj_t *parent, int32_t x0, int32_t y0, int32_t x1, int32_t y1, uint32_t fill)
{
    lv_obj_t *o = lv_obj_create(parent);
    lv_obj_remove_style_all(o);
    set_flag(o, LV_OBJ_FLAG_CLICKABLE, false);
    set_flag(o, LV_OBJ_FLAG_SCROLLABLE, false);
    lv_obj_set_pos(o, x0, y0);
    lv_obj_set_size(o, x1 - x0, y1 - y0);
    lv_obj_set_style_bg_color(o, lv_color_hex(fill), 0);
    lv_obj_set_style_bg_opa(o, LV_OPA_COVER, 0);
    return o;
}

static void outline(lv_obj_t *o, uint32_t color, int32_t width)
{
    lv_obj_set_style_border_color(o, lv_color_hex(color), 0);
    lv_obj_set_style_border_width(o, width, 0);
    lv_obj_set_style_border_opa(o, LV_OPA_COVER, 0);
}

static lv_obj_t *oval(lv_obj_t *parent, int32_t x0, int32_t y0, int32_t x1, int32_t y1, uint32_t fill)
{
    lv_obj_t *o = rect(parent, x0, y0, x1, y1, fill);
    lv_obj_set_style_radius(o, LV_RADIUS_CIRCLE, 0);
    return o;
}

/*
 * One line of text at (x, y) with a tk-style anchor, as sim/render.py places
 * it. A width > 0 cuts the text with "..." to fit, as render.clip does, and
 * is required for the centered and right anchors.
 */
static lv_obj_t *text(lv_obj_t *parent, int32_t x, int32_t y, int32_t w, const char *s, uint32_t color, int size,
                      anchor_t anchor)
{
    const lv_font_t *f = font(size);
    int32_t h = lv_font_get_line_height(f);
    lv_obj_t *l = lv_label_create(parent);
    lv_obj_set_style_text_font(l, f, 0);
    lv_obj_set_style_text_color(l, lv_color_hex(color), 0);
    if (w > 0) {
        lv_label_set_long_mode(l, LV_LABEL_LONG_MODE_DOTS);
        lv_obj_set_size(l, w, h);
    }
    lv_label_set_text(l, s);
    int32_t left = x;
    lv_text_align_t align = LV_TEXT_ALIGN_LEFT;
    if (anchor == A_N || anchor == A_CENTER) {
        left = x - w / 2;
        align = LV_TEXT_ALIGN_CENTER;
    } else if (anchor == A_NE || anchor == A_E) {
        left = x - w;
        align = LV_TEXT_ALIGN_RIGHT;
    }
    int32_t top = (anchor == A_W || anchor == A_CENTER || anchor == A_E) ? y - h / 2 : y;
    lv_obj_set_style_text_align(l, align, 0);
    lv_obj_set_pos(l, left, top);
    return l;
}

/* Wrapped text in a clipped box, `line_h` px per line. Returns the label. */
static lv_obj_t *paragraph(lv_obj_t *parent, int32_t x, int32_t y, int32_t w, int32_t h, const char *s, uint32_t color,
                           int size, int32_t line_h)
{
    lv_obj_t *box = lv_obj_create(parent);
    lv_obj_remove_style_all(box);
    set_flag(box, LV_OBJ_FLAG_CLICKABLE, false);
    set_flag(box, LV_OBJ_FLAG_SCROLLABLE, false);
    lv_obj_set_pos(box, x, y);
    lv_obj_set_size(box, w, h);
    const lv_font_t *f = font(size);
    lv_obj_t *l = lv_label_create(box);
    lv_obj_set_style_text_font(l, f, 0);
    lv_obj_set_style_text_color(l, lv_color_hex(color), 0);
    lv_obj_set_style_text_line_space(l, line_h - lv_font_get_line_height(f), 0);
    lv_label_set_long_mode(l, LV_LABEL_LONG_MODE_WRAP);
    lv_obj_set_width(l, w);
    lv_label_set_text(l, s);
    return l;
}

static int32_t paragraph_lines(lv_obj_t *label, int32_t line_h)
{
    lv_obj_update_layout(label);
    int32_t space = lv_obj_get_style_text_line_space(label, 0);
    int32_t lines = (lv_obj_get_height(label) + space) / line_h;
    return lines < 1 ? 1 : lines;
}

static void chip(lv_obj_t *parent, int32_t x, int32_t y, uint32_t color, int32_t size)
{
    rect(parent, x, y, x + size, y + size, color);
}

/* Model helpers */

static uint32_t item_color(helm_color_t c)
{
    switch (c) {
    case HELM_COLOR_RED:
        return C_RED;
    case HELM_COLOR_AMBER:
        return C_AMBER;
    case HELM_COLOR_BLUE:
        return C_BLUE;
    case HELM_COLOR_GREEN:
        return C_GREEN;
    }
    return C_TEXT;
}

/* An item's color on its list row: its kind's color, tinted by its project
 * like its light on the bar (helm_lights.h states the rule). */
static uint32_t item_light(const helm_model_t *m, const helm_item_t *item)
{
    uint32_t c = item_color(item->color);
    helm_rgb_t rgb = {(uint8_t)(c >> 16), (uint8_t)(c >> 8), (uint8_t)c};
    rgb = helm_lights_tint(rgb, helm_lights_project_tint(helm_model_str(m, item->project)));
    return ((uint32_t)rgb.r << 16) | ((uint32_t)rgb.g << 8) | rgb.b;
}

static const char *kind_label(helm_item_kind_t k)
{
    switch (k) {
    case HELM_KIND_DECISION:
        return "decision";
    case HELM_KIND_PR_READY:
        return "PR ready";
    case HELM_KIND_WORKER_PROBLEM:
        return "worker problem";
    case HELM_KIND_HERDR_BLOCKED:
        return "herdr blocked";
    }
    return "";
}

static void age(char *out, size_t cap, int32_t s)
{
    if (s < 60) {
        snprintf(out, cap, "%lds", (long)s);
    } else if (s < 3600) {
        snprintf(out, cap, "%ldm", (long)(s / 60));
    } else if (s < 86400) {
        snprintf(out, cap, "%ldh", (long)(s / 3600));
    } else {
        snprintf(out, cap, "%ldd", (long)(s / 86400));
    }
}

static const char *str(const helm_model_t *m, helm_str_t s)
{
    const char *v = helm_model_str(m, s);
    return v != NULL ? v : "";
}

/* "YES sent" while the item's answer waits on firstmate's reply, as render.answer_tag; false when none. */
static bool answer_tag(char *out, size_t cap, const helm_item_t *item)
{
    if (!item->has_pending) {
        return false;
    }
    snprintf(out, cap, "%s sent", KEY_LABELS[item->pending]);
    return true;
}

/* The width the simulator gives a run of Menlo text (CHAR_W = 0.602 em), so cuts land in the same places. */
static int32_t menlo_width(const char *s, int size)
{
    return (int32_t)strlen(s) * size * 602 / 1000;
}

/* One usage window: "5h 62% for 1h", "5h 62%", or "5h ?". */
static void usage_part(char *out, size_t cap, const char *name, helm_opt_int_t left, helm_opt_int_t resets)
{
    if (!left.known) {
        snprintf(out, cap, "%s ?", name);
        return;
    }
    char when[16] = "";
    if (resets.known) {
        age(when, sizeof when, resets.value);
    }
    snprintf(out, cap, "%s %ld%%%s%s", name, (long)left.value, resets.known ? " for " : "", when);
}

/* The usage gauge as one line, as sim/render.py usage_line writes it. */
static void usage_line(char *out, size_t cap, const helm_usage_t *u)
{
    if (!u->five_hour_left.known && !u->week_left.known) {
        snprintf(out, cap, "Claude usage unknown");
        return;
    }
    char five[64], week[64];
    usage_part(five, sizeof five, "5h", u->five_hour_left, u->five_hour_resets_s);
    usage_part(week, sizeof week, "week", u->week_left, u->week_resets_s);
    snprintf(out, cap, "Claude left  %s  %s", five, week);
}

/* The context gauge as one line, as sim/render.py context_line writes it. */
static void context_line(char *out, size_t cap, const helm_model_t *m)
{
    const helm_context_t *x = &m->context;
    if (!x->top_used.known) {
        snprintf(out, cap, "Agent context unknown");
        return;
    }
    const char *agent = x->top_agent != HELM_STR_NULL ? str(m, x->top_agent) : "?";
    int n = snprintf(out, cap, "Context  %s %ld%% used", agent, (long)x->top_used.value);
    if (x->near_limit.known && x->near_limit.value > 0 && n >= 0 && (size_t)n < cap) {
        snprintf(out + n, cap - (size_t)n, "  %ld near limit", (long)x->near_limit.value);
    }
}

/* Screens, after sim/render.py */

static void status_strip(lv_obj_t *p, const helm_deck_t *deck, uint32_t now)
{
    rect(p, 0, 0, SCREEN_W, 60, C_PANEL);
    const helm_model_t *m = helm_deck_model(deck);
    const char *reason = NULL;
    switch (helm_deck_link_state(deck, now)) {
    case HELM_LINK_OK:
        break;
    case HELM_LINK_WAITING:
        reason = "waiting for the bridge";
        break;
    case HELM_LINK_SILENT:
        reason = "no word from the bridge for 10 s";
        break;
    case HELM_LINK_BRIDGE_PROBLEM:
        reason = m->link.stale_reason != HELM_STR_NULL ? str(m, m->link.stale_reason) : "the bridge reports a problem";
        break;
    case HELM_LINK_FIRSTMATE_NOT_LISTENING:
        reason = m->link.stale_reason != HELM_STR_NULL ? str(m, m->link.stale_reason) : "firstmate is not listening";
        break;
    }
    char buf[192];
    /* Right side, from the edge in: MUTED, then the project view when there is more than one. */
    int32_t right = SCREEN_W - 22, left_w = 900;
    if (deck->muted) {
        text(p, right, 30, 140, "MUTED", C_DIM, 22, A_E);
        right -= 96;
    }
    if (helm_deck_has_views(deck)) {
        const char *view = helm_deck_view(deck);
        snprintf(buf, sizeof buf, "view: %s", view != NULL ? view : "all");
        text(p, right, 30, VIEW_LABEL_W, buf, C_TEXT, 22, A_E);
        left_w = right - VIEW_LABEL_W - 64;
    }
    if (reason != NULL) {
        oval(p, 22, 21, 40, 39, C_AMBER);
        text(p, 52, 30, left_w, reason, C_AMBER, 22, A_W);
    } else if (m->link.mac_locked) {
        /* Not a fault either: every key is dark until the Mac is unlocked. */
        oval(p, 22, 21, 40, 39, C_BLUE);
        text(p, 52, 30, left_w, "Mac locked: keys locked", C_TEXT, 22, A_W);
    } else if (m->link.away) {
        /* Follow away mode: not a fault, so blue rather than amber, and it says what it means. */
        const char *posture = m->link.posture != HELM_STR_NULL ? str(m, m->link.posture) : "away";
        snprintf(buf, sizeof buf, "firstmate %s: keys locked", posture);
        oval(p, 22, 21, 40, 39, C_BLUE);
        text(p, 52, 30, left_w, buf, C_TEXT, 22, A_W);
    } else {
        const char *posture = m->link.posture != HELM_STR_NULL ? str(m, m->link.posture) : "listening";
        snprintf(buf, sizeof buf, "firstmate %s", posture);
        oval(p, 22, 21, 40, 39, C_GREEN);
        text(p, 52, 30, left_w, buf, C_TEXT, 22, A_W);
    }
}

/* One item as a row, as sim/render.py _item_row: tinted strip, short id, kind
 * and project (and the answer sent), NEW, age. Home's column uses the small size (id_size < 34). */
static void item_row(lv_obj_t *p, const helm_model_t *m, const helm_item_t *item, int32_t x0, int32_t x1, int32_t y,
                     int32_t h, bool selected, int id_size)
{
    bool small = id_size < 34;
    int32_t badge_right = x1 - (small ? 110 : 130);
    /* Text runs up to the NEW badge, or to the age when there is none. */
    int32_t text_w = (item->unseen ? badge_right - 90 : x1 - 90) - (x0 + 36);
    char buf[192];
    lv_obj_t *row = rect(p, x0, y, x1, y + h, selected ? C_PANEL_HI : C_PANEL);
    if (selected) {
        outline(row, C_TEXT, 2);
    }
    rect(p, x0, y, x0 + 14, y + h, item_light(m, item));
    text(p, x0 + 36, y + 10, text_w, str(m, item->short_id), C_TEXT, id_size, A_NW);
    if (item->project != HELM_STR_NULL) {
        snprintf(buf, sizeof buf, "%s   %s", kind_label(item->kind), str(m, item->project));
    } else {
        snprintf(buf, sizeof buf, "%s", kind_label(item->kind));
    }
    int32_t kind_w = text_w;
    char tag[24];
    if (answer_tag(tag, sizeof tag, item)) {
        /* Right-aligned at the end of the text, in its key's color; the kind line gives way. */
        int32_t tag_w = menlo_width(tag, 20);
        text(p, x0 + 36 + text_w, y + h - 30, tag_w + 20, tag, KEY_COLORS[item->pending], 20, A_NE);
        kind_w = text_w - tag_w - 20;
    }
    text(p, x0 + 36, y + h - 30, kind_w, buf, C_DIM, 20, A_NW);
    age(buf, sizeof buf, item->age_s);
    text(p, x1 - 24, y + h / 2, 100, buf, C_DIM, small ? 24 : 28, A_E);
    if (item->unseen) {
        rect(p, badge_right - 80, y + h / 2 - 16, badge_right, y + h / 2 + 16, item_color(item->color));
        text(p, badge_right - 40, y + h / 2, 80, "NEW", C_SCREEN, 20, A_CENTER);
    }
}

/* "Needs you (3)" or "Needs you in widget-api (2)". */
static void needs_you(char *out, size_t cap, const helm_deck_t *deck)
{
    const char *view = helm_deck_view(deck);
    int count = helm_deck_view_count(deck);
    if (view != NULL) {
        snprintf(out, cap, "Needs you in %s (%d)", view, count);
    } else {
        snprintf(out, cap, "Needs you (%d)", count);
    }
}

static void home(lv_obj_t *p, const helm_deck_t *deck, uint32_t now)
{
    helm_attention_t attention = helm_deck_attention(deck, now);
    const helm_model_t *m = helm_deck_model(deck);
    char buf[192];
    /* Left column: the headline, the gauges, the counts. */
    if (attention == HELM_ATTENTION_UNKNOWN) {
        text(p, 40, 100, 0, "Link unknown", C_AMBER, 56, A_NW);
        text(p, 40, 175, 0, "No green until the link is back.", C_DIM, 24, A_NW);
    } else if (attention == HELM_ATTENTION_NEW && m != NULL) {
        snprintf(buf, sizeof buf, "%ld new for you", (long)m->unseen);
        text(p, 40, 100, 0, buf, C_TEXT, 56, A_NW);
    } else {
        text(p, 40, 100, 0, "All quiet", C_TEXT, 56, A_NW);
    }
    if (m == NULL) {
        return;
    }
    if (attention != HELM_ATTENTION_UNKNOWN) {
        usage_line(buf, sizeof buf, &m->usage);
        text(p, 40, 168, COLUMN_X0 - 80, buf, C_DIM, 22, A_NW);
        bool near = m->context.near_limit.known && m->context.near_limit.value > 0;
        context_line(buf, sizeof buf, m);
        text(p, 40, 195, COLUMN_X0 - 80, buf, near ? C_AMBER : C_DIM, 22, A_NW);
    }
    const struct {
        const char *label;
        int32_t value;
        uint32_t color;
    } tiles[4] = {
        {"decisions", m->counts.decisions, C_RED},
        {"working", m->counts.working, C_TEXT},
        {"PRs ready", m->counts.prs_ready, C_BLUE},
        {"landed today", m->counts.landed_today, C_GREEN},
    };
    for (int n = 0; n < 4; n++) {
        int32_t x = 40 + (n % 2) * 330;
        int32_t y = 240 + (n / 2) * 150;
        rect(p, x, y, x + 310, y + 130, C_PANEL);
        /* Fail visible: nothing green while the link is unknown. */
        bool dim = tiles[n].value == 0 || (attention == HELM_ATTENTION_UNKNOWN && tiles[n].color == C_GREEN);
        snprintf(buf, sizeof buf, "%ld", (long)tiles[n].value);
        text(p, x + 24, y + 14, 0, buf, dim ? C_DIM : tiles[n].color, 60, A_NW);
        text(p, x + 24, y + 92, 0, tiles[n].label, C_DIM, 22, A_NW);
    }
    snprintf(buf, sizeof buf, "herdr   %ld working   %ld blocked", (long)m->counts.herdr_working,
             (long)m->counts.herdr_blocked);
    text(p, 40, 548, 0, buf, C_TEXT, 26, A_NW);
    snprintf(buf, sizeof buf, "queued  %ld", (long)m->counts.queued);
    text(p, 40, 590, 0, buf, C_DIM, 22, A_NW);

    /* Right column: what needs you in this view, the selection outlined. */
    int count = helm_deck_view_count(deck);
    needs_you(buf, sizeof buf, deck);
    text(p, COLUMN_X0, 84, COLUMN_X1 - COLUMN_X0 - (count > COLUMN_ROWS ? 110 : 0), buf, C_TEXT, 28, A_NW);
    if (count == 0) {
        text(p, COLUMN_X0, 140, 0, "Nothing needs you", C_DIM, 24, A_NW);
        return;
    }
    int sel = helm_deck_view_pos(deck, deck->selected);
    sel = sel < 0 ? 0 : sel;
    int first = helm_deck_list_first(deck, COLUMN_ROWS);
    for (int n = 0; n < COLUMN_ROWS && first + n < count; n++) {
        const helm_item_t *item = &m->items[helm_deck_view_item(deck, first + n)];
        item_row(p, m, item, COLUMN_X0, COLUMN_X1, COLUMN_TOP + n * COLUMN_PITCH, COLUMN_ROW_H, first + n == sel, 30);
    }
    if (count > COLUMN_ROWS) {
        snprintf(buf, sizeof buf, "%d/%d", sel + 1, count);
        text(p, COLUMN_X1, 90, 110, buf, C_DIM, 22, A_NE);
    }
#if TOUCH_KEYS
    const char *hint = helm_deck_has_views(deck) ? "tap for list" : "swipe for list";
#else
    const char *hint = helm_deck_has_views(deck) ? "press for list" : "turn for list";
#endif
    text(p, COLUMN_X0, 610, 0, hint, C_FAINT, 20, A_W);
}

static void list(lv_obj_t *p, const helm_deck_t *deck)
{
    const helm_model_t *m = helm_deck_model(deck);
    int count = helm_deck_view_count(deck);
    char buf[192];
    const int rows = TOUCH_KEYS ? 5 : LIST_ROWS_MAX;
    needs_you(buf, sizeof buf, deck);
    text(p, 40, 80, SCREEN_W - 80 - (count > rows ? 160 : 0), buf, C_TEXT, 32, A_NW);
    int sel = helm_deck_view_pos(deck, deck->selected);
    sel = sel < 0 ? 0 : sel;
    int first = helm_deck_list_first(deck, rows);
    int shown = 0;
    for (int n = 0; n < rows && first + n < count; n++, shown++) {
        int index = helm_deck_view_item(deck, first + n);
        s_list_items[n] = index;
        item_row(p, m, &m->items[index], 24, SCREEN_W - 24, LIST_TOP + n * LIST_PITCH, LIST_ROW_H, first + n == sel, 34);
    }
    if (count > rows) {
        snprintf(buf, sizeof buf, "%d/%d", sel + 1, count);
        text(p, SCREEN_W - 40, 92, 160, buf, C_DIM, 22, A_NE);
    }
#if !TOUCH_KEYS
    text(p, 40, 690, 0, "turn: move   press: full text   hold a key to act", C_FAINT, 20, A_W);
#endif
    s_on_list = true;
    s_list_shown = shown;
}

static void detail(lv_obj_t *p, helm_deck_t *deck)
{
    const helm_model_t *m = helm_deck_model(deck);
    const helm_item_t *item = helm_deck_selected(deck);
    if (item == NULL) {
        return;
    }
    char buf[320];
    chip(p, 40, 84, item_color(item->color), 30);
    text(p, 86, 99, 820, str(m, item->short_id), C_TEXT, 34, A_W);
    text(p, SCREEN_W - 40, 99, 240, kind_label(item->kind), C_DIM, 22, A_E);
    char when[16];
    age(when, sizeof when, item->age_s);
    const char *checks = helm_checks_name(item->checks);
    char project[160] = "";
    if (item->project != HELM_STR_NULL) {
        snprintf(project, sizeof project, "   project %s", str(m, item->project));
    }
    if (checks != NULL) {
        snprintf(buf, sizeof buf, "home %s%s   age %s   checks %s", str(m, item->home), project, when, checks);
    } else {
        snprintf(buf, sizeof buf, "home %s%s   age %s", str(m, item->home), project, when);
    }
    int32_t meta_w = SCREEN_W - 80;
    char tag[24];
    if (answer_tag(tag, sizeof tag, item)) {
        int32_t tag_w = menlo_width(tag, 22);
        text(p, SCREEN_W - 40, 136, tag_w + 30, tag, KEY_COLORS[item->pending], 22, A_NE);
        meta_w -= tag_w + 30;
    }
    text(p, 40, 136, meta_w, buf, C_DIM, 22, A_NW);

    const int32_t line_h = 38, top = 186, bottom = TOUCH_KEYS ? 580 : 620;
    lv_obj_t *body = paragraph(p, 40, top, SCREEN_W - 80, bottom - top, str(m, item->detail), C_TEXT, 26, line_h);
    int32_t total = paragraph_lines(body, line_h);
    int32_t visible = (bottom - top) / line_h;
    helm_deck_clamp_detail_scroll(deck, total, visible);
    lv_obj_set_y(body, -deck->detail_scroll * line_h);
    if (total > visible) {
        int32_t track = bottom - top;
        int32_t thumb = track * visible / total;
        thumb = thumb < 30 ? 30 : thumb;
        int32_t span = total - visible;
        int32_t y = top + (track - thumb) * deck->detail_scroll / (span > 0 ? span : 1);
        rect(p, SCREEN_W - 20, top, SCREEN_W - 14, bottom, C_PANEL);
        rect(p, SCREEN_W - 20, y, SCREEN_W - 14, y + thumb, C_DIM);
    }
    const char *footer = item->pr_url != HELM_STR_NULL ? str(m, item->pr_url)
                                                         : (TOUCH_KEYS ? "swipe: scroll   tap: back" : "turn: scroll   press: back");
    text(p, 40, TOUCH_KEYS ? 604 : 680, SCREEN_W - 80, footer, C_FAINT, 20, A_W);
}

/* The Confirm fill bar's track, as sim/render.py _confirm. */
#define CONFIRM_X0 240
#define CONFIRM_X1 (SCREEN_W - 240)

static void confirm(lv_obj_t *p, const helm_deck_t *deck)
{
    const helm_model_t *m = helm_deck_model(deck);
    const helm_item_t *item = helm_deck_selected(deck);
    if (!deck->holding || item == NULL) {
        return;
    }
    uint32_t color = KEY_COLORS[deck->hold_key];
    const int32_t mid = SCREEN_W / 2;
    char buf[160];
    text(p, mid, 110, 600, "Hold to confirm", C_DIM, 30, A_N);

    /* The simulator sets this at 110 px; the largest built-in font is 48, so
     * scale it up around its center. */
    lv_obj_t *big = lv_label_create(p);
    lv_obj_set_style_text_font(big, font(48), 0);
    lv_obj_set_style_text_color(big, lv_color_hex(color), 0);
    lv_label_set_text(big, KEY_LABELS[deck->hold_key]);
    lv_obj_update_layout(big);
    int32_t bw = lv_obj_get_width(big), bh = lv_obj_get_height(big);
    lv_obj_set_pos(big, mid - bw / 2, 250 - bh / 2);
    lv_obj_set_style_transform_pivot_x(big, bw / 2, 0);
    lv_obj_set_style_transform_pivot_y(big, bh / 2, 0);
    lv_obj_set_style_transform_scale(big, 256 * 110 / 48, 0);

    snprintf(buf, sizeof buf, "on %s", str(m, item->short_id));
    text(p, mid, 360, 1000, buf, C_TEXT, 40, A_CENTER);
    text(p, mid, 410, 600, kind_label(item->kind), C_DIM, 24, A_CENTER);
    lv_obj_t *track = rect(p, CONFIRM_X0, 480, CONFIRM_X1, 536, C_PANEL);
    outline(track, C_FAINT, 2);
    s_fill = rect(p, CONFIRM_X0 + 4, 484, CONFIRM_X0 + 5, 532, color);
    set_flag(s_fill, LV_OBJ_FLAG_HIDDEN, true);
    text(p, mid, 600, 600, "release to cancel", C_FAINT, 24, A_CENTER);
}

static void result(lv_obj_t *p, const helm_deck_t *deck, bool waited)
{
    if (!deck->pending) {
        return;
    }
    char buf[192];
    snprintf(buf, sizeof buf, "%s on %s", KEY_LABELS[deck->pending_key], deck->pending_short_id);
    text(p, 40, 90, SCREEN_W - 80, buf, C_TEXT, 34, A_NW);
    const char *label;
    const char *body;
    uint32_t color;
    if (!deck->pending_has_result) {
        label = waited ? "No answer yet" : "Sending";
        color = waited ? C_AMBER : C_DIM;
        body = waited ? "The bridge has not answered. Nothing is known to have happened."
                      : "Waiting for the bridge to confirm.";
    } else {
        body = deck->pending_text;
        switch (deck->pending_state) {
        case HELM_RESULT_QUEUED:
            label = deck->pending_seen ? "Seen" : "Queued";
            color = !deck->pending_seen && deck->pending_stalled ? C_AMBER : C_BLUE;
            break;
        case HELM_RESULT_REPLIED:
            label = "Replied";
            color = C_GREEN;
            break;
        default:
            label = "Failed";
            color = C_RED;
            break;
        }
    }
    rect(p, 40, 160, 300, 220, color);
    text(p, 170, 190, 250, label, C_SCREEN, 30, A_CENTER);
    /* A queued note's progress, as render.result_progress. */
    if (deck->pending_has_result && deck->pending_state == HELM_RESULT_QUEUED && deck->pending_waited_s.known) {
        char sent[16];
        age(sent, sizeof sent, deck->pending_waited_s.value);
        uint32_t line_color = C_DIM;
        if (deck->pending_seen) {
            snprintf(buf, sizeof buf, "sent %s ago, firstmate has read it", sent);
        } else if (deck->pending_stalled) {
            snprintf(buf, sizeof buf, "firstmate has not picked this up: sent %s ago", sent);
            line_color = C_AMBER;
        } else {
            snprintf(buf, sizeof buf, "sent %s ago, waiting for firstmate to read it", sent);
        }
        text(p, 330, 190, SCREEN_W - 370, buf, line_color, 26, A_W);
    }
    const int32_t line_h = 42, lines = TOUCH_KEYS ? 7 : 9;
    paragraph(p, 40, 260, SCREEN_W - 80, lines * line_h, body, C_TEXT, 28, line_h);
#if TOUCH_KEYS
    text(p, 40, 604, 0, "tap: home", C_FAINT, 20, A_W);
#else
    text(p, 40, 690, 0, "turn or press: home", C_FAINT, 20, A_W);
#endif
}

static void build(helm_deck_t *deck, uint32_t now, bool waited)
{
    lv_obj_clean(s_content);
    s_fill = NULL;
    s_on_list = false;
    status_strip(s_content, deck, now);
    switch (deck->screen) {
    case HELM_SCREEN_HOME:
        home(s_content, deck, now);
        break;
    case HELM_SCREEN_LIST:
        list(s_content, deck);
        break;
    case HELM_SCREEN_DETAIL:
        detail(s_content, deck);
        break;
    case HELM_SCREEN_CONFIRM:
        confirm(s_content, deck);
        break;
    case HELM_SCREEN_RESULT:
        result(s_content, deck, waited);
        break;
    }
}

static signature_t signature(const helm_deck_t *deck, uint32_t now, bool waited)
{
    signature_t s;
    memset(&s, 0, sizeof s); /* compared with memcmp, so clear the padding */
    s.screen = deck->screen;
    s.has_model = deck->has_model;
    s.model_ms = deck->last_model_ms;
    s.selected = deck->selected;
    s.detail_scroll = deck->detail_scroll;
    s.link = helm_deck_link_state(deck, now);
    s.attention = helm_deck_attention(deck, now);
    s.muted = deck->muted;
    s.holding = deck->holding;
    s.hold_key = deck->hold_key;
    s.pending_has_result = deck->pending_has_result;
    s.pending_state = deck->pending_state;
    s.waited = waited;
    memcpy(s.view, deck->view, sizeof s.view);
    return s;
}

/* On-screen keys */

#if TOUCH_KEYS
static struct {
    lv_obj_t *obj;
    lv_obj_t *label;
    lv_obj_t *hint;
    bool down; /* the finger is on it */
    int8_t shown; /* -1 unknown, else lit * 2 + down */
} s_keys[HELM_ACTION_COUNT];

static uint32_t mix(uint32_t color, float f, uint32_t base)
{
    uint32_t out = 0;
    for (int shift = 16; shift >= 0; shift -= 8) {
        float a = (float)((color >> shift) & 0xffu);
        float b = (float)((base >> shift) & 0xffu);
        out |= (uint32_t)(b + (a - b) * f + 0.5f) << shift;
    }
    return out;
}


static void update_key(int k, bool lit)
{
    int8_t shown = (int8_t)((lit ? 2 : 0) + (s_keys[k].down ? 1 : 0));
    if (shown == s_keys[k].shown) {
        return;
    }
    s_keys[k].shown = shown;
    uint32_t color = KEY_COLORS[k];
    uint32_t face = lit ? mix(color, s_keys[k].down ? 0.9f : 0.75f, C_OFF) : C_OFF;
    lv_obj_set_style_bg_color(s_keys[k].obj, lv_color_hex(face), 0);
    outline(s_keys[k].obj, lit ? color : C_FAINT, 2);
    uint32_t label = lit ? C_SCREEN : C_FAINT;
    lv_obj_set_style_text_color(s_keys[k].label, lv_color_hex(label), 0);
    lv_obj_set_style_text_color(s_keys[k].hint, lv_color_hex(label), 0);
}

static void post_key(int k, bool down)
{
    if (s_keys[k].down == down) {
        return; /* a lost press is followed by a release; send one up */
    }
    s_keys[k].down = down;
    ui_input_t in = {.type = UI_INPUT_KEY, .key = (helm_action_t)k, .down = down};
    s_post(&in);
}

static void key_event(lv_event_t *e)
{
    int k = (int)(intptr_t)lv_event_get_user_data(e);
    lv_event_code_t code = lv_event_get_code(e);
    if (code == LV_EVENT_PRESSED) {
        post_key(k, true);
    } else if (code == LV_EVENT_RELEASED) {
        post_key(k, false);
    } else if (code == LV_EVENT_PRESS_LOST) {
        /* The finger slid off. Letting go of YES, LATER, or HOLD cancels the
         * hold; SHOW ME acts on release, so it lets go without one. */
        if (k == HELM_ACTION_FOCUS) {
            s_keys[k].down = false;
        } else {
            post_key(k, false);
        }
    }
}

static void build_keys(lv_obj_t *screen)
{
    const int32_t margin = 16, gap = 12, top = KEYBAR_Y + 8, bottom = SCREEN_H - 10;
    const int32_t w = (SCREEN_W - 2 * margin - 3 * gap) / HELM_ACTION_COUNT;
    for (int k = 0; k < HELM_ACTION_COUNT; k++) {
        int32_t x = margin + k * (w + gap);
        lv_obj_t *o = lv_obj_create(screen);
        lv_obj_remove_style_all(o);
        set_flag(o, LV_OBJ_FLAG_SCROLLABLE, false);
        /* LVGL keeps an object pressed when the finger slides off it; a key
         * must let go instead, so sliding off cancels a hold (PRESS_LOST). */
        set_flag(o, LV_OBJ_FLAG_PRESS_LOCK, false);
        lv_obj_set_pos(o, x, top);
        lv_obj_set_size(o, w, bottom - top);
        lv_obj_set_style_bg_opa(o, LV_OPA_COVER, 0);
        lv_obj_add_event_cb(o, key_event, LV_EVENT_ALL, (void *)(intptr_t)k);
        s_keys[k].obj = o;
        s_keys[k].label = text(o, w / 2, (bottom - top) / 2 - 10, w - 8, KEY_LABELS[k], C_FAINT,
                               k == HELM_ACTION_FOCUS ? 18 : 20, A_CENTER);
        s_keys[k].hint = text(o, w / 2, (bottom - top) / 2 + 18, w - 8, k == HELM_ACTION_FOCUS ? "tap" : "hold 1s",
                              C_FAINT, 14, A_CENTER);
        s_keys[k].shown = -1;
        update_key(k, false);
    }
}

#endif /* TOUCH_KEYS */

/* Touch on the content: swipe = knob turn, tap = knob press, long press = mute */

static void post(ui_input_type_t type, int32_t delta, int row)
{
    ui_input_t in = {.type = type, .delta = delta, .row = row};
    s_post(&in);
}

static void content_event(lv_event_t *e)
{
    lv_event_code_t code = lv_event_get_code(e);
    lv_indev_t *indev = lv_indev_active();
    if (indev == NULL) {
        return;
    }
    lv_point_t pt;
    lv_indev_get_point(indev, &pt);
    switch (code) {
    case LV_EVENT_PRESSED:
        s_touch.active = true;
        s_touch.press_y = s_touch.step_y = pt.y;
        s_touch.dragged = false;
        s_touch.tap = false;
        return;
    case LV_EVENT_RELEASED:
        s_touch.tap = s_touch.active && !s_touch.dragged;
        s_touch.active = false;
        return;
    case LV_EVENT_PRESS_LOST:
        s_touch.active = false;
        s_touch.tap = false;
        return;
    default:
        break;
    }
    switch (code) {
    case LV_EVENT_PRESSING: {
        if (!s_touch.active) {
            break;
        }
        int32_t moved = pt.y - s_touch.press_y;
        if (!s_touch.dragged && (moved > DRAG_START_PX || moved < -DRAG_START_PX)) {
            s_touch.dragged = true;
        }
        if (s_touch.dragged) {
            /* Finger up moves down the list, like scrolling a page. */
            int32_t steps = (s_touch.step_y - pt.y) / KNOB_STEP_PX;
            if (steps != 0) {
                s_touch.step_y -= steps * KNOB_STEP_PX;
                post(UI_INPUT_KNOB, steps, 0);
            }
        }
        break;
    }
    case LV_EVENT_SHORT_CLICKED:
        if (!s_touch.tap) {
            break;
        }
        s_touch.tap = false;
        if (s_on_list && pt.y >= LIST_TOP) {
            int n = (pt.y - LIST_TOP) / LIST_PITCH;
            if (n < s_list_shown && (pt.y - LIST_TOP) % LIST_PITCH < LIST_ROW_H) {
                post(UI_INPUT_ROW, 0, s_list_items[n]);
            }
            break;
        }
        post(UI_INPUT_PRESS, 0, 0);
        break;
    case LV_EVENT_LONG_PRESSED:
        if (s_touch.active && !s_touch.dragged) {
            post(UI_INPUT_LONG, 0, 0);
        }
        break;
    default:
        break;
    }
}

void ui_init(ui_post_fn post_fn)
{
    s_post = post_fn;
    lv_obj_t *screen = lv_screen_active();
    set_flag(screen, LV_OBJ_FLAG_SCROLLABLE, false);
    lv_obj_set_style_bg_color(screen, lv_color_hex(C_SCREEN), 0);
    lv_obj_set_style_bg_opa(screen, LV_OPA_COVER, 0);

    s_content = lv_obj_create(screen);
    lv_obj_remove_style_all(s_content);
    set_flag(s_content, LV_OBJ_FLAG_SCROLLABLE, false);
    lv_obj_set_pos(s_content, 0, 0);
    lv_obj_set_size(s_content, SCREEN_W, KEYBAR_Y);
    lv_obj_add_event_cb(s_content, content_event, LV_EVENT_ALL, NULL);

    lv_indev_t *touch = lv_indev_get_next(NULL);
    if (touch != NULL) {
        lv_indev_set_long_press_time(touch, LONG_PRESS_MS);
    }
#if TOUCH_KEYS
    build_keys(screen);
#endif
}

void ui_render(helm_deck_t *deck, uint32_t now_ms)
{
    bool on_result = deck->screen == HELM_SCREEN_RESULT && deck->pending;
    if (on_result && !s_on_result) {
        s_result_since = now_ms;
    }
    s_on_result = on_result;
    bool waited = on_result && !deck->pending_has_result && now_ms - s_result_since >= 10000u;

    signature_t sig = signature(deck, now_ms, waited);
    if (!s_built || memcmp(&sig, &s_sig, sizeof sig) != 0) {
        build(deck, now_ms, waited);
        s_sig = signature(deck, now_ms, waited); /* build may clamp the detail scroll */
        s_built = true;
    }
    if (s_fill != NULL) {
        uint32_t permille = helm_deck_hold_progress_permille(deck, now_ms);
        int32_t full = CONFIRM_X1 - CONFIRM_X0 - 8;
        if (permille == 0) {
            set_flag(s_fill, LV_OBJ_FLAG_HIDDEN, true);
        } else {
            set_flag(s_fill, LV_OBJ_FLAG_HIDDEN, false);
            lv_obj_set_width(s_fill, (int32_t)((int64_t)full * permille / 1000));
        }
    }
#if TOUCH_KEYS
    for (int k = 0; k < HELM_ACTION_COUNT; k++) {
        update_key(k, helm_deck_key_lit(deck, (helm_action_t)k, now_ms));
    }
#endif
}
