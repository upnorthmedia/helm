# Harness Pro: what it does and what is inside

The Autonomous Harness Pro is the device Helm is modeled on. This page records what it does and what hardware it uses, from public sources, so Helm can borrow what works and fill the gap it leaves.

All sources were read on 2026-11-09. The main ones:

- **[Product page][pp]**: https://www.autonomous.ai/harness-pro (spec strings checked against the page HTML).
- **[openharness repository][repo]**: Autonomous's MIT-licensed monorepo with the app, daemon, and device firmware. Links pin commit [`9d36097`][repo]. The Pro's firmware and docs live in [`devices/harness-pro/`][pro-dir]; the Pro's schematic, PCB, and enclosure CAD are **not** published there.

Claims marked **(inferred)** are reasoning from the sources, not something a source states.

## At a glance

| Area | Harness Pro | Source |
| --- | --- | --- |
| Purpose | Desk screen showing coding agents from all your machines; tap between agents or speak the next task | [Product page][pp] |
| Display | One 3.95 inch square LCD, 720 x 720, 60 Hz, capacitive touch, face tilted about 20 degrees | [Product page][pp] |
| Display controller | ST7703I over MIPI-DSI (2 lanes), GT911 touch controller | [pins_pro.h][pins] |
| Inputs | Touchscreen, one button (tap to go back or stop, hold to turn the screen off), three microphones | [Product page][pp] |
| Output | Screen, speaker for a notification tone | [Product page][pp] |
| Keys, knobs | None | [Product page][pp]; [pins_pro.h][pins] |
| Connectivity | USB-C to a computer running Harness; no Wi-Fi or Bluetooth in use | [Product page][pp]; [Pro README][pro-readme] |
| Processor | ESP32-P4, 16 MB flash, 32 MB PSRAM, in a Wireless-Tag WT01P4C5-S1 module (ESP32-P4 plus ESP32-C5) | [Product page][pp]; [pins_pro.h][pins] |
| Firmware | Open source (MIT), ESP-IDF 5.5.4, updates over the cable | [Pro README][pro-readme]; [Product page][pp] |
| Power | Over USB, no battery | [Product page][pp] |
| Size | 86.0 x 80.7 x 34.6 mm ("v2 CAD, preliminary") | [Product page][pp] |
| Housing | CNC aluminum body, cover glass face; colors Charcoal, Chalk, Burgundy | [Product page][pp] |
| Price | $299, bulk tiers down to $278 at 30 or more, ships Dec 15 | [Product page][pp] |

## What it does

The product page describes "A Desk Screen for Every AI Agent on Every Machine" that "Works with Claude Code, Codex, Cursor and more" ([product page][pp]).

- **One agent per screen.** "Each agent gets the whole screen and a pet that acts out its work. Swipe sideways to the next one."
- **Voice steering.** "Tap the agent on the glass and its pet puts on headphones. Say what you want. Tap anywhere to send it." Voice uses "Cloud speech-to-text."
- **Done alerts.** "Every agent keeps working on its own machine, and Harness Pro pings you the moment one is done."
- **Companion software required.** The spec row "Works with" says "Harness for Mac and Linux".

The software behind it ([openharness README][readme]; [engines.md][engines]):

- "One daemon per machine runs your agents in tmux. It dials out, so no machine opens a port."
- "Harness never wraps an agent. It reads the transcript the agent already writes and installs the" vendor's own hooks or plugin to learn when turns start and end ([engines.md line 3][engines]).
- "**Auto-approve** is the default permission mode for a new harness: the engine's own auto mode" ([engines.md line 24][engines]).

### No answering on the device

The Pro shows that an agent is waiting but does not answer it with a button.

- Firmware: when an agent has an open question, the voice gate refuses with "Answer its question first.", and the code comments "A Super Tab wait is not answered here: talking to the agent is how a person unblocks it." ([pro_app.c lines 711 to 712][pro-app]).
- Protocol doc: a Super Tab `question` "has no `key` or `options` and is not answered on a device" ([cable.md line 179][cable-md-179]).
- Port inventory: the Pro keeps only the question text, "No Pro-side question UI is used." ([port-inventory.md line 52][port-inv]).

Combined with the auto-approve default, the Pro is built for watching and voice, not approving. That is the gap Helm fills: physical answer keys routed through firstmate's own guards ([signals.md](signals.md)).

## How it talks to the computer

