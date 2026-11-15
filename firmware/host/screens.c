/*
 * The deck's screens on the host, for comparing with the simulator
 * (python -m sim.parity). Runs the device core (helm_deck) and the firmware's
 * own drawing code (firmware/idf/main/ui.c) under LVGL, into a 1280 x 720
 * RGB565 buffer in place of the panel.
 *
 * Reads one command per line on stdin; times are the deck's milliseconds:
 *
 *   model <ms> <frame-hex>          bytes from the bridge, a whole frame
 *   knob <ms> <delta>
 *   press <ms> <0|1>                a knob press; 1 is the long press
 *   key <ms> <yes|later|hold|focus> <down|up>
 *   tick <ms>
 *   render <ms> <out.ppm> <labels.json>
 *
 * render draws the screen ui.c shows at that time and writes it as a binary
 * PPM (RGB888, expanded from the panel's RGB565), and every visible LVGL
 * label as JSON: its text as drawn ("..." where it was cut), the label's box
 * on screen (x0, y0, x1, y1), and the part of it the text covers (ix0, iy0,
 * ix1, iy1), both after transforms and clipping, right and bottom edges
 * exclusive. Exits 0, or 2 on bad input.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "helm_deck.h"
#include "helm_jsonw.h"
#include "lvgl.h"
#include "ui.h"

#define SCREEN_W 1280
#define SCREEN_H 720
#define LINE_MAX_BYTES (4 * HELM_FRAME_MAX + 256)
#define LABELS_MAX_BYTES (1024 * 1024)

static uint16_t s_pixels[SCREEN_W * SCREEN_H];
static uint8_t s_frame[HELM_FRAME_MAX];
static char s_line[LINE_MAX_BYTES];
static uint8_t s_labels[LABELS_MAX_BYTES];
static uint32_t s_now;
static helm_deck_t s_deck;

static void die(const char *why)
{
    fprintf(stderr, "helm_screens: %s\n", why);
    exit(2);
}

static uint32_t tick_cb(void)
{
    return s_now;
}

static void flush_cb(lv_display_t *display, const lv_area_t *area, uint8_t *px)
{
    (void)area;
    (void)px;
    lv_display_flush_ready(display);
}

static void emit(void *ctx, const helm_event_t *event)
{
    (void)ctx;
    (void)event; /* nobody is listening */
}

static void post(const ui_input_t *input)
{
    (void)input; /* no touch here */
}

static int hex_nibble(char c)
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

static size_t from_hex(const char *hex, uint8_t *out, size_t cap)
{
    size_t n = strlen(hex);
    if (n % 2 != 0 || n / 2 > cap) {
        die("bad frame hex");
    }
    for (size_t i = 0; i < n / 2; i++) {
        int hi = hex_nibble(hex[2 * i]), lo = hex_nibble(hex[2 * i + 1]);
        if (hi < 0 || lo < 0) {
            die("bad frame hex");
        }
        out[i] = (uint8_t)((hi << 4) | lo);
    }
    return n / 2;
}

static uint32_t parse_ms(const char *s)
{
    char *end = NULL;
    unsigned long v = s != NULL ? strtoul(s, &end, 10) : 0;
    if (s == NULL || *s == '\0' || *end != '\0') {
        die("bad time");
    }
    return (uint32_t)v;
}

static helm_action_t parse_key(const char *s)
{
    static const char *const names[] = {"yes", "later", "hold", "focus"};
    for (int i = 0; i < HELM_ACTION_COUNT; i++) {
        if (s != NULL && strcmp(s, names[i]) == 0) {
            return (helm_action_t)i;
        }
    }
    die("bad key");
    return HELM_ACTION_YES;
}

static void write_ppm(const char *path)
{
    FILE *f = fopen(path, "wb");
    if (f == NULL) {
        die("cannot write the image");
    }
    static uint8_t rgb[3 * SCREEN_W * SCREEN_H];
    for (size_t i = 0; i < (size_t)SCREEN_W * SCREEN_H; i++) {
        uint16_t v = s_pixels[i];
        unsigned r = (v >> 11) & 0x1Fu, g = (v >> 5) & 0x3Fu, b = v & 0x1Fu;
        rgb[3 * i] = (uint8_t)((r << 3) | (r >> 2));
        rgb[3 * i + 1] = (uint8_t)((g << 2) | (g >> 4));
        rgb[3 * i + 2] = (uint8_t)((b << 3) | (b >> 2));
    }
    if (fprintf(f, "P6\n%d %d\n255\n", SCREEN_W, SCREEN_H) < 0 || fwrite(rgb, 1, sizeof rgb, f) != sizeof rgb) {
        die("cannot write the image");
    }
    if (fclose(f) != 0) {
        die("cannot write the image");
    }
}

