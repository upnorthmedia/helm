# Helm firmware

`core/` is the device side of Helm that does not depend on the board: the wire, the model, the deck's behavior, and the pure logic behind the physical controls. It is portable C11 with no framework headers (only `<stdint.h>`, `<stdbool.h>`, `<stddef.h>`, `<string.h>`, and `<math.h>` for the light pulse and the chime tone), never allocates, and is tested on the Mac against the Python bridge code. Drawing, the display, touch, the USB stack, the I2C, RMT, and audio drivers, and pin maps are not here; they are in the ESP-IDF app in `idf/`, on Waveshare's board package.

## What is in core/

| File | What it does | Matches |
| --- | --- | --- |
| `helm_frame.[ch]` | The Harness frame: `A5 48 \| ver \| type \| len u16 LE \| payload (max 8192) \| CRC-16/CCITT-FALSE LE`. Encoder, and a streaming decoder that takes one byte at a time into a fixed buffer, with the vendor's resync rules and the 300 ms partial-frame expiry. | `helm/wire/frame.py`, the vendor vectors in `tests/vectors/` |
| `helm_model.[ch]` | The contract `Model` as fixed-size structs, and a strict parser for the `model` JSON payload. | `helm/contract.py`, `codec.decode_model` |
| `helm_jsonw.[ch]` | A bounded JSON writer that matches Python's `json.dumps(..., separators=(",", ":"), ensure_ascii=False)` byte for byte. | `codec._dumps` |
| `helm_event.[ch]` | Events (hello with product "helm", key down/up/held, knob, knob_press, select, seen, resync) and their frames. | `codec.encode_event` |
| `helm_deck.[ch]` | The deck's logic: screens, selection and scrolling, project views on the knob, 1 s hold to confirm, keys lit only when the selected item allows the action and YES / LATER / HOLD locked while firstmate is away (every key while the Mac is locked), mute, the chime played once (never while away), the green sweep, link unknown after 10 s without a model, seq-gap and bad-CRC detection with `resync` at most once per 2 s, and the hello cadence. | `sim/state.py`, `DeviceLink` in `helm/wire/transport.py`, `LinkSource` in `sim/app.py` |
| `helm_lights.[ch]` | The colors of the four key lights, the 8-light bar (green sweep, all amber while unknown, one pulsing light per unseen item, tinted by its project without changing its kind's hue, and when calm the usage gauge: lights for what is left of the tighter Claude window over a dim track, with none lit while usage is unknown, and the last light amber while a herdr agent is near its context limit), and the knob's light (red while muted), under a brightness cap. The pulse and sweep take their phase from the millisecond clock modulo their period, so they stay exact however long the deck runs. | `_light_bar` and `_keys` in `sim/render.py` (fading to black, not to the simulator's grey key face) |
| `helm_controls.[ch]` | Switch debounce, and the knob button's press (on release) and long press (at the threshold, while held). | The knob handling in `sim/app.py` |
| `helm_knob.[ch]` | Adafruit's seesaw register protocol for the PID 5880 I2C encoder over a caller-supplied I2C device: identify and set up, read turns and the push switch, set its NeoPixel, and find, lose, and find it again without blocking. Sources are cited in the header. | |
| `helm_tone.[ch]` | The chime: a short sine tone with a quick rise and a falling tail, as 16-bit PCM. | |

### Using it

```c
static helm_deck_t deck; /* about 31 KB: keep it static, not on a task stack */

static void send_event(void *ctx, const helm_event_t *ev) {
    static uint8_t frame[HELM_FRAME_MAX];
    size_t n = helm_event_frame(ev, frame, sizeof frame);
    /* write frame[0..n) to the serial port */
}

static const char *const caps[] = {"screen-1280x720", "keys-4", "knob", "lightbar-8", "chime"};
helm_deck_config_t cfg = {"helm-0.1", caps, 5, send_event, NULL};
helm_deck_init(&deck, &cfg);

/* serial RX:     helm_deck_rx(&deck, buf, len, now_ms);
 * main loop:     helm_deck_tick(&deck, now_ms);   at least every 100 ms
 * controls:      helm_deck_key_down / key_up / knob / knob_press
 * drawing reads: helm_deck_model, helm_deck_selected, helm_deck_link_state,
 *                helm_deck_attention, helm_deck_key_lit, helm_deck_hold_progress_permille,
 *                helm_deck_take_chime, helm_deck_sweeping, helm_deck_list_first, deck.screen,
 *                helm_deck_view, helm_deck_has_views, helm_deck_view_count / _item / _pos */
```

`now_ms` is a `uint32_t` millisecond clock that may wrap. On a host, the library links `libm` when the platform has it separately (Linux). Everything runs on one thread: call the functions from the same task, or hold a lock around them.

### As an ESP-IDF component

`core/CMakeLists.txt` calls `idf_component_register` when `ESP_PLATFORM` is set and builds a plain static library otherwise. In the ESP-IDF project, point `EXTRA_COMPONENT_DIRS` at `firmware/core` (the component is then named `core`) or copy it to `components/helm_core/`, and add it to the main component's `REQUIRES`. `idf/` builds it that way with ESP-IDF v5.5.6 (see [idf/README.md](idf/README.md)). The headers also compile as C++ (checked by `test/cxx_headers.cpp`).

## Choices

**A small JSON reader written for the schema, not jsmn.** jsmn (MIT) only tokenizes: it does not unescape strings, decode `\u` escapes, check UTF-8, or parse numbers, so that code would be needed anyway. It also needs a token array sized for the largest model: a full frame of the smallest items is about 1,500 tokens, roughly 24 KB with jsmn's 16-byte tokens. Walking the schema directly needs only the reader's stack, bounded by the 16-level nesting cap. And there is no vendored third-party code to track. The cost is owning a parser, which is why it is held to the Python codec by the cross-tests below. The reader is strict like `json.loads`: no trailing commas, no raw control characters in strings, valid UTF-8 only, nothing after the top-level object, nesting at most 16 deep.

**Strings in one pool.** Each model keeps its strings in an 8192-byte pool addressed by offset. A payload is at most 8192 bytes and every decoded string is shorter than its quoted source, so every model that fits a frame fits the pool: nothing is truncated, and the ref in `select` is exactly what the bridge sent. Fixed per-field arrays would force truncating refs (which must round-trip) or sizing every field for the worst case.

**Two model buffers.** A frame is parsed into the spare buffer and swapped in only when it parses, so a bad frame never disturbs what is on screen.

## Where it differs from the Python code

- Integers must fit their C field: int64 for `seq`, int32 elsewhere. Python accepts any size; the bridge never sends numbers near these limits. Such a model is refused (`HELM_PARSE_RANGE`).
- Strings may not contain U+0000 or a lone surrogate escape (`\ud800`). Python accepts both; the device keeps C strings and UTF-8. Such a model is refused.
- Actions are kept as a set, so a repeated action collapses and the order is the contract order. Nothing on the device depends on the order.
- Non-JSON frame types from the bridge are ignored, as the Python transport does.
- The project view's name is kept in a 132-byte buffer (`HELM_VIEW_BYTES`). The bridge clips projects to 32 characters, so this holds any it sends; a longer one from elsewhere is cut, matches no item, and the next model puts the view back to "all".

## Tests

```sh
scripts/test-firmware.sh
```

That builds `firmware/build/` with CMake and runs:

- `test/test_core.c`, the C unit tests under AddressSanitizer and UBSan: every vendor vector (encode, and every stream fed one byte at a time, with the discarded and corrupt counters), CRC check value, random round trips, every single-bit flip, expiry, noise, the buffer bound, model parsing and its error cases, exact event bytes, and the deck behavior ported from `tests/test_sim_state.py` plus the link rules (resync rate limit, partial-frame expiry, seq gaps, hello cadence, link timeout); the light colors in every attention state, the pulse phase after weeks of uptime, debounce across the clock wrap, short and long knob presses, the chime tone's shape, and the knob driver against a fake seesaw (setup bytes, the read delay, signed turns, the switch, the NeoPixel, an absent, lost, and returning knob, and a device that is not a seesaw).
- `tests/test_firmware_core.py`, which drives `test/helm_wire_tool.c` and compares with `helm/wire`: event frames for every event type and hundreds of random strings; models encoded by Python, parsed by C, and written back out byte for byte (fixtures, random models, models at the 8192-byte limit); a set of mutated payloads that both sides must accept or refuse alike; and 300 random noisy streams through both frame decoders, comparing frames, expiry, and counters.

The Python test is part of the normal suite (`python3 -m unittest discover -s tests -t .`) and skips when `cmake` is missing.