- **Cable only, by design.** "No Wi-Fi: the Pro talks over the cable only, and the module's ESP32-C5 is held in reset." ([Pro README line 67][pro-readme]). The link header says there is no Wi-Fi on this firmware and that "plugging the cable in is the authorization" ([cable_link.h lines 3 to 4][cable-link]).
- **USB device type.** The console and the link use the chip's built-in USB Serial/JTAG peripheral (`CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG=y` in [sdkconfig.defaults][sdkconfig]). No USB HID component appears in the build, so it is a USB serial device, not a keyboard **(inferred)**. The link header adds that "There is no second UART bridge to move the console to", so the console and the protocol share one wire ([cable_link.h line 13][cable-link]).
- **Framing.** Little-endian frames: a two-byte magic (`0xA5 0x48`, where `0x48` is "H" for Harness), a version byte, a type byte, a 16-bit length, the payload (at most 8192 bytes), and a CRC-16/CCITT-FALSE. Payload types: `0x01` JSON object with a `"t"` discriminator, `0x02` 16-bit mono PCM (voice, device to daemon), `0x03` firmware slice (daemon to device), `0x04` log line ([cable_frame.h][cable-frame]). The header comment shows `A5 5A`, but the defined constants are `0xA5 0x48`. The file explains why the second byte names the product: a sibling product with the same framing uses a different second byte, so neither daemon can read, and then reflash, the other's device.
- **Handshake.** The device sends a `hello` with its firmware version, product, protocol, board, and capability strings; "The hello capabilities are the contract" ([cable.md][cable-md]).
- **Agent status on the wire.** Library rows carry "`status` one of `idle working question finished failed paused offline`" ([cable.md line 51][cable-md-51]).
- **Link reliability.** "The Pro's USB-Serial/JTAG path loses bytes host to device, each loss under one 64-byte packet." ([cable.md line 144][cable-md-144]). The firmware PR describes losing "8 to 50 bytes now and then (host to device)" with "The root cause is not yet found." ([PR #1170][pr1170]). The CRC and resync on a bad frame are what keep it working.

Helm copies this frame (decision D9 in the [README](README.md#decisions)); [signals.md](signals.md#the-device-link) has the details.

## Hardware detail

### Display

- "720 × 720, 60 Hz, capacitive touch" on a 3.95 inch square display with cover glass; brightness is set from the app ([product page][pp]).
- Backlit LCD, not OLED: "LCD panel: ST7703I 720x720 over MIPI-DSI", 2 DSI lanes at 480 Mbps, RGB565, backlight by PWM into an AP3032 boost converter ([pins_pro.h][pins]).
- Touch: "Capacitive touch: GT911" ([pins_pro.h][pins]).
- Panel technology (IPS or other) and brightness in nits: not published.

### Inputs and audio

- "Button: Tap to go back or stop, hold to turn the screen off" ([product page][pp]); the hold time is 800 ms (`HOLD_SCREEN_MS 800` in [ptt_pro.c][ptt]).
- "Microphones: Three: front left, front right, rear" ([product page][pp]), through an ES7210 ADC; an ES8311 codec and NS4150B amplifier drive the speaker ([pins_pro.h][pins]).
- The pin map also defines a "single RGB LED" (WS2812 on GPIO3) and a vibration motor (GPIO28), but no other firmware file references them, so whether retail units have them fitted is unknown ([pins_pro.h lines 83 to 84][pins-83]).

### Processor and firmware

- "Processor: ESP32-P4, 16 MB flash, 32 MB PSRAM" ([product page][pp]).
- "Module: WT01P4C5-S1 (Wireless-Tag)", "ESP32-P4 + ESP32-C5 in one package" ([pins_pro.h][pins]). The ESP32-C5 is the Wi-Fi coprocessor, held in reset.
- Built for P4 silicon revision 3.x at 400 MHz (`CONFIG_ESP32P4_REV_MIN_300=y`, `CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ_400=y` in [sdkconfig.defaults][sdkconfig]).
- Needs ESP-IDF 5.5.4; the image is about 1.87 MB. "A wrong-revision image bricks the board, because of its power latch", so the flash script checks the chip revision first ([Pro README][pro-readme]).
- The carrier board maker is not public.

### Power, size, price

- "Power: Over USB, no battery" ([product page][pp]). The board carries an IP5306 charger, but the firmware keeps the battery supply off ("dock-only", [pins_pro.h][pins]). Power draw: not published.
- "86.0 × 80.7 × 34.6 mm, face tilted ~20°", marked "v2 CAD, preliminary"; CNC aluminum ([product page][pp]). Weight: not published.

## The sibling: the round Harness Device

Autonomous also sells a $149 round "Harness Device" ([Harness hub][hub]).

- Its product page lists "Wireless: Wi-Fi • Bluetooth LE" and "Autonomy: Auto-allow" ([Harness Device page][device]).
- Its open firmware README says "**The connection is USB.**" and that the current firmware has no Wi-Fi setup ([device firmware README][device-fw]). Both statements are on primary pages.
- Its hardware is open in the same repository: schematic, PCB, BOM, and STEP and STL housing files under [`devices/harness-device/hardware/`][device-hw].

## What Helm takes from this

| Harness Pro choice | Helm takeaway |
| --- | --- |
| Cable only; "plugging the cable in is the authorization" | Same for v1: USB serial, no Wi-Fi, no pairing |
| ESP32-P4 with a 720 x 720 MIPI-DSI touch panel | Same class of board: Helm uses a Waveshare ESP32-P4 4 inch 720 x 720 touch module (D3, [parts.md](parts.md)) |
| Binary frame with length and CRC, resync after a bad frame, because the USB link drops bytes | Same frame, with Helm's own second magic byte and only the JSON and log types (D9) |
| Capability `hello` at connect | Same, so the bridge and firmware can change separately |
| One screen, one button, voice | Helm adds four mechanical answer keys, a knob, a light bar, and a buzzer |
| No answering on the device; agents default to auto-approve | Helm's reason to exist: answer keys whose presses become captain notes to firstmate |
| CNC aluminum housing | Out of reach for one unit; Helm uses a stock sloped console with a laser-cut aluminum face ([case.md](case.md)) |

## Conflicts between sources

1. **Rotation.** The product page says "Rotate 180° from the Harness app"; the Pro README says "there is no turn and no setting" ([Pro README line 17][pro-readme]).
2. **Stock.** The page's structured data lists every color as in stock, while its embedded product data says `"is_in_stock":false`; the buy box still takes orders with a Dec 15 date ([product page][pp]).
3. **Earlier coverage.** A launch-day third-party write-up listed different colors and a Nov 30 delivery date; it says it was drafted by an AI model, so it is treated as low reliability (https://notes.nicolasdeville.com/office/harness-pro/).
4. **USB id.** A comment in the frame header says the board "enumerates as 303a:1001"; the same comment exists in the round device's firmware and predates the Pro firmware, so whether it was measured on the Pro is unverified ([cable_frame.h][cable-frame]).

## Not found

Weight, panel technology and brightness, power draw, box contents, the carrier board maker, the Pro's schematic and enclosure CAD, any FCC filing, and independent reviews or teardowns.

[pp]: https://www.autonomous.ai/harness-pro
[hub]: https://www.autonomous.ai/harness
[device]: https://www.autonomous.ai/harness-device
[repo]: https://github.com/autonomous-ai/openharness/tree/9d360978693c1025e8f6b6d585966520980a1994
[readme]: https://github.com/autonomous-ai/openharness/blob/9d360978693c1025e8f6b6d585966520980a1994/README.md
[engines]: https://github.com/autonomous-ai/openharness/blob/9d360978693c1025e8f6b6d585966520980a1994/docs/engines.md
[pro-dir]: https://github.com/autonomous-ai/openharness/tree/9d360978693c1025e8f6b6d585966520980a1994/devices/harness-pro
[pro-readme]: https://github.com/autonomous-ai/openharness/blob/9d360978693c1025e8f6b6d585966520980a1994/devices/harness-pro/README.md
[pins]: https://github.com/autonomous-ai/openharness/blob/9d360978693c1025e8f6b6d585966520980a1994/devices/harness-pro/firmware/main/board/pins_pro.h
[pins-83]: https://github.com/autonomous-ai/openharness/blob/9d360978693c1025e8f6b6d585966520980a1994/devices/harness-pro/firmware/main/board/pins_pro.h#L83-L84
[ptt]: https://github.com/autonomous-ai/openharness/blob/9d360978693c1025e8f6b6d585966520980a1994/devices/harness-pro/firmware/main/board/ptt_pro.c
[sdkconfig]: https://github.com/autonomous-ai/openharness/blob/9d360978693c1025e8f6b6d585966520980a1994/devices/harness-pro/firmware/sdkconfig.defaults
[cable-frame]: https://github.com/autonomous-ai/openharness/blob/9d360978693c1025e8f6b6d585966520980a1994/devices/harness-pro/firmware/main/cable/cable_frame.h
[cable-link]: https://github.com/autonomous-ai/openharness/blob/9d360978693c1025e8f6b6d585966520980a1994/devices/harness-pro/firmware/main/cable/cable_link.h#L3-L13
[cable-md]: https://github.com/autonomous-ai/openharness/blob/9d360978693c1025e8f6b6d585966520980a1994/devices/harness-pro/docs/cable.md
[cable-md-51]: https://github.com/autonomous-ai/openharness/blob/9d360978693c1025e8f6b6d585966520980a1994/devices/harness-pro/docs/cable.md?plain=1#L51
[cable-md-144]: https://github.com/autonomous-ai/openharness/blob/9d360978693c1025e8f6b6d585966520980a1994/devices/harness-pro/docs/cable.md?plain=1#L144
[cable-md-179]: https://github.com/autonomous-ai/openharness/blob/9d360978693c1025e8f6b6d585966520980a1994/devices/harness-pro/docs/cable.md?plain=1#L179
[port-inv]: https://github.com/autonomous-ai/openharness/blob/9d360978693c1025e8f6b6d585966520980a1994/devices/harness-pro/docs/port-inventory.md?plain=1#L52
[pro-app]: https://github.com/autonomous-ai/openharness/blob/9d360978693c1025e8f6b6d585966520980a1994/devices/harness-pro/firmware/main/app/pro_app.c#L711-L712
[pr1170]: https://github.com/autonomous-ai/openharness/pull/1170
[device-fw]: https://github.com/autonomous-ai/openharness/blob/9d360978693c1025e8f6b6d585966520980a1994/devices/harness-device/firmware/README.md
[device-hw]: https://github.com/autonomous-ai/openharness/tree/9d360978693c1025e8f6b6d585966520980a1994/devices/harness-device/hardware
