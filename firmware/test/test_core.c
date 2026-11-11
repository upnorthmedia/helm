/*
 * Unit tests for firmware/core on the host. Usage: test_core <cable_frame.txt>
 * (the vendor vector file in tests/vectors/). Exits non-zero on any failure.
 */
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "helm_controls.h"
#include "helm_deck.h"
#include "helm_event.h"
#include "helm_frame.h"
#include "helm_jsonw.h"
#include "helm_knob.h"
#include "helm_lights.h"
#include "helm_model.h"
#include "helm_tone.h"
#include "support.h"

static int checks;
static int failures;

#define CHECK(cond)                                                              \
    do {                                                                         \
        checks++;                                                                \
        if (!(cond)) {                                                           \
            failures++;                                                          \
            fprintf(stderr, "%s:%d: CHECK(%s) failed\n", __FILE__, __LINE__, #cond); \
        }                                                                        \
    } while (0)

#define CHECK_INT(got, want)                                                                      \
    do {                                                                                          \
        long long got_ = (long long)(got), want_ = (long long)(want);                             \
        checks++;                                                                                 \
        if (got_ != want_) {                                                                      \
            failures++;                                                                           \
            fprintf(stderr, "%s:%d: %s is %lld, want %lld\n", __FILE__, __LINE__, #got, got_, want_); \
        }                                                                                         \
    } while (0)

#define CHECK_STR(got, want)                                                                         \
    do {                                                                                             \
        const char *got_ = (got), *want_ = (want);                                                   \
        checks++;                                                                                    \
        if (got_ == NULL || want_ == NULL ? got_ != want_ : strcmp(got_, want_) != 0) {              \
            failures++;                                                                              \
            fprintf(stderr, "%s:%d: %s is \"%s\", want \"%s\"\n", __FILE__, __LINE__, #got,          \
                    got_ ? got_ : "(null)", want_ ? want_ : "(null)");                               \
        }                                                                                            \
    } while (0)

/* ---------------------------------------------------------------- frames */

typedef struct {
    int count;
    uint8_t types[64];
    uint8_t payloads[64][HELM_FRAME_MAX_PAYLOAD];
    uint16_t lens[64];
} frames_t;

static frames_t got_frames;

static void collect(void *ctx, const helm_frame_t *frame)
{
    frames_t *f = (frames_t *)ctx;
    if (f->count < 64) {
        f->types[f->count] = frame->type;
        f->lens[f->count] = frame->len;
        memcpy(f->payloads[f->count], frame->payload, frame->len);
        f->count++;
    }
}

static uint8_t big_a[4 * HELM_FRAME_MAX];
static uint8_t big_b[4 * HELM_FRAME_MAX];
static char hex_buf[8 * HELM_FRAME_MAX + 1];

static char *read_file(const char *path)
{
    FILE *f = fopen(path, "rb");
    if (f == NULL) {
        return NULL;
    }
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    char *text = malloc((size_t)n + 1);
    if (text != NULL && fread(text, 1, (size_t)n, f) != (size_t)n) {
        free(text);
        text = NULL;
    }
    if (text != NULL) {
        text[n] = '\0';
    }
    fclose(f);
    return text;
}

/* Split a line in place on tabs. */
static int split_tabs(char *line, char **fields, int max)
{
    int n = 0;
    fields[n++] = line;
    for (char *p = line; *p != '\0' && n < max; p++) {
        if (*p == '\t') {
            *p = '\0';
            fields[n++] = p + 1;
        }
    }
    return n;
}

static void test_vectors(const char *path)
{
    char *text = read_file(path);
    CHECK(text != NULL);
    if (text == NULL) {
        fprintf(stderr, "cannot read %s\n", path);
        return;
    }
    int encodes = 0, streams = 0;
    for (char *line = strtok(text, "\n"); line != NULL; line = strtok(NULL, "\n")) {
        char *f[8];
        int n = split_tabs(line, f, 8);
        if (strcmp(f[0], "encode") == 0 && n == 5) {
            long plen = helm_test_from_hex(f[3], strlen(f[3]), big_a, sizeof big_a);
            CHECK(plen >= 0);
            size_t len = helm_frame_encode((uint8_t)atoi(f[2]), big_a, (size_t)plen, big_b, sizeof big_b);
            helm_test_to_hex(big_b, len, hex_buf);
            if (strcmp(hex_buf, f[4]) != 0) {
                fprintf(stderr, "vector encode %s differs\n", f[1]);
            }
            CHECK(strcmp(hex_buf, f[4]) == 0);
            encodes++;
        } else if (strcmp(f[0], "stream") == 0 && n == 6) {
            long ilen = helm_test_from_hex(f[2], strlen(f[2]), big_a, sizeof big_a);
            CHECK(ilen >= 0);
            static helm_decoder_t d;
            helm_decoder_init(&d);
            got_frames.count = 0;
            for (long i = 0; i < ilen; i++) {
                helm_decoder_push(&d, big_a[i], collect, &got_frames);
            }
            /* Expected frames: type:payload-hex joined by ",", or "-". */
            int want = 0;
            bool same = true;
            if (strcmp(f[3], "-") != 0) {
                for (char *part = f[3]; part != NULL;) {
                    char *comma = strchr(part, ',');
                    if (comma != NULL) {
                        *comma = '\0';
                    }
                    char *colon = strchr(part, ':');
                    long t = strtol(part, NULL, 10);
                    long pl = helm_test_from_hex(colon + 1, strlen(colon + 1), big_b, sizeof big_b);
                    if (want >= got_frames.count || got_frames.types[want] != t || got_frames.lens[want] != pl ||
                        memcmp(got_frames.payloads[want], big_b, (size_t)pl) != 0) {
                        same = false;
                    }
                    want++;
                    part = comma != NULL ? comma + 1 : NULL;
                }
            }
            if (!same || want != got_frames.count) {
                fprintf(stderr, "vector stream %s: frames differ\n", f[1]);
            }
            CHECK(same && want == got_frames.count);
            CHECK_INT(d.discarded_bytes, atol(f[4]));
            CHECK_INT(d.corrupt_frames, atol(f[5]));
            streams++;
        }
    }
    CHECK(encodes >= 10);
    CHECK(streams >= 17);
    free(text);
}

static void test_crc(void)
{
    CHECK_INT(helm_crc16((const uint8_t *)"123456789", 9), 0x29B1);
}

static void test_encode_limits(void)
{
    static uint8_t payload[HELM_FRAME_MAX_PAYLOAD + 1];
    static uint8_t out[HELM_FRAME_MAX + 8];
    memset(payload, 'x', sizeof payload);
    CHECK_INT(helm_frame_encode(1, payload, HELM_FRAME_MAX_PAYLOAD, out, sizeof out), HELM_FRAME_MAX);
    CHECK_INT(helm_frame_encode(1, payload, HELM_FRAME_MAX_PAYLOAD + 1, out, sizeof out), 0);
    CHECK_INT(helm_frame_encode(1, payload, 2, out, 9), 0); /* needs 10 */
    CHECK_INT(helm_frame_encode(1, payload, 2, out, 10), 10);

    /* In place: the payload already sits after the header. */
    uint8_t a[16], b[16];
    memcpy(a + 6, "{}", 2);
    CHECK_INT(helm_frame_encode(1, a + 6, 2, a, sizeof a), 10);
    CHECK_INT(helm_frame_encode(1, (const uint8_t *)"{}", 2, b, sizeof b), 10);
    CHECK(memcmp(a, b, 10) == 0);
}

static uint32_t rng_state = 7;
static uint32_t rng(void)
{
    rng_state ^= rng_state << 13;
    rng_state ^= rng_state >> 17;
    rng_state ^= rng_state << 5;
    return rng_state;
}

static void test_round_trip_random(void)
{
    static helm_decoder_t d;
    static uint8_t stream[64 * 700];
    static uint8_t payloads[50][600];
    size_t lens[50], pos = 0;
    for (int i = 0; i < 50; i++) {
        lens[i] = rng() % 600;
        for (size_t j = 0; j < lens[i]; j++) {
            payloads[i][j] = (uint8_t)rng();
        }
        pos += helm_frame_encode(i % 2 ? 4 : 1, payloads[i], lens[i], stream + pos, sizeof stream - pos);
    }
    helm_decoder_init(&d);
    got_frames.count = 0;
    helm_decoder_feed(&d, stream, pos, collect, &got_frames);
    CHECK_INT(got_frames.count, 50);
    bool same = got_frames.count == 50;
    for (int i = 0; same && i < 50; i++) {
        same = got_frames.lens[i] == lens[i] && memcmp(got_frames.payloads[i], payloads[i], lens[i]) == 0;
    }
    CHECK(same);
    CHECK_INT(d.discarded_bytes, 0);
    CHECK_INT(d.corrupt_frames, 0);
}

static void test_bit_flips(void)
{
    static helm_decoder_t d;
    uint8_t good[64], follow[64], buf[128];
    const char *a = "{\"t\":\"model\",\"seq\":1}", *b = "{\"t\":\"model\",\"seq\":2}";
    size_t gl = helm_frame_encode(1, (const uint8_t *)a, strlen(a), good, sizeof good);
    size_t fl = helm_frame_encode(1, (const uint8_t *)b, strlen(b), follow, sizeof follow);
    int ok = 0;
    for (size_t bit = 0; bit < gl * 8; bit++) {
        memcpy(buf, good, gl);
        buf[bit / 8] ^= (uint8_t)(1u << (bit % 8));
        memcpy(buf + gl, follow, fl);
        helm_decoder_init(&d);
        got_frames.count = 0;
        helm_decoder_feed(&d, buf, gl + fl, collect, &got_frames);
        /* A flipped length byte can make the decoder wait; expiry resyncs. */
        helm_decoder_expire(&d, collect, &got_frames);
        if (got_frames.count == 1 && got_frames.lens[0] == strlen(b) && memcmp(got_frames.payloads[0], b, strlen(b)) == 0) {
            ok++;
        }
    }
    CHECK_INT(ok, (long long)(gl * 8));
}

static void test_truncated_expires(void)
{
    static helm_decoder_t d;
    uint8_t first[32], second[32];
    size_t fl = helm_frame_encode(1, (const uint8_t *)"{\"t\":\"a\"}", 9, first, sizeof first);
    size_t sl = helm_frame_encode(1, (const uint8_t *)"{\"t\":\"b\"}", 9, second, sizeof second);
    helm_decoder_init(&d);
    got_frames.count = 0;
    helm_decoder_feed(&d, first, fl - 3, collect, &got_frames);
    CHECK_INT(got_frames.count, 0);
    CHECK(helm_decoder_pending(&d));
    helm_decoder_expire(&d, collect, &got_frames);
    CHECK_INT(got_frames.count, 0);
    CHECK_INT(d.corrupt_frames, 1);
    CHECK(!helm_decoder_pending(&d));
    helm_decoder_feed(&d, second, sl, collect, &got_frames);
    CHECK_INT(got_frames.count, 1);
    CHECK(memcmp(got_frames.payloads[0], "{\"t\":\"b\"}", 9) == 0);
}

static void test_garbage_between_frames(void)
{
    static helm_decoder_t d;
    static uint8_t stream[20 * 80];
    size_t pos = 0;
    char payload[16];
    for (int i = 0; i < 20; i++) {
        uint32_t noise = rng() % 40;
        for (uint32_t j = 0; j < noise; j++) {
            uint8_t b = (uint8_t)rng();
            stream[pos++] = b == 0xA5 ? 0x00 : b;
        }
        int n = snprintf(payload, sizeof payload, "{\"n\":%d}", i);
        pos += helm_frame_encode(1, (const uint8_t *)payload, (size_t)n, stream + pos, sizeof stream - pos);
    }
    helm_decoder_init(&d);
    got_frames.count = 0;
    helm_decoder_feed(&d, stream, pos, collect, &got_frames);
    CHECK_INT(got_frames.count, 20);
}

/* A max-size frame fills the buffer exactly and still decodes, and a
 * stream of noise never grows the buffer past one frame. */
static void test_buffer_bound(void)
{
    static helm_decoder_t d;
    static uint8_t payload[HELM_FRAME_MAX_PAYLOAD];
    static uint8_t frame[HELM_FRAME_MAX];
    memset(payload, 'z', sizeof payload);
    size_t n = helm_frame_encode(3, payload, sizeof payload, frame, sizeof frame);
    helm_decoder_init(&d);
    got_frames.count = 0;
    for (size_t i = 0; i < n; i++) {
        helm_decoder_push(&d, frame[i], collect, &got_frames);
        CHECK(d.len < HELM_FRAME_MAX);
    }
    CHECK_INT(got_frames.count, 1);
    for (int i = 0; i < 100000; i++) {
        helm_decoder_push(&d, (uint8_t)rng(), collect, &got_frames);
        if (d.len >= HELM_FRAME_MAX) {
            CHECK(d.len < HELM_FRAME_MAX);
            break;
        }
    }
}

/* ---------------------------------------------------------------- model */

static helm_model_t model_a;

static helm_parse_status_t parse_text(const char *json)
{
    return helm_model_parse((const uint8_t *)json, strlen(json), &model_a);
}

#define LINK_OK "\"link\":{\"bridge_ok\":true,\"firstmate_can_receive\":true,\"posture\":\"listening\",\"stale_reason\":null}"
#define COUNTS "\"counts\":{\"decisions\":1,\"working\":4,\"queued\":1,\"prs_ready\":1,\"landed_today\":3,\"herdr_working\":3,\"herdr_blocked\":0}"
#define ITEM_A                                                                                              \
    "{\"ref\":\"decision|main|t1|k1\",\"kind\":\"decision\",\"color\":\"red\",\"short_id\":\"t1\",\"age_s\":95," \
    "\"unseen\":true,\"home\":\"main\",\"detail\":\"Pick one.\",\"actions\":[\"yes\",\"later\",\"hold\",\"focus\"]," \
    "\"pr_url\":null,\"checks\":null}"

static void test_model_parse_full(void)
{
    const char *json =
        " {\"t\" : \"model\", \"seq\": 42, " LINK_OK ", \"attention\":\"new\", \"unseen\":1, " COUNTS
        ", \"items\":[" ITEM_A
        ",{\"ref\":\"pr|main|https://github.com/o/r/pull/7\",\"kind\":\"pr_ready\",\"color\":\"blue\","
        "\"short_id\":\"r#7\",\"age_s\":1260,\"unseen\":false,\"home\":\"main\",\"detail\":\"Merge?\","
        "\"actions\":[\"focus\",\"yes\"],\"pr_url\":\"https://github.com/o/r/pull/7\",\"checks\":\"green\","
        "\"future_field\":{\"nested\":[1,2.5e3,{\"x\":null}]}}],"
        "\"result\":{\"request_id\":\"helm-yes-1\",\"state\":\"queued\",\"text\":\"Queued\"}, \"chime\":true,"
        "\"extra\":\"ignored\"}\n";
    CHECK_INT(parse_text(json), HELM_PARSE_OK);
    const helm_model_t *m = &model_a;
    CHECK_INT(m->seq, 42);
    CHECK(m->link.bridge_ok);
    CHECK_INT(m->link.firstmate_can_receive, HELM_TRI_TRUE);
    CHECK_STR(helm_model_str(m, m->link.posture), "listening");
    CHECK(helm_model_str(m, m->link.stale_reason) == NULL);
    CHECK_INT(m->attention, HELM_ATTENTION_NEW);
    CHECK_INT(m->unseen, 1);
    CHECK_INT(m->counts.working, 4);
    CHECK_INT(m->counts.herdr_working, 3);
    CHECK_INT(m->item_count, 2);
    CHECK_STR(helm_model_str(m, m->items[0].ref), "decision|main|t1|k1");
    CHECK_INT(m->items[0].kind, HELM_KIND_DECISION);
    CHECK_INT(m->items[0].actions, 0x0F);
    CHECK(m->items[0].unseen);
    CHECK(helm_model_str(m, m->items[0].pr_url) == NULL);
    CHECK_INT(m->items[0].checks, HELM_CHECKS_NONE);
    CHECK_INT(m->items[1].kind, HELM_KIND_PR_READY);
    CHECK_INT(m->items[1].color, HELM_COLOR_BLUE);
    CHECK_INT(m->items[1].age_s, 1260);
    CHECK_INT(m->items[1].actions, HELM_ACTION_BIT(HELM_ACTION_YES) | HELM_ACTION_BIT(HELM_ACTION_FOCUS));
    CHECK_STR(helm_model_str(m, m->items[1].pr_url), "https://github.com/o/r/pull/7");
    CHECK_INT(m->items[1].checks, HELM_CHECKS_GREEN);
    CHECK(m->has_result);
    CHECK_INT(m->result.state, HELM_RESULT_QUEUED);
    CHECK_STR(helm_model_str(m, m->result.text), "Queued");
    CHECK(m->chime);
    /* Fields an older bridge does not send take their defaults. */
    CHECK(!m->link.away);
    CHECK(!m->link.mac_locked);
    CHECK(helm_model_str(m, m->items[0].project) == NULL);
    CHECK(!m->usage.five_hour_left.known && !m->usage.week_left.known);
    CHECK(!m->context.top_used.known && !m->context.near_limit.known);
    CHECK(helm_model_str(m, m->context.top_agent) == NULL);
}

static void test_model_parse_new_fields(void)
{
    const char *json =
        "{\"t\":\"model\",\"seq\":3,\"link\":{\"bridge_ok\":true,\"firstmate_can_receive\":true,\"posture\":\"away\","
        "\"stale_reason\":null,\"away\":true,\"mac_locked\":true},\"attention\":\"calm\",\"unseen\":0," COUNTS ",\"items\":["
        "{\"ref\":\"r\",\"kind\":\"decision\",\"color\":\"red\",\"short_id\":\"s\",\"age_s\":0,\"unseen\":false,"
        "\"home\":\"h\",\"detail\":\"d\",\"actions\":[\"focus\"],\"pr_url\":null,\"checks\":null,\"project\":\"helm\"}],"
        "\"result\":null,\"chime\":false,\"usage\":{\"five_hour_left\":0,\"five_hour_resets_s\":2147483647,"
        "\"week_left\":100,\"week_resets_s\":null,\"later\":[1]},"
        "\"context\":{\"top_used\":91,\"top_agent\":\"widget-cache\",\"near_limit\":2,\"later\":{}}}";
    CHECK_INT(parse_text(json), HELM_PARSE_OK);
    const helm_model_t *m = &model_a;
    CHECK(m->link.away);
    CHECK(m->link.mac_locked);
    CHECK(m->context.top_used.known);
    CHECK_INT(m->context.top_used.value, 91);
    CHECK_STR(helm_model_str(m, m->context.top_agent), "widget-cache");
    CHECK(m->context.near_limit.known);
    CHECK_INT(m->context.near_limit.value, 2);
    CHECK_STR(helm_model_str(m, m->items[0].project), "helm");
    CHECK(m->usage.five_hour_left.known);
    CHECK_INT(m->usage.five_hour_left.value, 0);
    CHECK_INT(m->usage.five_hour_resets_s.value, INT32_MAX);
    CHECK(m->usage.week_left.known);
    CHECK_INT(m->usage.week_left.value, 100);
    CHECK(!m->usage.week_resets_s.known);
}

static void test_model_strings(void)
{
    const char *json = "{\"t\":\"model\",\"seq\":1," LINK_OK ",\"attention\":\"calm\",\"unseen\":0," COUNTS
                       ",\"items\":[{\"ref\":\"a\\\"b\\\\c\\/d\",\"kind\":\"decision\",\"color\":\"red\","
                       "\"short_id\":\"\\u00e9\\ud83d\\ude00\xc4\x91\",\"age_s\":-5,\"unseen\":false,\"home\":\"\","
                       "\"detail\":\"l1\\nl2\\tx\\b\\f\\r\\u001f\",\"actions\":[]}],\"chime\":false}";
    CHECK_INT(parse_text(json), HELM_PARSE_OK);
    CHECK_STR(helm_model_str(&model_a, model_a.items[0].ref), "a\"b\\c/d");
    CHECK_STR(helm_model_str(&model_a, model_a.items[0].short_id), "\xc3\xa9\xf0\x9f\x98\x80\xc4\x91");
    CHECK_STR(helm_model_str(&model_a, model_a.items[0].home), "");
    CHECK_STR(helm_model_str(&model_a, model_a.items[0].detail), "l1\nl2\tx\b\f\r\x1f");
    CHECK_INT(model_a.items[0].age_s, -5);
    CHECK_INT(model_a.items[0].actions, 0);
    CHECK(!model_a.has_result);
}

static void test_model_errors(void)
{
#define BASE_HEAD "{\"t\":\"model\",\"seq\":1," LINK_OK ",\"attention\":\"calm\",\"unseen\":0," COUNTS
    static const struct {
        const char *json;
        helm_parse_status_t want;
    } cases[] = {
        {BASE_HEAD ",\"items\":[],\"chime\":false}", HELM_PARSE_OK},
        {"", HELM_PARSE_SYNTAX},
        {"[]", HELM_PARSE_NOT_MODEL},
        {"{\"t\":\"key\"}", HELM_PARSE_NOT_MODEL},
        {"{\"t\":1,\"seq\":1}", HELM_PARSE_NOT_MODEL},
        {BASE_HEAD ",\"items\":[],\"chime\":false} x", HELM_PARSE_SYNTAX},
        {BASE_HEAD ",\"items\":[],\"chime\":false,}", HELM_PARSE_SYNTAX},
        {BASE_HEAD ",\"items\":[,],\"chime\":false}", HELM_PARSE_SYNTAX},
        {BASE_HEAD ",\"items\":[]}", HELM_PARSE_MISSING},                      /* chime is required */
        {BASE_HEAD ",\"items\":[],\"chime\":null}", HELM_PARSE_MISSING},       /* null counts as missing */
        {BASE_HEAD ",\"items\":[],\"chime\":0}", HELM_PARSE_TYPE},
        {BASE_HEAD ",\"items\":{},\"chime\":false}", HELM_PARSE_TYPE},
        {BASE_HEAD ",\"items\":[1],\"chime\":false}", HELM_PARSE_TYPE},         /* item is not an object */
        {BASE_HEAD ",\"items\":[],\"chime\":false,\"seq\":true}", HELM_PARSE_TYPE}, /* bool is not an int */
        {BASE_HEAD ",\"items\":[],\"chime\":false,\"seq\":1.0}", HELM_PARSE_TYPE},
        {BASE_HEAD ",\"items\":[],\"chime\":false,\"seq\":1e2}", HELM_PARSE_TYPE},
        {BASE_HEAD ",\"items\":[],\"chime\":false,\"seq\":01}", HELM_PARSE_SYNTAX},
        {BASE_HEAD ",\"items\":[],\"chime\":false,\"seq\":99999999999999999999}", HELM_PARSE_RANGE},
        {BASE_HEAD ",\"items\":[],\"chime\":false,\"unseen\":2147483648}", HELM_PARSE_RANGE},
        {BASE_HEAD ",\"items\":[],\"chime\":false,\"attention\":\"loud\"}", HELM_PARSE_ENUM},
        {BASE_HEAD ",\"items\":[],\"chime\":false,\"link\":{}}", HELM_PARSE_MISSING},
        {BASE_HEAD ",\"items\":[],\"chime\":false,\"counts\":{\"decisions\":1}}", HELM_PARSE_MISSING},
        {BASE_HEAD ",\"items\":[],\"chime\":false,\"result\":{\"request_id\":\"r\",\"state\":\"queued\"}}", HELM_PARSE_MISSING},
        {BASE_HEAD ",\"items\":[],\"chime\":false,\"result\":{\"request_id\":\"r\",\"state\":\"maybe\",\"text\":\"\"}}", HELM_PARSE_ENUM},
        {BASE_HEAD ",\"items\":[],\"chime\":false,\"result\":null}", HELM_PARSE_OK},
        {BASE_HEAD ",\"items\":[{\"ref\":\"r\"}],\"chime\":false}", HELM_PARSE_MISSING},
        {BASE_HEAD ",\"items\":[],\"chime\":false,\"x\":\"\\u0000\"}", HELM_PARSE_UTF8},
        {BASE_HEAD ",\"items\":[],\"chime\":false,\"x\":\"\\ud800\"}", HELM_PARSE_UTF8},
        {BASE_HEAD ",\"items\":[],\"chime\":false,\"x\":\"\\udc00\"}", HELM_PARSE_UTF8},
        {BASE_HEAD ",\"items\":[],\"chime\":false,\"x\":\"\xc0\xaf\"}", HELM_PARSE_UTF8}, /* overlong */
        {BASE_HEAD ",\"items\":[],\"chime\":false,\"x\":\"\xed\xa0\x80\"}", HELM_PARSE_UTF8}, /* surrogate */
        {BASE_HEAD ",\"items\":[],\"chime\":false,\"x\":\"\xff\"}", HELM_PARSE_UTF8},
        {BASE_HEAD ",\"items\":[],\"chime\":false,\"x\":\"a\tb\"}", HELM_PARSE_SYNTAX}, /* raw control char */
        {BASE_HEAD ",\"items\":[],\"chime\":false,\"x\":\"\\q\"}", HELM_PARSE_SYNTAX},
        {BASE_HEAD ",\"items\":[],\"chime\":false,\"x\":[[[[[[[[[[[[[[[[[[[[]]]]]]]]]]]]]]]]]]]]}", HELM_PARSE_TOO_DEEP},
        {BASE_HEAD ",\"items\":[],\"chime\":false,\"x\":[[[[[[[[[[1]]]]]]]]]]}", HELM_PARSE_OK},
        {BASE_HEAD ",\"items\":[],\"chime\":false,\"x\":nul}", HELM_PARSE_SYNTAX},
        {BASE_HEAD ",\"items\":[],\"chime\":false,\"usage\":null}", HELM_PARSE_OK},
        {BASE_HEAD ",\"items\":[],\"chime\":false,\"usage\":{}}", HELM_PARSE_OK},
        {BASE_HEAD ",\"items\":[],\"chime\":false,\"usage\":3}", HELM_PARSE_TYPE},
        {BASE_HEAD ",\"items\":[],\"chime\":false,\"usage\":{\"week_left\":101}}", HELM_PARSE_RANGE},
        {BASE_HEAD ",\"items\":[],\"chime\":false,\"usage\":{\"week_left\":-1}}", HELM_PARSE_RANGE},
        {BASE_HEAD ",\"items\":[],\"chime\":false,\"usage\":{\"five_hour_resets_s\":-1}}", HELM_PARSE_RANGE},
        {BASE_HEAD ",\"items\":[],\"chime\":false,\"usage\":{\"week_left\":true}}", HELM_PARSE_TYPE},
        {BASE_HEAD ",\"items\":[],\"chime\":false,\"usage\":{\"week_left\":5.5}}", HELM_PARSE_TYPE},
        {BASE_HEAD ",\"items\":[],\"chime\":false,\"link\":{\"bridge_ok\":true,\"away\":1}}", HELM_PARSE_TYPE},
        {BASE_HEAD ",\"items\":[],\"chime\":false,\"link\":{\"bridge_ok\":true,\"away\":null}}", HELM_PARSE_OK},
        {BASE_HEAD ",\"items\":[],\"chime\":false,\"link\":{\"bridge_ok\":true,\"mac_locked\":1}}", HELM_PARSE_TYPE},
        {BASE_HEAD ",\"items\":[],\"chime\":false,\"context\":null}", HELM_PARSE_OK},
        {BASE_HEAD ",\"items\":[],\"chime\":false,\"context\":[]}", HELM_PARSE_TYPE},
        {BASE_HEAD ",\"items\":[],\"chime\":false,\"context\":{\"top_used\":101}}", HELM_PARSE_RANGE},
        {BASE_HEAD ",\"items\":[],\"chime\":false,\"context\":{\"near_limit\":-1}}", HELM_PARSE_RANGE},
        {BASE_HEAD ",\"items\":[],\"chime\":false,\"context\":{\"top_used\":true}}", HELM_PARSE_TYPE},
        {BASE_HEAD ",\"items\":[],\"chime\":false,\"context\":{\"top_agent\":3}}", HELM_PARSE_TYPE},
    };
    for (size_t i = 0; i < sizeof cases / sizeof cases[0]; i++) {
        helm_parse_status_t got = parse_text(cases[i].json);
        if (got != cases[i].want) {
            fprintf(stderr, "model error case %zu: got %s, want %s\n", i, helm_parse_status_name(got),
                    helm_parse_status_name(cases[i].want));
        }
        CHECK_INT(got, cases[i].want);
    }
    static const struct {
        const char *item;
        helm_parse_status_t want;
    } item_cases[] = {
        {"\"kind\":\"other\"", HELM_PARSE_ENUM},
        {"\"color\":\"pink\"", HELM_PARSE_ENUM},
        {"\"checks\":\"meh\"", HELM_PARSE_ENUM},
        {"\"actions\":[\"maybe\"]", HELM_PARSE_ENUM},
        {"\"actions\":[null]", HELM_PARSE_ENUM},
        {"\"actions\":[1]", HELM_PARSE_TYPE},
        {"\"unseen\":1", HELM_PARSE_TYPE},
        {"\"age_s\":\"1\"", HELM_PARSE_TYPE},
        {"\"pr_url\":5", HELM_PARSE_TYPE},
        {"\"project\":5", HELM_PARSE_TYPE},
        {"\"project\":null", HELM_PARSE_OK},
        {"\"ref\":null", HELM_PARSE_MISSING},
    };
    char json[1024];
    for (size_t i = 0; i < sizeof item_cases / sizeof item_cases[0]; i++) {
        /* The override comes after the good field, so the last value wins as in Python. */
        snprintf(json, sizeof json, "%s,\"items\":[%.*s,%s}],\"chime\":false}", BASE_HEAD,
                 (int)strlen(ITEM_A) - 1, ITEM_A, item_cases[i].item);
        helm_parse_status_t got = parse_text(json);
        if (got != item_cases[i].want) {
            fprintf(stderr, "item error case %zu: got %s\n", i, helm_parse_status_name(got));
        }
        CHECK_INT(got, item_cases[i].want);
    }
#undef BASE_HEAD
}

/* A model whose one detail nearly fills the frame parses whole. */
static void test_model_pool_holds_a_full_frame(void)
{
    static uint8_t json[HELM_FRAME_MAX_PAYLOAD + 64];
    static char detail[HELM_FRAME_MAX_PAYLOAD];
    static helm_model_t m;
    helm_test_model_init(&m, 9);
    size_t base;
    {
        m.item_count = 1;
        m.items[0].ref = helm_test_str(&m, "r");
        m.items[0].short_id = helm_test_str(&m, "s");
        m.items[0].home = helm_test_str(&m, "h");
        m.items[0].detail = helm_test_str(&m, "");
        m.items[0].pr_url = HELM_STR_NULL;
        m.items[0].project = HELM_STR_NULL;
        base = helm_test_model_json(&m, json, sizeof json);
    }
    size_t fill = HELM_FRAME_MAX_PAYLOAD - base;
    memset(detail, 'd', fill);
    detail[fill] = '\0';
    m.items[0].detail = helm_test_str(&m, detail);
    size_t len = helm_test_model_json(&m, json, sizeof json);
    CHECK_INT(len, HELM_FRAME_MAX_PAYLOAD);
    CHECK_INT(helm_model_parse(json, len, &model_a), HELM_PARSE_OK);
    CHECK_INT(strlen(helm_model_str(&model_a, model_a.items[0].detail)), fill);
    CHECK_INT(helm_model_parse(json, HELM_FRAME_MAX_PAYLOAD + 1, &model_a), HELM_PARSE_TOO_LARGE);
}

/* ---------------------------------------------------------------- events */

static const char *event_json(const helm_event_t *ev)
{
    static char out[512];
    size_t n = helm_event_payload(ev, (uint8_t *)out, sizeof out - 1);
    out[n] = '\0';
    return out;
}

static void test_events(void)
{
    helm_event_t ev;
    const char *caps[] = {"keys-4", "knob"};
    memset(&ev, 0, sizeof ev);
    ev.type = HELM_EVENT_HELLO;
    ev.u.hello.fw = "helm-0.1";
    ev.u.hello.caps = caps;
    ev.u.hello.cap_count = 2;
    CHECK_STR(event_json(&ev), "{\"t\":\"hello\",\"fw\":\"helm-0.1\",\"caps\":[\"keys-4\",\"knob\"],\"product\":\"helm\"}");
    ev.u.hello.cap_count = 0;
    CHECK_STR(event_json(&ev), "{\"t\":\"hello\",\"fw\":\"helm-0.1\",\"caps\":[],\"product\":\"helm\"}");

    memset(&ev, 0, sizeof ev);
    ev.type = HELM_EVENT_KEY;
    ev.u.key.key = HELM_ACTION_LATER;
    ev.u.key.phase = HELM_KEY_HELD;
    CHECK_STR(event_json(&ev), "{\"t\":\"key\",\"key\":\"later\",\"phase\":\"held\",\"ref\":null}");
    ev.u.key.ref = "pr:a\"b";
    CHECK_STR(event_json(&ev), "{\"t\":\"key\",\"key\":\"later\",\"phase\":\"held\",\"ref\":\"pr:a\\\"b\"}");

    memset(&ev, 0, sizeof ev);
    ev.type = HELM_EVENT_KNOB;
    ev.u.knob.delta = INT32_MIN;
    CHECK_STR(event_json(&ev), "{\"t\":\"knob\",\"delta\":-2147483648}");

    memset(&ev, 0, sizeof ev);
    ev.type = HELM_EVENT_KNOB_PRESS;
    ev.u.knob_press.long_press = true;
    CHECK_STR(event_json(&ev), "{\"t\":\"knob_press\",\"long\":true}");

    memset(&ev, 0, sizeof ev);
    ev.type = HELM_EVENT_SELECT;
    ev.u.select.ref = "q\"b\\s\x01\x1b\x7f\xc3\xa9\n";
    CHECK_STR(event_json(&ev), "{\"t\":\"select\",\"ref\":\"q\\\"b\\\\s\\u0001\\u001b\x7f\xc3\xa9\\n\"}");

    memset(&ev, 0, sizeof ev);
    ev.type = HELM_EVENT_SEEN;
    CHECK_STR(event_json(&ev), "{\"t\":\"seen\"}");
    ev.type = HELM_EVENT_RESYNC;
    CHECK_STR(event_json(&ev), "{\"t\":\"resync\"}");

    /* Frames carry the payload; too small a buffer gives 0. */
    uint8_t frame[64];
    CHECK_INT(helm_event_frame(&ev, frame, sizeof frame), 6 + 14 + 2);
    CHECK(memcmp(frame + 6, "{\"t\":\"resync\"}", 14) == 0);
    CHECK_INT(helm_event_frame(&ev, frame, 21), 0);
    CHECK_INT(helm_event_payload(&ev, frame, 13), 0);
}

/* ---------------------------------------------------------------- deck */

typedef struct {
    const char *ref;
    helm_item_kind_t kind;
    helm_color_t color;
    const char *short_id;
    bool unseen;
    uint8_t actions;
    const char *project; /* NULL for none */
} fx_item_t;

#define ALL_ACTIONS 0x0F
#define NO_YES (ALL_ACTIONS & ~HELM_ACTION_BIT(HELM_ACTION_YES))

static const fx_item_t DECISION = {"decision:demo-widget-api:pick-cache", HELM_KIND_DECISION, HELM_COLOR_RED, "widget-api", true, ALL_ACTIONS, NULL};
static const fx_item_t PR_READY = {"pr:sample-org/gizmo#42", HELM_KIND_PR_READY, HELM_COLOR_BLUE, "gizmo#42", true, ALL_ACTIONS, NULL};
static const fx_item_t WORKER_PROBLEM = {"task:demo-docs-sweep", HELM_KIND_WORKER_PROBLEM, HELM_COLOR_AMBER, "docs-sweep", false, NO_YES, NULL};
static const fx_item_t HERDR_BLOCKED = {"herdr:pane-7", HELM_KIND_HERDR_BLOCKED, HELM_COLOR_AMBER, "pane-7", false, HELM_ACTION_BIT(HELM_ACTION_FOCUS), NULL};

typedef struct {
    bool chime;
    int landed_today;
    bool stale; /* firstmate not listening */
    bool has_result;
    helm_result_state_t result_state;
    const char *result_text;
    bool away; /* firstmate away: the bridge drops YES / LATER / HOLD, but keep them here to test the deck's own lock */
    bool mac_locked; /* the Mac is locked: the bridge drops every action, but keep them here too */
} fx_opts_t;

static const fx_opts_t FX = {false, 3, false, false, HELM_RESULT_QUEUED, NULL, false, false};

static helm_model_t fx_model;
static helm_usage_t fx_usage; /* usage for the next fixture models; all unknown by default */
static int fx_context_near = -1; /* context.near_limit for the next fixture models; -1 is unknown */
static uint8_t fx_json[HELM_FRAME_MAX_PAYLOAD];
static uint8_t fx_frame[HELM_FRAME_MAX];

/* The frame sim/fixtures.model() would send. */
static size_t fx_build(int64_t seq, const fx_item_t *const *items, int n, fx_opts_t o)
{
    helm_model_t *m = &fx_model;
    helm_test_model_init(m, seq);
    m->link.posture = helm_test_str(m, o.stale ? "unknown" : (o.away ? "away" : "present"));
    m->link.away = o.away;
    m->link.mac_locked = o.mac_locked;
    if (o.stale) {
        m->link.firstmate_can_receive = HELM_TRI_FALSE;
        m->link.stale_reason = helm_test_str(m, "firstmate is not listening");
    }
    for (int i = 0; i < n; i++) {
        helm_item_t *it = &m->items[i];
        it->ref = helm_test_str(m, items[i]->ref);
        it->kind = items[i]->kind;
        it->color = items[i]->color;
        it->short_id = helm_test_str(m, items[i]->short_id);
        it->age_s = 10 * i;
        it->unseen = items[i]->unseen;
        it->home = helm_test_str(m, "main");
        it->detail = helm_test_str(m, "detail text");
        it->actions = items[i]->actions;
        it->pr_url = HELM_STR_NULL;
        it->checks = HELM_CHECKS_NONE;
        it->project = items[i]->project != NULL ? helm_test_str(m, items[i]->project) : HELM_STR_NULL;
        m->unseen += items[i]->unseen;
        m->counts.decisions += items[i]->kind == HELM_KIND_DECISION;
        m->counts.prs_ready += items[i]->kind == HELM_KIND_PR_READY;
        m->counts.herdr_blocked += items[i]->kind == HELM_KIND_HERDR_BLOCKED;
    }
    m->item_count = (uint16_t)n;
    m->attention = o.stale ? HELM_ATTENTION_UNKNOWN : (m->unseen ? HELM_ATTENTION_NEW : HELM_ATTENTION_CALM);
    m->counts.working = 4;
    m->counts.queued = 1;
    m->counts.landed_today = o.landed_today;
    m->counts.herdr_working = 3;
    m->chime = o.chime;
    m->usage = fx_usage;
    if (fx_context_near >= 0) {
        m->context.top_used = (helm_opt_int_t){true, 91};
        m->context.top_agent = helm_test_str(m, "widget-cache");
        m->context.near_limit = (helm_opt_int_t){true, fx_context_near};
    }
    if (o.has_result) {
        m->has_result = true;
        m->result.request_id = helm_test_str(m, "r1");
        m->result.state = o.result_state;
        m->result.text = helm_test_str(m, o.result_text != NULL ? o.result_text : "");
    }
    size_t len = helm_test_model_json(m, fx_json, sizeof fx_json);
    return helm_frame_encode(HELM_FRAME_TYPE_JSON, fx_json, len, fx_frame, sizeof fx_frame);
}

#define EV_MAX 64
static char ev_log[EV_MAX][96];
static int ev_count;

static void record(void *ctx, const helm_event_t *ev)
{
    (void)ctx;
    if (ev_count >= EV_MAX) {
        return;
    }
    char *out = ev_log[ev_count++];
    switch (ev->type) {
    case HELM_EVENT_KEY:
        snprintf(out, 96, "key:%s:%s:%s", helm_action_name(ev->u.key.key), helm_key_phase_name(ev->u.key.phase),
                 ev->u.key.ref != NULL ? ev->u.key.ref : "null");
        break;
    case HELM_EVENT_KNOB:
        snprintf(out, 96, "knob:%d", (int)ev->u.knob.delta);
        break;
    case HELM_EVENT_KNOB_PRESS:
        snprintf(out, 96, "knob_press:%d", ev->u.knob_press.long_press);
        break;
    case HELM_EVENT_SELECT:
        snprintf(out, 96, "select:%s", ev->u.select.ref);
        break;
    default:
        snprintf(out, 96, "%s", helm_event_type_name(ev->type));
    }
    /* Every event must also encode to a frame. */
    static uint8_t frame[HELM_FRAME_MAX];
    CHECK(helm_event_frame(ev, frame, sizeof frame) > 0);
}

/* Compare and clear the event log. Arguments: expected events, then NULL. */
static bool events_are(int line, ...)
{
    va_list ap;
    va_start(ap, line);
    int i = 0;
    bool same = true;
    for (const char *want = va_arg(ap, const char *); want != NULL; want = va_arg(ap, const char *), i++) {
        if (i >= ev_count || strcmp(ev_log[i], want) != 0) {
            same = false;
        }
    }
    va_end(ap);
    if (i != ev_count) {
        same = false;
    }
    if (!same) {
        fprintf(stderr, "line %d: events were:", line);
        for (int j = 0; j < ev_count; j++) {
            fprintf(stderr, " [%s]", ev_log[j]);
        }
        fprintf(stderr, "\n");
    }
    ev_count = 0;
    return same;
}
#define EVENTS(...) CHECK(events_are(__LINE__, __VA_ARGS__, (const char *)NULL))
#define NO_EVENTS() CHECK(events_are(__LINE__, (const char *)NULL))

static helm_deck_t deck;
static const char *const CAPS[] = {"screen-720", "keys-4", "knob", "lightbar-8", "chime"};
#define T 100000u

static void deck_fresh(void)
{
    helm_deck_config_t cfg = {"helm-test", CAPS, 5, record, NULL};
    helm_deck_init(&deck, &cfg);
    ev_count = 0;
}

static void send_model(int64_t seq, const fx_item_t *const *items, int n, fx_opts_t o, uint32_t now)
{
    size_t len = fx_build(seq, items, n, o);
    helm_deck_rx(&deck, fx_frame, len, now);
}

static const fx_item_t *const BUSY[] = {&DECISION, &PR_READY, &WORKER_PROBLEM, &HERDR_BLOCKED};
static const fx_item_t DECISION_P = {"decision:demo-widget-api:pick-cache", HELM_KIND_DECISION, HELM_COLOR_RED, "widget-api", true, ALL_ACTIONS, "widget-api"};
static const fx_item_t PR_READY_P = {"pr:sample-org/gizmo#42", HELM_KIND_PR_READY, HELM_COLOR_BLUE, "gizmo#42", true, ALL_ACTIONS, "gizmo"};
static const fx_item_t WORKER_PROBLEM_P = {"task:demo-docs-sweep", HELM_KIND_WORKER_PROBLEM, HELM_COLOR_AMBER, "docs-sweep", false, NO_YES, "widget-api"};
static const fx_item_t *const PROJECTS[] = {&DECISION_P, &PR_READY_P, &WORKER_PROBLEM_P, &HERDR_BLOCKED};

static void busy_deck(void)
{
    deck_fresh();
    fx_opts_t o = FX;
    o.chime = true;
    send_model(2, BUSY, 4, o, T);
}

static const char *selected_ref(void)
{
    const helm_item_t *it = helm_deck_selected(&deck);
    return it != NULL ? helm_model_str(helm_deck_model(&deck), it->ref) : NULL;
}

static void test_deck_selection(void)
{
    busy_deck();
    CHECK_STR(selected_ref(), DECISION.ref);
    EVENTS("hello", "select:decision:demo-widget-api:pick-cache");

    helm_deck_knob(&deck, 1, T);
    CHECK_INT(deck.screen, HELM_SCREEN_LIST);
    helm_deck_knob(&deck, 1, T);
    CHECK_STR(selected_ref(), PR_READY.ref);
    helm_deck_knob(&deck, 10, T);
    CHECK_STR(selected_ref(), HERDR_BLOCKED.ref);
    EVENTS("seen", "knob:1", "knob:1", "select:pr:sample-org/gizmo#42", "knob:10", "select:herdr:pane-7");
    helm_deck_knob(&deck, -100, T);
    CHECK_STR(selected_ref(), DECISION.ref);
    helm_deck_knob(&deck, 0, T); /* no turn, no event */
    EVENTS("knob:-100", "select:decision:demo-widget-api:pick-cache");
    /* Turning up from the first row goes back to Home, keeping the selection. */
    CHECK_INT(deck.screen, HELM_SCREEN_LIST);
    helm_deck_knob(&deck, -1, T);
    CHECK_INT(deck.screen, HELM_SCREEN_HOME);
    CHECK_STR(selected_ref(), DECISION.ref);
    EVENTS("knob:-1");

    /* Selection follows the ref across a reorder and clamps to the top on removal. */
    busy_deck();
    helm_deck_knob(&deck, 1, T);
    helm_deck_knob(&deck, 1, T);
    ev_count = 0;
    const fx_item_t *const reordered[] = {&WORKER_PROBLEM, &PR_READY};
    send_model(3, reordered, 2, FX, T);
    CHECK_STR(selected_ref(), PR_READY.ref);
    NO_EVENTS();
    const fx_item_t *const shrunk[] = {&WORKER_PROBLEM};
    send_model(4, shrunk, 1, FX, T);
    CHECK_STR(selected_ref(), WORKER_PROBLEM.ref);
    EVENTS("select:task:demo-docs-sweep");

    /* Full text only after a knob press; an empty model returns home. */
    busy_deck();
    helm_deck_knob(&deck, 1, T);
    helm_deck_knob_press(&deck, false, T);
    CHECK_INT(deck.screen, HELM_SCREEN_DETAIL);
    helm_deck_knob(&deck, 3, T);
    CHECK_INT(deck.detail_scroll, 3);
    helm_deck_clamp_detail_scroll(&deck, 10, 8);
    CHECK_INT(deck.detail_scroll, 2);
    helm_deck_knob(&deck, -9, T);
    CHECK_INT(deck.detail_scroll, 0);
    helm_deck_knob_press(&deck, false, T);
    CHECK_INT(deck.screen, HELM_SCREEN_LIST);
    helm_deck_knob_press(&deck, false, T);
    send_model(5, NULL, 0, FX, T);
    CHECK_INT(deck.screen, HELM_SCREEN_HOME);
    CHECK(helm_deck_selected(&deck) == NULL);
}

static void test_deck_list_window(void)
{
    static const fx_item_t many[10] = {
        {"r0", HELM_KIND_DECISION, HELM_COLOR_RED, "0", false, 0, NULL}, {"r1", HELM_KIND_DECISION, HELM_COLOR_RED, "1", false, 0, NULL},
        {"r2", HELM_KIND_DECISION, HELM_COLOR_RED, "2", false, 0, NULL}, {"r3", HELM_KIND_DECISION, HELM_COLOR_RED, "3", false, 0, NULL},
        {"r4", HELM_KIND_DECISION, HELM_COLOR_RED, "4", false, 0, NULL}, {"r5", HELM_KIND_DECISION, HELM_COLOR_RED, "5", false, 0, NULL},
        {"r6", HELM_KIND_DECISION, HELM_COLOR_RED, "6", false, 0, NULL}, {"r7", HELM_KIND_DECISION, HELM_COLOR_RED, "7", false, 0, NULL},
        {"r8", HELM_KIND_DECISION, HELM_COLOR_RED, "8", false, 0, NULL}, {"r9", HELM_KIND_DECISION, HELM_COLOR_RED, "9", false, 0, NULL},
    };
    const fx_item_t *items[10];
    for (int i = 0; i < 10; i++) {
        items[i] = &many[i];
    }
    deck_fresh();
    send_model(1, items, 10, FX, T);
    helm_deck_knob(&deck, 1, T); /* home -> list */
    CHECK_INT(helm_deck_list_first(&deck, 6), 0);
    helm_deck_knob(&deck, 5, T);
    CHECK_INT(helm_deck_list_first(&deck, 6), 2);
    helm_deck_knob(&deck, 4, T);
    CHECK_INT(helm_deck_list_first(&deck, 6), 4);
}

static void test_deck_hold(void)
{
    /* A full hold sends held and shows the result; the later release sends nothing. */
    busy_deck();
    ev_count = 0;
    helm_deck_key_down(&deck, HELM_ACTION_YES, T);
    CHECK_INT(deck.screen, HELM_SCREEN_CONFIRM);
    helm_deck_tick(&deck, T + 500);
    CHECK_INT(helm_deck_hold_progress_permille(&deck, T + 500), 500);
    CHECK(helm_deck_key_lit(&deck, HELM_ACTION_YES, T + 500));
    CHECK(!helm_deck_key_lit(&deck, HELM_ACTION_LATER, T + 500));
    helm_deck_tick(&deck, T + 999);
    CHECK_INT(deck.screen, HELM_SCREEN_CONFIRM);
    helm_deck_tick(&deck, T + 1000);
    CHECK_INT(deck.screen, HELM_SCREEN_RESULT);
    CHECK(deck.pending);
    CHECK_STR(deck.pending_short_id, "widget-api");
    EVENTS("seen", "key:yes:down:decision:demo-widget-api:pick-cache", "key:yes:held:decision:demo-widget-api:pick-cache");
    helm_deck_key_up(&deck, HELM_ACTION_YES, T + 1100);
    NO_EVENTS();
    CHECK(!helm_deck_key_lit(&deck, HELM_ACTION_YES, T + 1100)); /* dark on the result screen */

    /* Released early: nothing but the up, and the screen it came from. */
    busy_deck();
    helm_deck_knob(&deck, 1, T);
    ev_count = 0;
    helm_deck_key_down(&deck, HELM_ACTION_LATER, T);
    helm_deck_tick(&deck, T + 400);
    helm_deck_key_up(&deck, HELM_ACTION_LATER, T + 500);
    helm_deck_tick(&deck, T + 2000);
    CHECK_INT(deck.screen, HELM_SCREEN_LIST);
    EVENTS("key:later:down:decision:demo-widget-api:pick-cache", "key:later:up:decision:demo-widget-api:pick-cache");

    /* The knob does not move the selection while a key is held. */
    busy_deck();
    helm_deck_key_down(&deck, HELM_ACTION_HOLD, T);
    helm_deck_knob(&deck, 1, T + 100);
    helm_deck_knob_press(&deck, false, T + 200);
    CHECK_INT(deck.screen, HELM_SCREEN_CONFIRM);
    CHECK_STR(selected_ref(), DECISION.ref);

    /* The list changes under the held key; the hold, and the held key's ref, still name the original item. */
    busy_deck();
    helm_deck_key_down(&deck, HELM_ACTION_HOLD, T);
    const fx_item_t *const moved[] = {&PR_READY, &DECISION};
    send_model(3, moved, 2, FX, T + 500);
    ev_count = 0;
    helm_deck_tick(&deck, T + 1000);
    CHECK_STR(deck.pending_short_id, "widget-api");
    EVENTS("key:hold:held:decision:demo-widget-api:pick-cache");

    /* The held item leaves the list: the hold is cancelled, not moved to another item. */
    busy_deck();
    ev_count = 0;
    helm_deck_key_down(&deck, HELM_ACTION_YES, T);
    const fx_item_t *const gone[] = {&PR_READY};
    send_model(3, gone, 1, FX, T + 500);
    helm_deck_tick(&deck, T + 1500);
    CHECK(!deck.pending);
    CHECK_INT(deck.screen, HELM_SCREEN_HOME);
    EVENTS("seen", "key:yes:down:decision:demo-widget-api:pick-cache", "key:yes:up:decision:demo-widget-api:pick-cache", "select:pr:sample-org/gizmo#42");

    /* A dark key does nothing (but still counts as a touch). */
    deck_fresh();
    const fx_item_t *const herdr_only[] = {&HERDR_BLOCKED};
    send_model(1, herdr_only, 1, FX, T);
    ev_count = 0;
    helm_deck_key_down(&deck, HELM_ACTION_YES, T);
    helm_deck_tick(&deck, T + 2000);
    CHECK_INT(deck.screen, HELM_SCREEN_HOME);
    NO_EVENTS();

    /* SHOW ME is a tap. */
    busy_deck();
    ev_count = 0;
    helm_deck_key_down(&deck, HELM_ACTION_FOCUS, T);
    helm_deck_key_up(&deck, HELM_ACTION_FOCUS, T + 100);
    CHECK_INT(deck.screen, HELM_SCREEN_HOME);
    EVENTS("seen", "key:focus:down:decision:demo-widget-api:pick-cache", "key:focus:up:decision:demo-widget-api:pick-cache");
}

static void test_deck_result(void)
{
    busy_deck();
    fx_opts_t old = FX;
    old.chime = true;
    old.has_result = true;
    old.result_state = HELM_RESULT_REPLIED;
    old.result_text = "stale reply";
    send_model(3, BUSY, 4, old, T);
    helm_deck_key_down(&deck, HELM_ACTION_YES, T);
    helm_deck_tick(&deck, T + 1000);
    CHECK(!deck.pending_has_result); /* a result from before the press is not ours */
    fx_opts_t queued = FX;
    queued.has_result = true;
    queued.result_text = "Queued";
    send_model(4, BUSY, 4, queued, T + 1500);
    CHECK(deck.pending_has_result);
    CHECK_INT(deck.pending_state, HELM_RESULT_QUEUED);
    CHECK_STR(deck.pending_text, "Queued");
    fx_opts_t replied = queued;
    replied.result_state = HELM_RESULT_REPLIED;
    replied.result_text = "done";
    send_model(5, BUSY, 4, replied, T + 2000);
    send_model(6, BUSY, 4, FX, T + 4000); /* a later model without a result keeps ours */
    CHECK_STR(deck.pending_text, "done");
    helm_deck_tick(&deck, T + 9999);
    CHECK_INT(deck.screen, HELM_SCREEN_RESULT);
    helm_deck_tick(&deck, T + 10000);
    CHECK_INT(deck.screen, HELM_SCREEN_HOME);
}

static void test_deck_link(void)
{
    /* Unknown before any model. */
    deck_fresh();
    CHECK_INT(helm_deck_link_state(&deck, T), HELM_LINK_WAITING);
    CHECK_INT(helm_deck_attention(&deck, T), HELM_ATTENTION_UNKNOWN);

    /* No model for over 10 s reads unknown and darkens the keys. */
    busy_deck();
    CHECK_INT(helm_deck_attention(&deck, T + 1000), HELM_ATTENTION_NEW);
    CHECK(helm_deck_key_lit(&deck, HELM_ACTION_YES, T + 1000));
    CHECK_INT(helm_deck_link_state(&deck, T + 10000), HELM_LINK_OK);
    CHECK_INT(helm_deck_link_state(&deck, T + 10001), HELM_LINK_SILENT);
    CHECK_INT(helm_deck_attention(&deck, T + 10001), HELM_ATTENTION_UNKNOWN);
    CHECK(!helm_deck_key_lit(&deck, HELM_ACTION_YES, T + 10001));
    /* Latched: a clock that wraps all the way round cannot make it look fresh. */
    helm_deck_tick(&deck, T + 10001);
    CHECK_INT(helm_deck_link_state(&deck, T + 5), HELM_LINK_SILENT);

    /* Firstmate not receiving is unknown. */
    deck_fresh();
    fx_opts_t stale = FX;
    stale.stale = true;
    const fx_item_t *const worker[] = {&WORKER_PROBLEM};
    send_model(3, worker, 1, stale, T);
    CHECK_INT(helm_deck_link_state(&deck, T), HELM_LINK_FIRSTMATE_NOT_LISTENING);
    CHECK_INT(helm_deck_attention(&deck, T), HELM_ATTENTION_UNKNOWN);
    CHECK(!helm_deck_key_lit(&deck, HELM_ACTION_LATER, T));
    CHECK_STR(helm_model_str(helm_deck_model(&deck), helm_deck_model(&deck)->link.stale_reason), "firstmate is not listening");
}

static void test_deck_hello(void)
{
    deck_fresh();
    helm_deck_tick(&deck, T);
    EVENTS("hello");
    helm_deck_tick(&deck, T + 1999);
    NO_EVENTS();
    helm_deck_tick(&deck, T + 2000);
    EVENTS("hello");
    /* The first model is a new session: hello again so that bridge hears it. */
    send_model(1, NULL, 0, FX, T + 2500);
    EVENTS("hello");
    for (uint32_t t = T + 3000; t <= T + 9000; t += 2000) {
        send_model(1 + (t - T - 2500) / 2000 + 1, NULL, 0, FX, t);
        helm_deck_tick(&deck, t + 100);
    }
    NO_EVENTS();
    /* seq going backwards means the bridge restarted. */
    send_model(1, NULL, 0, FX, T + 9500);
    EVENTS("hello", "resync"); /* and the seq gap asks for a resync */
    /* Silence: hello every 2 s once the link times out. */
    helm_deck_tick(&deck, T + 19500);
    NO_EVENTS();
    helm_deck_tick(&deck, T + 19501);
    EVENTS("hello");
    helm_deck_tick(&deck, T + 21501);
    EVENTS("hello");
}

static void test_deck_resync(void)
{
    /* A seq gap sends resync once; another inside 2 s waits for the window. */
    deck_fresh();
    send_model(1, NULL, 0, FX, T);
    ev_count = 0;
    send_model(3, NULL, 0, FX, T + 100);
    EVENTS("resync");
    CHECK_INT(deck.seq_gaps, 1);
    send_model(5, NULL, 0, FX, T + 600);
    NO_EVENTS();
    helm_deck_tick(&deck, T + 2099);
    NO_EVENTS();
    helm_deck_tick(&deck, T + 2100);
    EVENTS("resync");
    helm_deck_tick(&deck, T + 5000);
    NO_EVENTS();
    send_model(6, NULL, 0, FX, T + 5100); /* in order: no resync */
    NO_EVENTS();

    /* A bad CRC sends resync; a resync is not a touch, so no seen goes out. */
    busy_deck();
    ev_count = 0;
    size_t len = fx_build(3, BUSY, 4, FX);
    fx_frame[len - 1] ^= 0x01;
    helm_deck_rx(&deck, fx_frame, len, T + 3000);
    EVENTS("resync");
    CHECK_INT(deck.decoder.corrupt_frames, 1);
    CHECK_INT(helm_deck_model(&deck)->seq, 2);

    /* A partial frame expires after 300 ms of quiet, counts as corrupt, and asks for resync. */
    busy_deck();
    ev_count = 0;
    len = fx_build(3, BUSY, 4, FX);
    helm_deck_rx(&deck, fx_frame, len / 2, T + 3000);
    helm_deck_tick(&deck, T + 3299);
    CHECK(helm_decoder_pending(&deck.decoder));
    NO_EVENTS();
    helm_deck_tick(&deck, T + 3300);
    CHECK(!helm_decoder_pending(&deck.decoder));
    EVENTS("resync");
    /* The next whole frame is read normally (seq 4 after 2 is a gap: resync waits for its window). */
    len = fx_build(4, BUSY, 4, FX);
    helm_deck_rx(&deck, fx_frame, len, T + 3400);
    CHECK_INT(helm_deck_model(&deck)->seq, 4);

    /* A JSON frame that is not a model is counted and changes nothing. */
    busy_deck();
    ev_count = 0;
    uint8_t frame[64];
    size_t fl = helm_frame_encode(1, (const uint8_t *)"{\"t\":\"key\"}", 11, frame, sizeof frame);
    helm_deck_rx(&deck, frame, fl, T + 100);
    CHECK_INT(deck.bad_messages, 1);
    CHECK_INT(deck.last_parse_error, HELM_PARSE_NOT_MODEL);
    CHECK_INT(helm_deck_model(&deck)->seq, 2);
    NO_EVENTS();
}

static void test_deck_chime_and_sweep(void)
{
    busy_deck();
    CHECK(helm_deck_take_chime(&deck));
    CHECK(!helm_deck_take_chime(&deck));
    /* The same seq again (a duplicate) does not chime twice. */
    fx_opts_t chime = FX;
    chime.chime = true;
    send_model(2, BUSY, 4, chime, T + 10);
    CHECK(!helm_deck_take_chime(&deck));
    const fx_item_t *const one[] = {&DECISION};
    send_model(3, one, 1, FX, T + 20); /* a resend without the flag */
    CHECK(!helm_deck_take_chime(&deck));
    helm_deck_knob_press(&deck, true, T + 30);
    CHECK(deck.muted);
    send_model(4, BUSY, 4, chime, T + 40);
    CHECK(!helm_deck_take_chime(&deck));
    helm_deck_knob_press(&deck, true, T + 50);
    send_model(5, BUSY, 4, chime, T + 60);
    CHECK(helm_deck_take_chime(&deck));

    /* Landing starts a two second green sweep. */
    busy_deck();
    fx_opts_t landed = FX;
    landed.landed_today = 4;
    CHECK(!helm_deck_sweeping(&deck, T + 1000));
    send_model(3, NULL, 0, landed, T + 1000);
    CHECK(helm_deck_sweeping(&deck, T + 1000));
    CHECK(helm_deck_sweeping(&deck, T + 2999));
    helm_deck_tick(&deck, T + 3000);
    CHECK(!helm_deck_sweeping(&deck, T + 3000));
}

static void test_deck_seen_once_per_model(void)
{
    busy_deck();
    ev_count = 0;
    helm_deck_knob_press(&deck, true, T);
    helm_deck_knob_press(&deck, true, T);
    EVENTS("seen", "knob_press:1", "knob_press:1");
    send_model(3, BUSY, 4, FX, T + 100);
    helm_deck_knob(&deck, 1, T + 200);
    EVENTS("seen", "knob:1");
    /* Nothing unseen: no seen. */
    const fx_item_t *const seen_only[] = {&WORKER_PROBLEM};
    send_model(4, seen_only, 1, FX, T + 300);
    EVENTS("select:task:demo-docs-sweep");
    helm_deck_knob(&deck, 1, T + 400);
    EVENTS("knob:1");
}

/* ---------------------------------------------------------------- lights */

#define CHECK_RGB(got, r_, g_, b_)                \
    do {                                          \
        helm_rgb_t c_ = (got);                    \
        CHECK_INT(c_.r, r_);                      \
        CHECK_INT(c_.g, g_);                      \
        CHECK_INT(c_.b, b_);                      \
    } while (0)

static helm_lights_t lights;

static void test_lights_calm_and_keys(void)
{
    /* Nothing unseen, usage unknown: the calm bar is only the gauge's dim
     * track, never a full gauge. The keys follow the selected item's actions
     * (a worker problem offers everything but YES). */
    deck_fresh();
    const fx_item_t *const worker[] = {&WORKER_PROBLEM};
    send_model(3, worker, 1, FX, T);
    helm_lights_compute(&deck, T + 10, 255, &lights);
    for (int i = 0; i < HELM_BAR_LIGHTS; i++) {
        CHECK_RGB(lights.bar[i], 7, 7, 7); /* white at 3 % */
    }
    CHECK_RGB(lights.keys[HELM_ACTION_YES], 0, 0, 0);
    CHECK_RGB(lights.keys[HELM_ACTION_LATER], 57, 119, 184); /* blue at 75 % */
    CHECK_RGB(lights.keys[HELM_ACTION_HOLD], 180, 127, 35);  /* amber at 75 % */
    CHECK_RGB(lights.keys[HELM_ACTION_FOCUS], 175, 178, 182);
    CHECK_RGB(lights.knob, 0, 0, 0);

    /* The brightness cap scales everything. */
    helm_lights_compute(&deck, T + 10, 64, &lights);
    CHECK_RGB(lights.bar[0], 2, 2, 2);
    CHECK_RGB(lights.keys[HELM_ACTION_LATER], 14, 30, 46);
    helm_lights_compute(&deck, T + 10, 0, &lights);
    CHECK_RGB(lights.keys[HELM_ACTION_LATER], 0, 0, 0);

    /* While a key is held only that key is lit. */
    busy_deck();
    helm_lights_compute(&deck, T + 10, 255, &lights);
    CHECK_RGB(lights.keys[HELM_ACTION_YES], 50, 146, 80); /* green at 75 % */
    helm_deck_key_down(&deck, HELM_ACTION_HOLD, T + 20);
    helm_lights_compute(&deck, T + 30, 255, &lights);
    CHECK_RGB(lights.keys[HELM_ACTION_YES], 0, 0, 0);
    CHECK_RGB(lights.keys[HELM_ACTION_HOLD], 180, 127, 35);

    /* The calm bar fills with what is left of the tighter window, rounded up. */
    fx_usage = (helm_usage_t){{true, 62}, {true, 3600}, {true, 40}, {true, 86400}};
    deck_fresh();
    send_model(4, worker, 1, FX, T);
    helm_lights_compute(&deck, T + 10, 255, &lights);
    CHECK_INT(helm_lights_gauge(helm_deck_model(&deck)), 4); /* week 40 %: 3.2 lights, so 4 */
    CHECK_RGB(lights.bar[3], 28, 28, 29);                    /* white at 12 % */
    CHECK_RGB(lights.bar[4], 7, 7, 7);
    fx_usage.five_hour_left.value = 100;
    fx_usage.week_left.value = 100;
    send_model(5, worker, 1, FX, T + 20);
    helm_lights_compute(&deck, T + 30, 255, &lights);
    CHECK_RGB(lights.bar[7], 28, 28, 29);
    fx_usage.five_hour_left.value = 1;
    send_model(6, worker, 1, FX, T + 40);
    CHECK_INT(helm_lights_gauge(helm_deck_model(&deck)), 1);
    fx_usage.five_hour_left.value = 0;
    send_model(7, worker, 1, FX, T + 50);
    CHECK_INT(helm_lights_gauge(helm_deck_model(&deck)), 0);
    fx_usage.week_left.known = false; /* one window unknown is unknown */
    send_model(8, worker, 1, FX, T + 60);
    CHECK_INT(helm_lights_gauge(helm_deck_model(&deck)), -1);
    fx_usage = (helm_usage_t){{false, 0}, {false, 0}, {false, 0}, {false, 0}};

    /* An agent near its context limit turns the last calm light amber at 30 %,
     * over the gauge; none near, or an unknown gauge, shows no hint. */
    fx_usage = (helm_usage_t){{true, 100}, {true, 3600}, {true, 100}, {true, 86400}};
    fx_context_near = 2;
    deck_fresh();
    send_model(9, worker, 1, FX, T);
    CHECK(helm_lights_context_hint(helm_deck_model(&deck)));
    helm_lights_compute(&deck, T + 10, 255, &lights);
    CHECK_RGB(lights.bar[6], 28, 28, 29);
    CHECK_RGB(lights.bar[7], 72, 51, 14); /* amber at 30 % */
    fx_context_near = 0;
    send_model(10, worker, 1, FX, T + 20);
    CHECK(!helm_lights_context_hint(helm_deck_model(&deck)));
    helm_lights_compute(&deck, T + 30, 255, &lights);
    CHECK_RGB(lights.bar[7], 28, 28, 29);
    fx_context_near = -1;
    send_model(11, worker, 1, FX, T + 40);
    CHECK(!helm_lights_context_hint(helm_deck_model(&deck)));
    fx_usage = (helm_usage_t){{false, 0}, {false, 0}, {false, 0}, {false, 0}};

    /* Away: YES, LATER, and HOLD go dark even where the item allows them; SHOW ME stays lit. */
    deck_fresh();
    fx_opts_t away = FX;
    away.away = true;
    send_model(1, BUSY, 4, away, T);
    helm_lights_compute(&deck, T + 10, 255, &lights);
    CHECK_RGB(lights.keys[HELM_ACTION_YES], 0, 0, 0);
    CHECK_RGB(lights.keys[HELM_ACTION_LATER], 0, 0, 0);
    CHECK_RGB(lights.keys[HELM_ACTION_HOLD], 0, 0, 0);
    CHECK_RGB(lights.keys[HELM_ACTION_FOCUS], 175, 178, 182);

    /* Muted: the knob glows red. */
    busy_deck();
    helm_deck_knob_press(&deck, true, T + 10);
    helm_lights_compute(&deck, T + 20, 255, &lights);
    CHECK_RGB(lights.knob, 84, 26, 26);
}

static void test_lights_new_pulse(void)
{
    /* Two unseen items (a red decision, a blue PR): one light each, the rest off.
     * T + 800 is a whole number of 1.4 s periods, so the pulse is mid-way (77.5 %). */
    busy_deck();
    helm_lights_compute(&deck, T + 800, 255, &lights);
    CHECK_RGB(lights.bar[0], 185, 58, 58);
    CHECK_RGB(lights.bar[1], 59, 122, 190);
    for (int i = 2; i < HELM_BAR_LIGHTS; i++) {
        CHECK_RGB(lights.bar[i], 0, 0, 0);
    }
    helm_lights_compute(&deck, T + 800 + 350, 255, &lights); /* a quarter period: full */
    CHECK_RGB(lights.bar[0], 0xef, 0x4b, 0x4b);
    helm_lights_compute(&deck, T + 800 + 1050, 255, &lights); /* three quarters: 55 % */
    CHECK_RGB(lights.bar[0], 131, 41, 41);

    /* The pulse keeps its exact phase after weeks of uptime (a float of the
     * seconds since boot would have lost the milliseconds by then). */
    deck_fresh();
    uint32_t big = 4294000000u;
    big -= big % HELM_PULSE_PERIOD_MS;
    send_model(2, BUSY, 4, FX, big);
    helm_lights_compute(&deck, big + 350, 255, &lights);
    CHECK_RGB(lights.bar[0], 0xef, 0x4b, 0x4b);
    helm_lights_compute(&deck, big + 1050, 255, &lights);
    CHECK_RGB(lights.bar[0], 131, 41, 41);

    /* Project tints: widget-api is tint 1 and gizmo tint 3 (sim/render.py
     * project_tint gives the same), so at full pulse each light is its kind's
     * color with 18 % or 54 % white mixed in. */
    CHECK_INT(helm_lights_project_tint(NULL), 0);
    CHECK_INT(helm_lights_project_tint(""), 0);
    CHECK_INT(helm_lights_project_tint("widget-api"), 1);
    CHECK_INT(helm_lights_project_tint("gizmo"), 3);
    CHECK_INT(helm_lights_project_tint("a"), 2);
    deck_fresh();
    send_model(1, PROJECTS, 4, FX, T);
    helm_lights_compute(&deck, T + 800 + 350, 255, &lights);
    CHECK_RGB(lights.bar[0], 0xf2, 0x6b, 0x6b); /* red, tint 1 */
    CHECK_RGB(lights.bar[1], 0xad, 0xd2, 0xfa); /* blue, tint 3 */
    helm_rgb_t amber = {0xf0, 0xa9, 0x2e};
    helm_rgb_t t2 = helm_lights_tint(amber, 2);
    CHECK_RGB(t2, 0xf5, 0xc8, 0x79);
    t2 = helm_lights_tint(amber, 0);
    CHECK_RGB(t2, 0xf0, 0xa9, 0x2e);
    t2 = helm_lights_tint(amber, 9); /* out of range: untinted */
    CHECK_RGB(t2, 0xf0, 0xa9, 0x2e);

    /* More unseen items than lights: the first eight show. */
    deck_fresh();
    const fx_item_t *const many[] = {&DECISION, &DECISION, &DECISION, &DECISION, &DECISION,
                                     &PR_READY, &PR_READY, &PR_READY, &PR_READY, &PR_READY};
    send_model(1, many, 10, FX, T);
    helm_lights_compute(&deck, T + 800 + 350, 255, &lights);
    CHECK_RGB(lights.bar[4], 0xef, 0x4b, 0x4b);
    CHECK_RGB(lights.bar[7], 0x4c, 0x9e, 0xf5);
}

static void test_lights_unknown_and_sweep(void)
{
    /* Before any model, and when firstmate is not listening: all amber, keys dark. */
    deck_fresh();
    helm_lights_compute(&deck, T, 255, &lights);
    for (int i = 0; i < HELM_BAR_LIGHTS; i++) {
        CHECK_RGB(lights.bar[i], 132, 93, 25);
    }
    fx_opts_t stale = FX;
    stale.stale = true;
    const fx_item_t *const worker[] = {&WORKER_PROBLEM};
    send_model(3, worker, 1, stale, T);
    helm_lights_compute(&deck, T + 10, 255, &lights);
    CHECK_RGB(lights.bar[7], 132, 93, 25);
    for (int k = 0; k < HELM_ACTION_COUNT; k++) {
        CHECK_RGB(lights.keys[k], 0, 0, 0);
    }
    /* Silent for over 10 s is unknown too. */
    busy_deck();
    helm_lights_compute(&deck, T + 10001, 255, &lights);
    CHECK_RGB(lights.bar[0], 132, 93, 25);

    /* Something landed: a green head runs along the bar for 2 s, ahead of
     * the unseen pulse. T + 100 is a whole number of 1.1 s sweeps: head on light 0. */
    busy_deck();
    fx_opts_t landed = FX;
    landed.landed_today = 4;
    send_model(3, BUSY, 4, landed, T);
    helm_lights_compute(&deck, T + 100, 255, &lights);
    CHECK_RGB(lights.bar[0], 0x43, 0xc2, 0x6b);
    CHECK_RGB(lights.bar[1], 40, 116, 64); /* 1 light away: 60 % */
    CHECK_RGB(lights.bar[2], 13, 39, 21);  /* 2 away: 20 % */
    CHECK_RGB(lights.bar[3], 0, 0, 0);
    helm_lights_compute(&deck, T + 100 + 500, 255, &lights); /* head on light 5 */
    CHECK_RGB(lights.bar[5], 0x43, 0xc2, 0x6b);
    CHECK_RGB(lights.bar[0], 0, 0, 0);
    helm_deck_tick(&deck, T + 2000);
    helm_lights_compute(&deck, T + 2000, 255, &lights); /* sweep over: the pulse again */
    CHECK_RGB(lights.bar[2], 0, 0, 0);
    CHECK(lights.bar[0].r > 0 && lights.bar[0].g < lights.bar[0].r);
}

/* ---------------------------------------------------------------- controls */

static void test_debounce(void)
{
    helm_debounce_t d = {0};
    uint32_t t = 0xFFFFFFF0u; /* across the clock wrap */
    CHECK(!helm_debounce(&d, true, t, 20));
    CHECK(!helm_debounce(&d, false, t + 5, 20)); /* bounce */
    CHECK(!helm_debounce(&d, true, t + 8, 20));
    CHECK(!helm_debounce(&d, true, t + 27, 20));
    CHECK(helm_debounce(&d, true, t + 28, 20)); /* held 20 ms since the last change */
    CHECK(d.down);
    CHECK(!helm_debounce(&d, true, t + 100, 20)); /* no repeat */
    CHECK(!helm_debounce(&d, false, t + 200, 20));
    CHECK(!helm_debounce(&d, false, t + 219, 20));
    CHECK(helm_debounce(&d, false, t + 220, 20));
    CHECK(!d.down);
    /* A blip shorter than the settle time never shows. */
    CHECK(!helm_debounce(&d, true, t + 300, 20));
    CHECK(!helm_debounce(&d, false, t + 310, 20));
    CHECK(!helm_debounce(&d, false, t + 400, 20));
    CHECK(!d.down);
}

static void test_button(void)
{
    helm_button_t b = {0};
    /* Short: released before the long press time. */
    CHECK_INT(helm_button(&b, true, 1000, 10, 800), HELM_PRESS_NONE);
    CHECK_INT(helm_button(&b, true, 1010, 10, 800), HELM_PRESS_NONE); /* pressed */
    CHECK_INT(helm_button(&b, true, 1500, 10, 800), HELM_PRESS_NONE);
    CHECK_INT(helm_button(&b, false, 1600, 10, 800), HELM_PRESS_NONE);
    CHECK_INT(helm_button(&b, false, 1610, 10, 800), HELM_PRESS_SHORT);
    CHECK_INT(helm_button(&b, false, 1700, 10, 800), HELM_PRESS_NONE);

    /* Long: reported once, at 800 ms, while still held; the release is quiet. */
    CHECK_INT(helm_button(&b, true, 2000, 10, 800), HELM_PRESS_NONE);
    CHECK_INT(helm_button(&b, true, 2010, 10, 800), HELM_PRESS_NONE);
    CHECK_INT(helm_button(&b, true, 2809, 10, 800), HELM_PRESS_NONE);
    CHECK_INT(helm_button(&b, true, 2810, 10, 800), HELM_PRESS_LONG);
    CHECK_INT(helm_button(&b, true, 4000, 10, 800), HELM_PRESS_NONE);
    CHECK_INT(helm_button(&b, false, 4100, 10, 800), HELM_PRESS_NONE);
    CHECK_INT(helm_button(&b, false, 4110, 10, 800), HELM_PRESS_NONE);
    /* And the next short press still works. */
    CHECK_INT(helm_button(&b, true, 5000, 10, 800), HELM_PRESS_NONE);
    CHECK_INT(helm_button(&b, true, 5010, 10, 800), HELM_PRESS_NONE);
    CHECK_INT(helm_button(&b, false, 5100, 10, 800), HELM_PRESS_NONE);
    CHECK_INT(helm_button(&b, false, 5110, 10, 800), HELM_PRESS_SHORT);
}

/* ---------------------------------------------------------------- knob */

/* A seesaw encoder on the bus: answers register reads the way the PID 4991
 * firmware would, and logs every write. */
typedef struct {
    bool present;
    uint8_t hw_id;
    uint32_t version;
    int32_t delta; /* cleared by a read, as the firmware does */
    uint32_t gpio;
    uint8_t base, reg; /* the register the last 2-byte write pointed at */
    bool delayed;      /* delay_us(>= 250) since that write */
    int early_reads;   /* reads that did not wait for the seesaw */
    int writes;
    uint8_t log[32][8];
    size_t log_len[32];
} fake_seesaw_t;

static bool fake_write(void *ctx, const uint8_t *data, size_t len)
{
    fake_seesaw_t *f = ctx;
    if (!f->present) {
        return false;
    }
    memcpy(f->log[f->writes % 32], data, len < 8 ? len : 8); /* the last 32 writes */
    f->log_len[f->writes % 32] = len;
    f->writes++;
    if (len == 2) {
        f->base = data[0];
        f->reg = data[1];
        f->delayed = false;
    }
    return true;
}

static void put_u32(uint8_t *out, uint32_t v)
{
    out[0] = (uint8_t)(v >> 24);
    out[1] = (uint8_t)(v >> 16);
    out[2] = (uint8_t)(v >> 8);
    out[3] = (uint8_t)v;
}

static bool fake_read(void *ctx, uint8_t *data, size_t len)
{
    fake_seesaw_t *f = ctx;
    if (!f->present) {
        return false;
    }
    if (!f->delayed) {
        f->early_reads++;
    }
    uint8_t reply[4] = {0};
    if (f->base == HELM_SEESAW_STATUS_BASE && f->reg == HELM_SEESAW_STATUS_HW_ID) {
        reply[0] = f->hw_id;
    } else if (f->base == HELM_SEESAW_STATUS_BASE && f->reg == HELM_SEESAW_STATUS_VERSION) {
        put_u32(reply, f->version);
    } else if (f->base == HELM_SEESAW_ENCODER_BASE && f->reg == HELM_SEESAW_ENCODER_DELTA) {
        put_u32(reply, (uint32_t)f->delta);
        f->delta = 0;
    } else if (f->base == HELM_SEESAW_GPIO_BASE && f->reg == HELM_SEESAW_GPIO_BULK) {
        put_u32(reply, f->gpio);
    }
    memcpy(data, reply, len < 4 ? len : 4);
    return true;
}

static int probes;

static bool fake_probe(void *ctx)
{
    probes++;
    return ((fake_seesaw_t *)ctx)->present;
}

static void fake_delay(void *ctx, uint32_t us)
{
    fake_seesaw_t *f = ctx;
    if (us >= HELM_SEESAW_READ_DELAY_US) {
        f->delayed = true;
    }
}

static bool logged(const fake_seesaw_t *f, const uint8_t *want, size_t len)
{
    for (int i = 0; i < f->writes && i < 32; i++) { /* the last 32 writes */
        if (f->log_len[i] == len && memcmp(f->log[i], want, len) == 0) {
            return true;
        }
    }
    return false;
}

#define SWITCH_UP (1u << 24) /* pulled up: not pressed */

static fake_seesaw_t ss;
static helm_knob_t knob;

static void knob_fresh(bool present)
{
    memset(&ss, 0, sizeof ss);
    ss.present = present;
    ss.hw_id = 0x87; /* ATtiny817 */
    ss.version = ((uint32_t)HELM_KNOB_PRODUCT << 16) | 0x1234u;
    ss.gpio = SWITCH_UP;
    const helm_seesaw_bus_t bus = {fake_probe, fake_write, fake_read, fake_delay, &ss};
    helm_knob_init(&knob, &bus, 800);
    probes = 0;
}

static void test_knob_parse(void)
{
    const uint8_t neg3[4] = {0xFF, 0xFF, 0xFF, 0xFD};
    CHECK_INT((int32_t)helm_seesaw_u32(neg3), -3);
    const uint8_t version[4] = {0x13, 0x7F, 0x12, 0x34};
    CHECK_INT(helm_seesaw_u32(version) >> 16, 4991);
    CHECK(helm_seesaw_hw_id_known(0x87));
    CHECK(helm_seesaw_hw_id_known(0x55));
    CHECK(!helm_seesaw_hw_id_known(0x00));
    CHECK(!helm_seesaw_hw_id_known(0xFF));
}

static void test_knob_absent_then_found(void)
{
    knob_fresh(false);
    helm_knob_input_t in = helm_knob_poll(&knob, T);
    CHECK_INT(in.change, HELM_KNOB_ABSENT);
    /* Not looked for again until the retry time, and not reported twice. */
    CHECK_INT(helm_knob_poll(&knob, T + 1999).change, HELM_KNOB_NO_CHANGE);
    CHECK_INT(helm_knob_poll(&knob, T + 2000).change, HELM_KNOB_NO_CHANGE);
    CHECK(!knob.ready);
    CHECK_INT(probes, 2); /* one quiet probe per look */

    /* Without a probe hook, the first register write is the look. */
    const helm_seesaw_bus_t no_probe = {NULL, fake_write, fake_read, fake_delay, &ss};
    helm_knob_t bare;
    helm_knob_init(&bare, &no_probe, 800);
    CHECK_INT(helm_knob_poll(&bare, T).change, HELM_KNOB_ABSENT);
    ss.present = true;
    CHECK_INT(helm_knob_poll(&bare, T + 2000).change, HELM_KNOB_FOUND);
    ss.present = false;
    ss.writes = 0;

    /* Plugged in: found at the next look, and set up as the Adafruit library does. */
    ss.present = true;
    ss.delta = 5; /* turned before it was found: dropped */
    CHECK_INT(helm_knob_poll(&knob, T + 3000).change, HELM_KNOB_NO_CHANGE); /* not due yet */
    CHECK_INT(ss.writes, 0);
    in = helm_knob_poll(&knob, T + 4000);
    CHECK_INT(in.change, HELM_KNOB_FOUND);
    CHECK(knob.ready);
    CHECK_INT(knob.hw_id, 0x87);
    CHECK_INT(knob.product, 4991);
    const uint8_t dirclr[6] = {0x01, 0x03, 0x01, 0x00, 0x00, 0x00};
    const uint8_t pullen[6] = {0x01, 0x0B, 0x01, 0x00, 0x00, 0x00};
    const uint8_t pullup[6] = {0x01, 0x05, 0x01, 0x00, 0x00, 0x00};
    const uint8_t pixel_pin[3] = {0x0E, 0x01, 0x06};
    const uint8_t pixel_len[4] = {0x0E, 0x03, 0x00, 0x03};
    CHECK(logged(&ss, dirclr, 6));
    CHECK(logged(&ss, pullen, 6));
    CHECK(logged(&ss, pullup, 6));
    CHECK(logged(&ss, pixel_pin, 3));
    CHECK(logged(&ss, pixel_len, 4));
    in = helm_knob_poll(&knob, T + 4010);
    CHECK_INT(in.change, HELM_KNOB_NO_CHANGE);
    CHECK_INT(in.delta, 0);
    CHECK_INT(ss.early_reads, 0);

    /* Something else at the address: reported once, never used. */
    knob_fresh(true);
    ss.hw_id = 0x12;
    CHECK_INT(helm_knob_poll(&knob, T).change, HELM_KNOB_NOT_SEESAW);
    CHECK_INT(helm_knob_poll(&knob, T + 2000).change, HELM_KNOB_NO_CHANGE);
    CHECK(!knob.ready);
}

static void test_knob_turn_press_light(void)
{
    knob_fresh(true);
    CHECK_INT(helm_knob_poll(&knob, T).change, HELM_KNOB_FOUND);
    ss.delta = -3;
    helm_knob_input_t in = helm_knob_poll(&knob, T + 10);
    CHECK_INT(in.delta, -3);
    CHECK_INT(helm_knob_poll(&knob, T + 20).delta, 0); /* the read cleared it */
    ss.delta = 2;
    CHECK_INT(helm_knob_poll(&knob, T + 30).delta, 2);

    /* Push: short on release, long at 800 ms while held. */
    ss.gpio = 0;
    CHECK_INT(helm_knob_poll(&knob, T + 100).press, HELM_PRESS_NONE);
    CHECK_INT(helm_knob_poll(&knob, T + 110).press, HELM_PRESS_NONE);
    ss.gpio = SWITCH_UP;
    CHECK_INT(helm_knob_poll(&knob, T + 300).press, HELM_PRESS_NONE);
    CHECK_INT(helm_knob_poll(&knob, T + 310).press, HELM_PRESS_SHORT);
    ss.gpio = 0;
    helm_knob_poll(&knob, T + 400);
    helm_knob_poll(&knob, T + 410);
    CHECK_INT(helm_knob_poll(&knob, T + 1209).press, HELM_PRESS_NONE);
    CHECK_INT(helm_knob_poll(&knob, T + 1210).press, HELM_PRESS_LONG);
    ss.gpio = SWITCH_UP;
    helm_knob_poll(&knob, T + 1300);
    CHECK_INT(helm_knob_poll(&knob, T + 1310).press, HELM_PRESS_NONE);

    /* The NeoPixel: G, R, B after a zero offset, then SHOW; only on change. */
    int before = ss.writes;
    helm_knob_set_light(&knob, (helm_rgb_t){84, 26, 10});
    const uint8_t buf[7] = {0x0E, 0x04, 0x00, 0x00, 26, 84, 10};
    const uint8_t show[2] = {0x0E, 0x05};
    CHECK(logged(&ss, buf, 7));
    CHECK(logged(&ss, show, 2));
    CHECK_INT(ss.writes, before + 2);
    helm_knob_set_light(&knob, (helm_rgb_t){84, 26, 10});
    CHECK_INT(ss.writes, before + 2);
    helm_knob_set_light(&knob, (helm_rgb_t){0, 0, 0});
    CHECK_INT(ss.writes, before + 4);
    CHECK_INT(ss.early_reads, 0);
}

static void test_knob_lost_and_back(void)
{
    knob_fresh(true);
    CHECK_INT(helm_knob_poll(&knob, T).change, HELM_KNOB_FOUND);
    helm_knob_set_light(&knob, (helm_rgb_t){1, 2, 3});
    ss.present = false; /* unplugged */
    CHECK_INT(helm_knob_poll(&knob, T + 10).change, HELM_KNOB_NO_CHANGE);
    CHECK_INT(helm_knob_poll(&knob, T + 20).change, HELM_KNOB_NO_CHANGE);
    CHECK_INT(helm_knob_poll(&knob, T + 30).change, HELM_KNOB_LOST);
    CHECK(!knob.ready);
    helm_knob_set_light(&knob, (helm_rgb_t){4, 5, 6}); /* ignored while gone */
    CHECK_INT(helm_knob_poll(&knob, T + 2030).change, HELM_KNOB_NO_CHANGE); /* still gone, quiet */
    /* One failed poll among good ones is not a loss. */
    ss.present = true;
    CHECK_INT(helm_knob_poll(&knob, T + 4030).change, HELM_KNOB_FOUND);
    ss.present = false;
    CHECK_INT(helm_knob_poll(&knob, T + 4040).change, HELM_KNOB_NO_CHANGE);
    ss.present = true;
    CHECK_INT(helm_knob_poll(&knob, T + 4050).change, HELM_KNOB_NO_CHANGE);
    CHECK(knob.ready);
    /* Found again, the light is written afresh even if the color is the same. */
    int before = ss.writes;
    helm_knob_set_light(&knob, (helm_rgb_t){1, 2, 3});
    CHECK_INT(ss.writes, before + 2);
}

/* ---------------------------------------------------------------- tone */

static int16_t tone_buf[8000];

static void test_tone(void)
{
    size_t n = helm_tone(tone_buf, sizeof tone_buf / sizeof tone_buf[0], 22050, 1320, 120, 12000);
    CHECK_INT(n, 2646);
    CHECK_INT(helm_tone_samples(22050, 120), 2646);
    CHECK_INT(tone_buf[0], 0);
    int peak = 0, crossings = 0;
    for (size_t i = 0; i < n; i++) {
        int v = tone_buf[i] < 0 ? -tone_buf[i] : tone_buf[i];
        peak = v > peak ? v : peak;
        if (i > 0 && (tone_buf[i - 1] < 0) != (tone_buf[i] < 0)) {
            crossings++;
        }
    }
    CHECK(peak <= 12000 && peak > 11000);
    /* 1320 Hz for 120 ms: about 158 cycles, two crossings each. */
    CHECK(crossings >= 2 * 158 - 4 && crossings <= 2 * 158 + 4);
    /* It ends near silence: no click. */
    CHECK(tone_buf[n - 1] > -60 && tone_buf[n - 1] < 60);
    /* The rise takes 3 ms: early samples stay small. */
    CHECK(tone_buf[5] > -2000 && tone_buf[5] < 2000);
    /* The buffer bound holds. */
    CHECK_INT(helm_tone(tone_buf, 100, 22050, 1320, 120, 12000), 100);
}


static void test_deck_views(void)
{
    deck_fresh();
    send_model(5, PROJECTS, 4, FX, T);
    ev_count = 0;
    CHECK(helm_deck_has_views(&deck));
    CHECK(helm_deck_view(&deck) == NULL);
    CHECK_INT(helm_deck_view_count(&deck), 4);

    /* On Home the knob turns through all, gizmo, widget-api (byte order), and back to all. */
    helm_deck_knob(&deck, 1, T);
    CHECK_INT(deck.screen, HELM_SCREEN_HOME);
    CHECK_STR(helm_deck_view(&deck), "gizmo");
    CHECK_INT(helm_deck_view_count(&deck), 1);
    CHECK_STR(selected_ref(), PR_READY_P.ref);
    helm_deck_knob(&deck, 1, T);
    CHECK_STR(helm_deck_view(&deck), "widget-api");
    CHECK_STR(selected_ref(), DECISION_P.ref);
    helm_deck_knob(&deck, 1, T);
    CHECK(helm_deck_view(&deck) == NULL);
    helm_deck_knob(&deck, -1, T);
    CHECK_STR(helm_deck_view(&deck), "widget-api");
    EVENTS("seen", "knob:1", "select:pr:sample-org/gizmo#42", "knob:1", "select:decision:demo-widget-api:pick-cache",
           "knob:1", "knob:-1");
    helm_deck_knob(&deck, 5, T); /* five steps over three views is two */
    CHECK_STR(helm_deck_view(&deck), "gizmo");
    helm_deck_knob(&deck, 1, T);
    ev_count = 0;

    /* The list holds only the view; turning up from its first row goes Home. */
    helm_deck_knob_press(&deck, false, T);
    CHECK_INT(deck.screen, HELM_SCREEN_LIST);
    CHECK_INT(helm_deck_view_item(&deck, 0), 0);
    CHECK_INT(helm_deck_view_item(&deck, 1), 2);
    CHECK_INT(helm_deck_view_item(&deck, 2), -1);
    CHECK_INT(helm_deck_view_pos(&deck, 2), 1);
    CHECK_INT(helm_deck_view_pos(&deck, 1), -1);
    helm_deck_knob(&deck, 5, T);
    CHECK_STR(selected_ref(), WORKER_PROBLEM_P.ref);
    CHECK_INT(helm_deck_list_first(&deck, 6), 0);
    helm_deck_knob(&deck, -1, T);
    CHECK_STR(selected_ref(), DECISION_P.ref);
    helm_deck_knob(&deck, -1, T);
    CHECK_INT(deck.screen, HELM_SCREEN_HOME);
    EVENTS("knob_press:0", "knob:5", "select:task:demo-docs-sweep", "knob:-1", "select:decision:demo-widget-api:pick-cache",
           "knob:-1");

    /* Selection follows the ref within the view; a view whose project leaves goes back to all. */
    const fx_item_t *const reordered[] = {&HERDR_BLOCKED, &WORKER_PROBLEM_P, &PR_READY_P, &DECISION_P};
    send_model(6, reordered, 4, FX, T);
    CHECK_STR(selected_ref(), DECISION_P.ref);
    CHECK_INT(helm_deck_view_pos(&deck, deck.selected), 1);
    NO_EVENTS();
    const fx_item_t *const no_widget[] = {&PR_READY_P, &HERDR_BLOCKED};
    deck.screen = HELM_SCREEN_LIST;
    send_model(7, no_widget, 2, FX, T);
    CHECK(helm_deck_view(&deck) == NULL);
    CHECK_STR(selected_ref(), PR_READY_P.ref);
    CHECK_INT(deck.screen, HELM_SCREEN_LIST);
    EVENTS("select:pr:sample-org/gizmo#42");

    /* Without projects there is only "all", and a turn on Home opens the list as before. */
    busy_deck();
    CHECK(!helm_deck_has_views(&deck));
    helm_deck_knob(&deck, 1, T);
    CHECK_INT(deck.screen, HELM_SCREEN_LIST);
}

static void test_deck_away(void)
{
    deck_fresh();
    fx_opts_t away = FX;
    away.away = true;
    away.chime = true;
    send_model(1, PROJECTS, 4, away, T);
    CHECK_INT(helm_deck_link_state(&deck, T), HELM_LINK_OK); /* away is not a link problem */
    CHECK(!helm_deck_take_chime(&deck));                     /* chimes muted */
    CHECK(!helm_deck_key_lit(&deck, HELM_ACTION_YES, T));    /* the item allows YES; away locks it */
    CHECK(!helm_deck_key_lit(&deck, HELM_ACTION_LATER, T));
    CHECK(!helm_deck_key_lit(&deck, HELM_ACTION_HOLD, T));
    CHECK(helm_deck_key_lit(&deck, HELM_ACTION_FOCUS, T)); /* SHOW ME still works */
    ev_count = 0;
    helm_deck_key_down(&deck, HELM_ACTION_YES, T);
    CHECK_INT(deck.screen, HELM_SCREEN_HOME);
    CHECK(!deck.holding);
    helm_deck_key_down(&deck, HELM_ACTION_FOCUS, T);
    helm_deck_key_up(&deck, HELM_ACTION_FOCUS, T);
    EVENTS("seen", "key:focus:down:decision:demo-widget-api:pick-cache", "key:focus:up:decision:demo-widget-api:pick-cache");

    /* Firstmate going away mid-hold cancels the hold. */
    deck_fresh();
    send_model(1, PROJECTS, 4, FX, T);
    helm_deck_key_down(&deck, HELM_ACTION_YES, T);
    CHECK(deck.holding);
    ev_count = 0;
    away.chime = false;
    send_model(2, PROJECTS, 4, away, T + 500);
    CHECK(!deck.holding);
    CHECK_INT(deck.screen, HELM_SCREEN_HOME);
    EVENTS("key:yes:up:decision:demo-widget-api:pick-cache");
    helm_deck_tick(&deck, T + 1500);
    CHECK(!deck.pending);
}

static void test_deck_mac_locked(void)
{
    deck_fresh();
    fx_opts_t locked = FX;
    locked.mac_locked = true;
    locked.chime = true;
    send_model(1, PROJECTS, 4, locked, T);
    CHECK_INT(helm_deck_link_state(&deck, T), HELM_LINK_OK); /* a locked Mac is not a link problem */
    CHECK(helm_deck_take_chime(&deck));                      /* the chime still rings */
    for (int k = 0; k < HELM_ACTION_COUNT; k++) {
        CHECK(!helm_deck_key_lit(&deck, (helm_action_t)k, T)); /* every key locked, SHOW ME too */
    }
    ev_count = 0;
    helm_deck_key_down(&deck, HELM_ACTION_YES, T);
    CHECK(!deck.holding);
    helm_deck_key_down(&deck, HELM_ACTION_FOCUS, T);
    helm_deck_key_up(&deck, HELM_ACTION_FOCUS, T);
    EVENTS("seen");
    helm_lights_compute(&deck, T + 10, 255, &lights);
    CHECK_RGB(lights.keys[HELM_ACTION_FOCUS], 0, 0, 0);

    /* The Mac locking mid-hold cancels the hold; unlocking lights the keys again. */
    deck_fresh();
    send_model(1, PROJECTS, 4, FX, T);
    helm_deck_key_down(&deck, HELM_ACTION_YES, T);
    CHECK(deck.holding);
    ev_count = 0;
    locked.chime = false;
    send_model(2, PROJECTS, 4, locked, T + 500);
    CHECK(!deck.holding);
    CHECK_INT(deck.screen, HELM_SCREEN_HOME);
    EVENTS("key:yes:up:decision:demo-widget-api:pick-cache");
    helm_deck_tick(&deck, T + 1500);
    CHECK(!deck.pending);
    send_model(3, PROJECTS, 4, FX, T + 2000);
    CHECK(helm_deck_key_lit(&deck, HELM_ACTION_YES, T + 2000));
}

int main(int argc, char **argv)
{
    if (argc != 2) {
        fprintf(stderr, "usage: test_core <tests/vectors/cable_frame.txt>\n");
        return 2;
    }
    test_crc();
    test_vectors(argv[1]);
    test_encode_limits();
    test_round_trip_random();
    test_bit_flips();
    test_truncated_expires();
    test_garbage_between_frames();
    test_buffer_bound();
    test_model_parse_full();
    test_model_parse_new_fields();
    test_model_strings();
    test_model_errors();
    test_model_pool_holds_a_full_frame();
    test_events();
    test_deck_selection();
    test_deck_list_window();
    test_deck_hold();
    test_deck_result();
    test_deck_link();
    test_deck_hello();
    test_deck_resync();
    test_deck_chime_and_sweep();
    test_deck_seen_once_per_model();
    test_lights_calm_and_keys();
    test_lights_new_pulse();
    test_lights_unknown_and_sweep();
    test_debounce();
    test_button();
    test_knob_parse();
    test_knob_absent_then_found();
    test_knob_turn_press_light();
    test_knob_lost_and_back();
    test_tone();
    test_deck_views();
    test_deck_away();
    test_deck_mac_locked();
    printf("test_core: %d checks, %d failures\n", checks, failures);
    return failures == 0 ? 0 : 1;
}