static bool intersect(lv_area_t *a, const lv_area_t *b)
{
    a->x1 = a->x1 > b->x1 ? a->x1 : b->x1;
    a->y1 = a->y1 > b->y1 ? a->y1 : b->y1;
    a->x2 = a->x2 < b->x2 ? a->x2 : b->x2;
    a->y2 = a->y2 < b->y2 ? a->y2 : b->y2;
    return a->x1 <= a->x2 && a->y1 <= a->y2;
}

/* Every visible label under obj, clipped to its ancestors (LVGL clips children to their parent). */
/* The part of a label's box its text covers: as wide and tall as the text, placed by its alignment. */
static lv_area_t text_extent(lv_obj_t *label)
{
    lv_area_t box;
    lv_obj_get_content_coords(label, &box);
    lv_point_t size;
    lv_text_get_size(&size, lv_label_get_text(label), lv_obj_get_style_text_font(label, LV_PART_MAIN),
                     lv_obj_get_style_text_letter_space(label, LV_PART_MAIN),
                     lv_obj_get_style_text_line_space(label, LV_PART_MAIN), lv_area_get_width(&box), LV_TEXT_FLAG_NONE);
    int32_t w = size.x < lv_area_get_width(&box) ? size.x : lv_area_get_width(&box);
    int32_t h = size.y < lv_area_get_height(&box) ? size.y : lv_area_get_height(&box);
    lv_area_t ink = box;
    switch (lv_obj_get_style_text_align(label, LV_PART_MAIN)) {
    case LV_TEXT_ALIGN_CENTER:
        ink.x1 = box.x1 + (lv_area_get_width(&box) - w) / 2;
        break;
    case LV_TEXT_ALIGN_RIGHT:
        ink.x1 = box.x2 + 1 - w;
        break;
    default:
        break;
    }
    ink.x2 = ink.x1 + w - 1;
    ink.y2 = ink.y1 + h - 1;
    return ink;
}

static void put_area(helm_jsonw_t *w, const char *names[4], const lv_area_t *a)
{
    const int32_t v[4] = {a->x1, a->y1, a->x2 + 1, a->y2 + 1};
    for (int i = 0; i < 4; i++) {
        helm_jsonw_raw(w, names[i]);
        helm_jsonw_int(w, v[i]);
    }
}

static void walk_labels(lv_obj_t *obj, lv_area_t clip, helm_jsonw_t *w, bool *first)
{
    if (lv_obj_has_flag(obj, LV_OBJ_FLAG_HIDDEN)) {
        return;
    }
    /* The object's box, then through its own and its parents' transforms (the big YES on Confirm is
     * scaled up). The transform takes the box in and gives back exclusive right and bottom edges. */
    lv_area_t area;
    lv_obj_get_coords(obj, &area);
    lv_obj_get_transformed_area(obj, &area, LV_OBJ_POINT_TRANSFORM_FLAG_RECURSIVE);
    area.x2--;
    area.y2--;
    if (lv_obj_check_type(obj, &lv_label_class)) {
        lv_area_t shown = area;
        lv_area_t coords;
        lv_obj_get_coords(obj, &coords);
        /* A transformed label (the big YES) keeps its whole transformed box as its text. */
        bool transformed = coords.x1 != area.x1 || coords.y1 != area.y1 || coords.x2 != area.x2 || coords.y2 != area.y2;
        lv_area_t ink = transformed ? area : text_extent(obj);
        if (intersect(&shown, &clip) && intersect(&ink, &clip)) {
            static const char *box_names[4] = {",\"x0\":", ",\"y0\":", ",\"x1\":", ",\"y1\":"};
            static const char *ink_names[4] = {",\"ix0\":", ",\"iy0\":", ",\"ix1\":", ",\"iy1\":"};
            helm_jsonw_raw(w, *first ? "\n{\"text\":" : ",\n{\"text\":");
            *first = false;
            helm_jsonw_string(w, lv_label_get_text(obj));
            put_area(w, box_names, &shown);
            put_area(w, ink_names, &ink);
            helm_jsonw_raw(w, "}");
        }
    }
    if (!lv_obj_has_flag(obj, LV_OBJ_FLAG_OVERFLOW_VISIBLE) && !intersect(&clip, &area)) {
        return;
    }
    uint32_t count = lv_obj_get_child_count(obj);
    for (uint32_t i = 0; i < count; i++) {
        walk_labels(lv_obj_get_child(obj, (int32_t)i), clip, w, first);
    }
}

