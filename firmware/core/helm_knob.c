#include "helm_knob.h"

#include <string.h>

#define SWITCH_MASK (1u << HELM_KNOB_SWITCH_PIN)

uint32_t helm_seesaw_u32(const uint8_t b[4])
{
    return ((uint32_t)b[0] << 24) | ((uint32_t)b[1] << 16) | ((uint32_t)b[2] << 8) | (uint32_t)b[3];
}

/* The hardware ids Adafruit_seesaw::begin() accepts (Adafruit_seesaw.h). */
bool helm_seesaw_hw_id_known(uint8_t hw_id)
{
    static const uint8_t KNOWN[] = {
        0x55,                                     /* SAMD09 */
        0x46,                                     /* ATtiny416 */
        0x84, 0x85, 0x86, 0x87, 0x88, 0x89,       /* ATtiny806, 807, 816, 817, 1616, 1617 */
        0x90, 0x91, 0x92, 0x93,                   /* STM32C011, C031, C051, G071 */
    };
    for (size_t i = 0; i < sizeof KNOWN; i++) {
        if (KNOWN[i] == hw_id) {
            return true;
        }
    }
    return false;
}

static bool ss_write(helm_knob_t *knob, const uint8_t *data, size_t len)
{
    return knob->bus.write(knob->bus.ctx, data, len);
}

static bool ss_read(helm_knob_t *knob, uint8_t base, uint8_t reg, uint8_t *out, size_t len)
{
    const uint8_t cmd[2] = {base, reg};
    if (!ss_write(knob, cmd, sizeof cmd)) {
        return false;
    }
    knob->bus.delay_us(knob->bus.ctx, HELM_SEESAW_READ_DELAY_US);
    return knob->bus.read(knob->bus.ctx, out, len);
}

static bool ss_write_u32(helm_knob_t *knob, uint8_t base, uint8_t reg, uint32_t value)
{
    const uint8_t cmd[6] = {base, reg, (uint8_t)(value >> 24), (uint8_t)(value >> 16), (uint8_t)(value >> 8),
                            (uint8_t)value};
    return ss_write(knob, cmd, sizeof cmd);
}

static bool ss_write_u8(helm_knob_t *knob, uint8_t base, uint8_t reg, uint8_t value)
{
    const uint8_t cmd[3] = {base, reg, value};
    return ss_write(knob, cmd, sizeof cmd);
}

static helm_knob_change_t report(helm_knob_t *knob, helm_knob_change_t change)
{
    if ((int)change == knob->reported) {
        return HELM_KNOB_NO_CHANGE;
    }
    knob->reported = (int)change;
    return change;
}

/* Identify the seesaw and set up the push switch and NeoPixel, as
 * Adafruit_seesaw::begin(), pinMode(INPUT_PULLUP) and seesaw_NeoPixel::begin() do. */
