/*
 * Line-oriented driver for tests/test_firmware_core.py. One request per input
 * line, one answer per output line. Strings travel as hex so any byte can;
 * "-" stands for an empty string.
 *
 *   event hello <fw-hex> [<cap-hex>...]   -> frame hex
 *   event key <yes|later|hold|focus> <down|up|held> [<ref-hex>]   (no ref: null)
 *   event knob <int>
 *   event knob_press <0|1>
 *   event select <ref-hex>
 *   event seen | event resync
 *   model <stream-hex>  -> per frame: "ok <payload-hex>" with the parsed model
 *                          written back out, or "err <status>"; "none" if no frame
 *   stream <hex>        -> "<frames> <expired-frames> <discarded> <corrupt>", the
 *                          bytes pushed one at a time, then helm_decoder_expire;
 *                          frames as type:payload-hex joined by ",", or "-"
 *   tint <project-hex>  -> helm_lights_project_tint of the name, 0 to 3
 */
#define _POSIX_C_SOURCE 200809L

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "helm_event.h"
#include "helm_frame.h"
#include "helm_lights.h"
#include "helm_model.h"
#include "support.h"

#define MAX_ARGS 32
#define BYTES_MAX (4 * HELM_FRAME_MAX)

static uint8_t bytes[BYTES_MAX];
static char hex_out[2 * BYTES_MAX + 1];
static helm_decoder_t decoder;
static helm_model_t model;

typedef struct {
    char *out;
    size_t len;
    size_t cap;
    int count;
} list_t;

static void list_add(list_t *l, const char *text)
{
    size_t n = strlen(text);
    if (l->len + n + 2 > l->cap) {
        fprintf(stderr, "helm_wire_tool: output too long\n");
        exit(2);
    }
    if (l->count > 0) {
        l->out[l->len++] = ',';
    }
    memcpy(l->out + l->len, text, n + 1);
    l->len += n;
    l->count++;
}

static char *decode_hex_arg(const char *hex, size_t *len_out)
{
    if (strcmp(hex, "-") == 0) {
        hex = "";
    }
    size_t n = strlen(hex);
    char *s = malloc(n / 2 + 1);
    long got = s != NULL ? helm_test_from_hex(hex, n, (uint8_t *)s, n / 2) : -1;
    if (got < 0) {
        fprintf(stderr, "helm_wire_tool: bad hex argument\n");
        exit(2);
    }
    s[got] = '\0';
    if (len_out != NULL) {
        *len_out = (size_t)got;
    }
    return s;
}

static int index_of(const char *name, const char *const *names, int count)
{
    for (int i = 0; i < count; i++) {
        if (strcmp(name, names[i]) == 0) {
            return i;
        }
    }
    fprintf(stderr, "helm_wire_tool: unknown name %s\n", name);
    exit(2);
}

static void do_event(char **argv, int argc)
{
    static const char *const types[] = {"hello", "key", "knob", "knob_press", "select", "seen", "resync"};
    static const char *const keys[] = {"yes", "later", "hold", "focus"};
    static const char *const phases[] = {"down", "up", "held"};
    helm_event_t ev;
    char *owned[MAX_ARGS] = {0};
    const char *caps[MAX_ARGS];
    memset(&ev, 0, sizeof ev);
    if (argc < 1) {
        exit(2);
    }
    ev.type = (helm_event_type_t)index_of(argv[0], types, 7);
    switch (ev.type) {
    case HELM_EVENT_HELLO:
        owned[0] = decode_hex_arg(argv[1], NULL);
        ev.u.hello.fw = owned[0];
        for (int i = 2; i < argc; i++) {
            owned[i] = decode_hex_arg(argv[i], NULL);
            caps[i - 2] = owned[i];
        }
        ev.u.hello.caps = caps;
        ev.u.hello.cap_count = (size_t)(argc - 2);
        break;
    case HELM_EVENT_KEY:
        ev.u.key.key = (helm_action_t)index_of(argv[1], keys, 4);
        ev.u.key.phase = (helm_key_phase_t)index_of(argv[2], phases, 3);
        if (argc > 3) {
            owned[0] = decode_hex_arg(argv[3], NULL);
            ev.u.key.ref = owned[0];
        }
        break;
    case HELM_EVENT_KNOB:
        ev.u.knob.delta = (int32_t)strtol(argv[1], NULL, 10);
        break;
    case HELM_EVENT_KNOB_PRESS:
        ev.u.knob_press.long_press = strcmp(argv[1], "1") == 0;
        break;
    case HELM_EVENT_SELECT:
        owned[0] = decode_hex_arg(argv[1], NULL);
        ev.u.select.ref = owned[0];
        break;
    case HELM_EVENT_SEEN:
    case HELM_EVENT_RESYNC:
        break;
    }
    size_t n = helm_event_frame(&ev, bytes, sizeof bytes);
    helm_test_to_hex(bytes, n, hex_out);
    printf("%s\n", n == 0 ? "toolarge" : hex_out);
    for (int i = 0; i < MAX_ARGS; i++) {
        free(owned[i]);
    }
}