static void write_labels(const char *path)
{
    helm_jsonw_t w;
    helm_jsonw_init(&w, s_labels, sizeof s_labels);
    helm_jsonw_raw(&w, "[");
    bool first = true;
    lv_area_t screen = {0, 0, SCREEN_W - 1, SCREEN_H - 1};
    walk_labels(lv_screen_active(), screen, &w, &first);
    helm_jsonw_raw(&w, "\n]\n");
    if (w.overflow) {
        die("too many labels");
    }
    FILE *f = fopen(path, "wb");
    if (f == NULL || fwrite(s_labels, 1, w.len, f) != w.len || fclose(f) != 0) {
        die("cannot write the labels");
    }
}

int main(void)
{
    lv_init();
    lv_tick_set_cb(tick_cb);
    lv_display_t *display = lv_display_create(SCREEN_W, SCREEN_H);
    lv_display_set_color_format(display, LV_COLOR_FORMAT_RGB565);
    lv_display_set_buffers(display, s_pixels, NULL, sizeof s_pixels, LV_DISPLAY_RENDER_MODE_FULL);
    lv_display_set_flush_cb(display, flush_cb);
    ui_init(post);

    const helm_deck_config_t cfg = {"helm-host", NULL, 0, emit, NULL};
    helm_deck_init(&s_deck, &cfg);

    while (fgets(s_line, sizeof s_line, stdin) != NULL) {
        size_t n = strlen(s_line);
        if (n > 0 && s_line[n - 1] != '\n' && !feof(stdin)) {
            die("line too long");
        }
        char *cmd = strtok(s_line, " \r\n");
        if (cmd == NULL) {
            continue;
        }
        s_now = parse_ms(strtok(NULL, " \r\n"));
        if (strcmp(cmd, "model") == 0) {
            const char *hex = strtok(NULL, " \r\n");
            size_t len = from_hex(hex != NULL ? hex : "", s_frame, sizeof s_frame);
            helm_deck_rx(&s_deck, s_frame, len, s_now);
        } else if (strcmp(cmd, "knob") == 0) {
            const char *delta = strtok(NULL, " \r\n");
            helm_deck_knob(&s_deck, delta != NULL ? (int32_t)strtol(delta, NULL, 10) : 0, s_now);
        } else if (strcmp(cmd, "press") == 0) {
            const char *is_long = strtok(NULL, " \r\n");
            helm_deck_knob_press(&s_deck, is_long != NULL && strcmp(is_long, "1") == 0, s_now);
        } else if (strcmp(cmd, "key") == 0) {
            helm_action_t key = parse_key(strtok(NULL, " \r\n"));
            const char *phase = strtok(NULL, " \r\n");
            if (phase != NULL && strcmp(phase, "down") == 0) {
                helm_deck_key_down(&s_deck, key, s_now);
            } else if (phase != NULL && strcmp(phase, "up") == 0) {
                helm_deck_key_up(&s_deck, key, s_now);
            } else {
                die("bad key phase");
            }
        } else if (strcmp(cmd, "tick") == 0) {
            helm_deck_tick(&s_deck, s_now);
        } else if (strcmp(cmd, "render") == 0) {
            const char *ppm = strtok(NULL, " \r\n");
            const char *labels = strtok(NULL, " \r\n");
            if (ppm == NULL || labels == NULL) {
                die("render needs an image path and a labels path");
            }
            ui_render(&s_deck, s_now);
            lv_obj_invalidate(lv_screen_active());
            lv_refr_now(display);
            write_ppm(ppm);
            write_labels(labels);
        } else {
            die("unknown command");
        }
    }
    return 0;
}