static helm_knob_change_t probe(helm_knob_t *knob, uint32_t now_ms)
{
    knob->waiting = true;
    knob->next_probe_ms = now_ms + HELM_KNOB_RETRY_MS;

    uint8_t id = 0;
    bool answers = knob->bus.probe == NULL || knob->bus.probe(knob->bus.ctx);
    if (!answers || !ss_read(knob, HELM_SEESAW_STATUS_BASE, HELM_SEESAW_STATUS_HW_ID, &id, 1)) {
        /* Silent after a loss: LOST already said it is gone. */
        return knob->reported == HELM_KNOB_NO_CHANGE ? report(knob, HELM_KNOB_ABSENT) : HELM_KNOB_NO_CHANGE;
    }
    if (!helm_seesaw_hw_id_known(id)) {
        knob->hw_id = id;
        return report(knob, HELM_KNOB_NOT_SEESAW);
    }
    uint8_t version[4];
    static const uint8_t pixel_len[4] = {HELM_SEESAW_NEOPIXEL_BASE, HELM_SEESAW_NEOPIXEL_BUF_LENGTH, 0, 3};
    uint8_t delta[4];
    bool ok = ss_read(knob, HELM_SEESAW_STATUS_BASE, HELM_SEESAW_STATUS_VERSION, version, sizeof version) &&
              ss_write_u32(knob, HELM_SEESAW_GPIO_BASE, HELM_SEESAW_GPIO_DIRCLR_BULK, SWITCH_MASK) &&
              ss_write_u32(knob, HELM_SEESAW_GPIO_BASE, HELM_SEESAW_GPIO_PULLENSET, SWITCH_MASK) &&
              ss_write_u32(knob, HELM_SEESAW_GPIO_BASE, HELM_SEESAW_GPIO_BULK_SET, SWITCH_MASK) &&
              ss_write_u8(knob, HELM_SEESAW_NEOPIXEL_BASE, HELM_SEESAW_NEOPIXEL_SPEED, 1) && /* 800 kHz */
              ss_write_u8(knob, HELM_SEESAW_NEOPIXEL_BASE, HELM_SEESAW_NEOPIXEL_PIN, HELM_KNOB_PIXEL_PIN) &&
              ss_write(knob, pixel_len, sizeof pixel_len) && /* one RGB pixel, 3 bytes */
              /* Drop any turn counted before now. */
              ss_read(knob, HELM_SEESAW_ENCODER_BASE, HELM_SEESAW_ENCODER_DELTA, delta, sizeof delta);
    if (!ok) {
        return HELM_KNOB_NO_CHANGE; /* answered, then failed partway: try again later */
    }
    knob->hw_id = id;
    knob->product = (uint16_t)(helm_seesaw_u32(version) >> 16);
    knob->ready = true;
    knob->waiting = false;
    knob->fails = 0;
    memset(&knob->button, 0, sizeof knob->button);
    knob->light_written = false;
    return report(knob, HELM_KNOB_FOUND);
}

void helm_knob_init(helm_knob_t *knob, const helm_seesaw_bus_t *bus, uint32_t long_ms)
{
    memset(knob, 0, sizeof *knob);
    knob->bus = *bus;
    knob->long_ms = long_ms;
    knob->reported = HELM_KNOB_NO_CHANGE;
}

helm_knob_input_t helm_knob_poll(helm_knob_t *knob, uint32_t now_ms)
{
    helm_knob_input_t in = {HELM_KNOB_NO_CHANGE, 0, HELM_PRESS_NONE};
    if (!knob->ready) {
        if (!knob->waiting || (int32_t)(now_ms - knob->next_probe_ms) >= 0) {
            in.change = probe(knob, now_ms);
        }
        return in;
    }
    uint8_t b[4];
    bool ok = ss_read(knob, HELM_SEESAW_ENCODER_BASE, HELM_SEESAW_ENCODER_DELTA, b, sizeof b);
    if (ok) {
        in.delta = (int32_t)helm_seesaw_u32(b);
        ok = ss_read(knob, HELM_SEESAW_GPIO_BASE, HELM_SEESAW_GPIO_BULK, b, sizeof b);
    }
    if (!ok) {
        if (++knob->fails >= HELM_KNOB_MAX_FAILS) {
            knob->ready = false;
            knob->waiting = true;
            knob->next_probe_ms = now_ms + HELM_KNOB_RETRY_MS;
            in.change = report(knob, HELM_KNOB_LOST);
        }
        return in;
    }
    knob->fails = 0;
    bool pressed = (helm_seesaw_u32(b) & SWITCH_MASK) == 0; /* pulled up; pressed reads low */
    in.press = helm_button(&knob->button, pressed, now_ms, HELM_KNOB_SETTLE_MS, knob->long_ms);
    return in;
}

void helm_knob_set_light(helm_knob_t *knob, helm_rgb_t color)
{
    if (!knob->ready ||
        (knob->light_written && memcmp(&knob->light, &color, sizeof color) == 0)) {
        return;
    }
    /* BUF: a 16-bit start offset, then the pixel in the NeoPixel's G, R, B order. */
    const uint8_t buf[7] = {HELM_SEESAW_NEOPIXEL_BASE, HELM_SEESAW_NEOPIXEL_BUF, 0, 0, color.g, color.r, color.b};
    const uint8_t show[2] = {HELM_SEESAW_NEOPIXEL_BASE, HELM_SEESAW_NEOPIXEL_SHOW};
    knob->light_written = ss_write(knob, buf, sizeof buf) && ss_write(knob, show, sizeof show);
    knob->light = color;
}