static void collect_frame(void *ctx, const helm_frame_t *frame)
{
    static char entry[2 * HELM_FRAME_MAX + 16];
    list_t *l = (list_t *)ctx;
    int at = snprintf(entry, sizeof entry, "%u:", (unsigned)frame->type);
    helm_test_to_hex(frame->payload, frame->len, entry + at);
    list_add(l, entry);
}

static char list_buf_a[4 * BYTES_MAX];
static char list_buf_b[4 * BYTES_MAX];

static void do_stream(const char *hex)
{
    long n = helm_test_from_hex(hex, strlen(hex), bytes, sizeof bytes);
    if (n < 0) {
        exit(2);
    }
    list_t fed = {list_buf_a, 0, sizeof list_buf_a, 0};
    list_t expired = {list_buf_b, 0, sizeof list_buf_b, 0};
    list_buf_a[0] = list_buf_b[0] = '\0';
    helm_decoder_init(&decoder);
    for (long i = 0; i < n; i++) {
        helm_decoder_push(&decoder, bytes[i], collect_frame, &fed);
    }
    helm_decoder_expire(&decoder, collect_frame, &expired);
    printf("%s %s %u %u\n", fed.count ? fed.out : "-", expired.count ? expired.out : "-",
           (unsigned)decoder.discarded_bytes, (unsigned)decoder.corrupt_frames);
}

static void model_frame(void *ctx, const helm_frame_t *frame)
{
    static uint8_t json[HELM_FRAME_MAX_PAYLOAD + 1];
    static char entry[2 * (HELM_FRAME_MAX_PAYLOAD + 1) + 16];
    list_t *l = (list_t *)ctx;
    helm_parse_status_t st = helm_model_parse(frame->payload, frame->len, &model);
    if (st != HELM_PARSE_OK) {
        snprintf(entry, sizeof entry, "err %s", helm_parse_status_name(st));
    } else {
        size_t len = helm_test_model_json(&model, json, sizeof json);
        memcpy(entry, "ok ", 3);
        helm_test_to_hex(json, len, entry + 3);
    }
    list_add(l, entry);
}

static void do_model(const char *hex)
{
    long n = helm_test_from_hex(hex, strlen(hex), bytes, sizeof bytes);
    if (n < 0) {
        exit(2);
    }
    list_t out = {list_buf_a, 0, sizeof list_buf_a, 0};
    helm_decoder_init(&decoder);
    for (long i = 0; i < n; i++) {
        helm_decoder_push(&decoder, bytes[i], model_frame, &out);
    }
    printf("%s\n", out.count ? out.out : "none");
}

int main(void)
{
    char *line = NULL;
    size_t cap = 0;
    ssize_t got;
    setvbuf(stdout, NULL, _IOFBF, 1 << 16);
    while ((got = getline(&line, &cap, stdin)) > 0) {
        char *argv[MAX_ARGS];
        int argc = 0;
        for (char *tok = strtok(line, " \t\r\n"); tok != NULL && argc < MAX_ARGS; tok = strtok(NULL, " \t\r\n")) {
            argv[argc++] = tok;
        }
        if (argc == 0) {
            continue;
        }
        if (strcmp(argv[0], "event") == 0) {
            do_event(argv + 1, argc - 1);
        } else if (strcmp(argv[0], "stream") == 0 && argc == 2) {
            do_stream(argv[1]);
        } else if (strcmp(argv[0], "model") == 0 && argc == 2) {
            do_model(argv[1]);
        } else if (strcmp(argv[0], "tint") == 0 && argc == 2) {
            char *project = decode_hex_arg(argv[1], NULL);
            printf("%d\n", helm_lights_project_tint(project));
            free(project);
        } else {
            fprintf(stderr, "helm_wire_tool: bad request %s\n", argv[0]);
            return 2;
        }
    }
    free(line);
    return 0;
}
