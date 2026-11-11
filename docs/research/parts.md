# Parts: the v1 build

Prices and stock checked 2026-11-09, USD, quantity 1, before shipping and tax. Adafruit figures come from Adafruit's product API (`https://www.adafruit.com/api/product/<PID>`). Stock changes daily. "Unverified" means the source did not show the value or could not be loaded; nothing is filled in from memory.

The build follows the decisions in the [README](README.md#decisions): an ESP32-P4 720 x 720 touch module (D3), four MX keys with custom keycaps (D4, D5, D21), one push knob, a light bar, a buzzer (D6), USB power only (D8), Arduino firmware (D7), and USB serial to the Mac (D9).

## The main board: Waveshare ESP32-P4-WIFI6-Touch-LCD-4B

A finished 86.5 x 86.5 x 14.5 mm module with the screen, the ESP32-P4, and its own housing, the closest stock match to the Harness Pro (same SoC family, same 720 x 720 MIPI-DSI panel class, same GT911 touch controller).

| Fact | Value | Source |
| --- | --- | --- |
| SoC and memory | ESP32-P4NRW32 (32 MB PSRAM in package), 32 MB NOR flash | [Waveshare product page](https://www.waveshare.com/esp32-p4-wifi6-touch-lcd-4b.htm) (read 2026-11-09) |
| Display | "4-inch 720 x 720 IPS display", 2-lane MIPI-DSI; driver ST7703 per Waveshare's board support package | [Waveshare docs](https://docs.waveshare.com/ESP32-P4-WIFI6-Touch-LCD-4B); [BSP readme](https://components.espressif.com/components/waveshare/esp32_p4_wifi6_touch_lcd_4b) (`waveshare/esp_lcd_st7703`) |
| Touch | "GT911 5-point capacitive touch" on I2C (SDA GPIO7, SCL GPIO8) | [Waveshare docs](https://docs.waveshare.com/ESP32-P4-WIFI6-Touch-LCD-4B) |
| Wi-Fi / BLE | ESP32-C6-MINI-1U-H8 over SDIO (unused in v1) | [Waveshare product page](https://www.waveshare.com/esp32-p4-wifi6-touch-lcd-4b.htm) |
| Size | 86.50 x 86.50 mm face, 14.50 mm deep; touch active area 72.53 x 72.53 mm; four rear mounting holes on 74.00 x 70.00 mm centers; both USB-C ports and two buttons on one edge | [Waveshare 2D drawing](https://files.waveshare.com/wiki/ESP32-P4-WIFI6-Touch-LCD-4B/ESP32-P4-WIFI6-Touch-LCD-4B-2D.zip) |
| Expansion header (P3, 2.0 mm pitch) | 3V3, 5V, GND, GPIO2 to GPIO5, GPIO7 (I2C SDA), GPIO8 (I2C SCL), GPIO20, GPIO21, GPIO22, GPIO37, GPIO38 | [Waveshare docs](https://docs.waveshare.com/ESP32-P4-WIFI6-Touch-LCD-4B) |
| Price | $39.99 to $49.99 range shown, not mapped to variants (read 2026-11-09 by an earlier pass; the page timed out on the re-check) | Unverified for this exact variant |

### USB ports (re-verified from the schematic)

The board has **two USB-C ports**, both device-side (each has 5.1 k pull-downs on CC1 and CC2), and either can power the board ([schematic PDF](https://files.waveshare.com/wiki/ESP32-P4-WIFI6-Touch-LCD-4B/ESP32-P4-WIFI6-Touch-LCD-4B.pdf), "USB" and "USB to UART" blocks, read 2026-11-09):

| Port (schematic label) | Wired to | Use in Helm |
| --- | --- | --- |
| H1 "Type-C UART" | CH343P USB-to-UART bridge, UART0 on GPIO37 and GPIO38. Waveshare: "For power supply, programming, and debugging". | Flashing and the log console. The firmware can fall back to it for the link (**Helm deck > Link to the Mac > UART0**). |
| H2 "Type-C" | The ESP32-P4's native USB 2.0 high-speed OTG pins (`USBD_P` / `USBD_N`). Waveshare: "USB OTG 2.0 High Speed interface". | **The Helm link**: a TinyUSB CDC-ACM device, `/dev/cu.usbmodem*` on the Mac, carrying the binary frames. |

An earlier pass of this research read the product page as putting the OTG port on a Type-A connector. Waveshare's docs page and the schematic both show two Type-C connectors, so the Type-A reading is wrong for this board.

This research first picked H1 for the link. The firmware uses H2 instead; the reasons are in [`firmware/idf/README.md`](../../firmware/idf/README.md#the-usb-c-ports), in short:

- On H1 the CH343P's DTR and RTS drive the board's reset and boot pins, so a host that toggles them on open would reset the deck. On H2 they are only flags.
- UART0 also carries the boot ROM's and ESP-IDF's console text.
- Whether macOS needs a driver for the CH343P was never settled; H2 is a standard CDC-ACM device.
- Over either port Helm is a plain serial device, not HID, which matches D9. The Harness Pro's byte loss was on the P4's USB Serial/JTAG peripheral, which neither path uses; the frame's CRC covers loss either way ([signals.md](signals.md#the-device-link)).

The placement page puts H2 next to the BOOT and RESET buttons and H1 at the far end; confirm on the silkscreen. Both cables can be plugged in at once.

### Arduino on the ESP32-P4 (decision D7)

- Espressif's arduino-esp32 lists ESP32-P4 as supported in both stable and development ([Getting Started, supported SoCs](https://docs.espressif.com/projects/arduino-esp32/en/latest/getting_started.html)).
- Waveshare says: "Due to the limited support for ESP32-P4 on the Arduino platform, ESP-IDF is currently recommended for development." ([Waveshare docs](https://docs.waveshare.com/ESP32-P4-WIFI6-Touch-LCD-4B)).
- Espressif's Arduino display library, [ESP32_Display_Panel](https://github.com/esp-arduino-libs/ESP32_Display_Panel), ships an ST7703 driver and presets for two ESP32-P4 boards (Espressif's P4 Function EV Board and Waveshare's ESP32-P4-NANO), but no preset for this board (checked the repository tree on 2026-11-09). The panel's init sequence and timing would come from Waveshare's ESP-IDF board support package.

So Arduino is workable but the display bring-up is the riskiest firmware step: plan to port the panel settings from the BSP into an ESP32_Display_Panel board config, and treat a working "hello" screen as the first milestone.

## Parts table

| Part | Purpose | PID / SKU | Price (2026-11-09) | Stock | Alternatives |
| --- | --- | --- | --- | --- | --- |
| Waveshare ESP32-P4-WIFI6-Touch-LCD-4B | Screen, touch, controller | 31416 (page SKU) | $39.99 to $49.99 range (variant unverified) | Not shown | Waveshare ESP32-S3-Touch-LCD-4, 480 x 480, $25.99 to $32.99 range ([page](https://www.waveshare.com/esp32-s3-touch-lcd-4.htm)) |
| NeoKey Socket Breakout, x5 (4 plus a spare) | Hot-swap MX socket plus one RGB LED per key | [4978](https://www.adafruit.com/product/4978) | $1.75 each, $8.75 | In stock | NeoKey 1x4 I2C ([4980](https://www.adafruit.com/product/4980), stock 0); NeoKey 5x6 snap-apart ([5157](https://www.adafruit.com/product/5157), $29.95) |
| Kailh tactile brown switches, 10 pack | Quiet bump | [4954](https://www.adafruit.com/product/4954) | $6.95 | 62 | Clicky white ([4955](https://www.adafruit.com/product/4955), few left) |
| Custom keycaps, prototype set (D21) | Legends YES, LATER, HOLD, SHOW ME on paper inserts | [5662](https://www.adafruit.com/product/5662) | $7.50 | 34 | Printed legends for the final set, see below |
| I2C STEMMA QT rotary encoder, with encoder | Push knob on the shared I2C bus (default address 0x36; touch is at 0x5D or 0x14) | [5880](https://www.adafruit.com/product/5880) | $7.95 | In stock | Same board without encoder ([4991](https://www.adafruit.com/product/4991), $5.95) |
| Anodized aluminum knob, 20 mm, black | Knob cap | [5527](https://www.adafruit.com/product/5527) | $2.95 | In stock | Shaft fit to 5880's encoder unverified |
| NeoPixel Stick, 8 RGB LEDs | Light bar | [1426](https://www.adafruit.com/product/1426) | $5.95 | 81 | Per-key LEDs only |
| Buzzer, 5 V (superseded) | One chime | [1536](https://www.adafruit.com/product/1536) | $0.95 | In stock | Not used: the chime plays through the board's speaker output, see the pin budget |
| Perma-Proto half-size board | Distributes key, LED, 5 V, and ground wiring | [1609](https://www.adafruit.com/product/1609) | $4.50 | 18 | |
| **Core electronics** | | | **$85.49 to $95.49** (board range plus $45.50) | | |
| Half-size breadboard and jumper wires | Bench phase | [64](https://www.adafruit.com/product/64), [1957](https://www.adafruit.com/product/1957) | $4.95 + $1.95 | In stock | |
| 2.0 mm pitch cable to the P3 header | Connect P3 to the Perma-Proto | Not selected | Unverified | | Standard 2.54 mm jumpers do not fit 2.0 mm pins |
| USB-C to USB-C cable, 1 m (optional) | Host cable; any data-capable cable works | [4199](https://www.adafruit.com/product/4199) | $9.95 | In stock | |

### Pin budget

The firmware ([`firmware/idf/README.md`](../../firmware/idf/README.md#pins)) uses the five general pins on P3 and the shared I2C bus, and needs no pin for the chime:

| Signal | Pin |
| --- | --- |
| Keys YES, LATER, HOLD, SHOW ME | GPIO2, GPIO3, GPIO4, GPIO5 |
| Light chain: the four key lights, then the 8-light bar | GPIO21 |
| Knob (I2C, shared with touch and the codecs) | GPIO7, GPIO8 |
| Chime | No pin: the board's ES8311 codec and NS4150B amplifier drive a small 8 ohm speaker on the 2-pin AUDIO connector H4 |
| Power | 5V for the lights, 3V3 for the knob, GND |

GPIO37 and GPIO38 stay UART0 for the CH343P. GPIO20 and GPIO22 are unused spares (Waveshare's docs call them used; the schematic shows them only on P3). The full wiring and the chosen speaker are in [`docs/build/`](../build/wiring.md).

### Custom keycaps (decision D21)

The captain wants custom keys; this is read here as custom-legend keycaps on the MX switches, keeping the black anodized plate and a printed label strip ([case.md](case.md)).

| Option | What it is | Price | Notes |
| --- | --- | --- | --- |
| Adafruit black relegendable keycaps ([5662](https://www.adafruit.com/product/5662)) | Black base with a clear removable cover over a paper insert | $7.50, 34 in stock (pack size not in the API name; a reseller lists it as a 10 pack, unverified) | Best for the prototype: print legends on paper, change them as the key set changes. Light from the key's LED shows only around the insert. |
| Adafruit clear relegendable keycaps, 10 pack ([5039](https://www.adafruit.com/product/5039)) | Same, off-white base | $4.95, stock 0 | Out of stock. |
| Signature Plastics DSA individual text keycaps ([spkeyboards.com](https://spkeyboards.com/products/dsa-individual-text-keycaps)) | Single keycaps with custom text legends | Unverified (page returned HTTP 429) | Candidate for the final printed legends. |
| WASD Keyboards custom printing | UV-printed custom keycaps | Unverified (no current official price found) | Candidate for the final printed legends. |

Per-key light and printed legends pull against each other: an opaque cap hides the LED. If lit keys matter, pick shine-through legends or translucent caps for the final set. The legend vendor is left open.

### Power

USB only, no battery (D8). A USB 2.0 bus-powered device may draw up to 100 mA before configuration and up to 500 mA after it enumerates as high-power (cited from a TI datasheet's USB section, [TI SLVSBD0B](https://ti.com/document-viewer/lit/html/SLVSBD0B/usb-low-power-bus-powered-and-high-power-bus-powered-functions-slvsbd07138); the USB-IF spec text was not extracted). The CH343P port is a USB-C sink with 5.1 k CC resistors, which signals a request for default USB power. The P4 board's draw with its 4 inch backlight is not published, so measure it on the bench before adding LEDs, and cap LED brightness in firmware. The NeoPixel stick is specified for 5 V with about 18 mA per LED; driving its data from a 3.3 V pin is marginal, so verify on the bench.

## Looked at and not chosen

| Board or part | Price (2026-11-09) | Verdict |
| --- | --- | --- |
| Adafruit ESP32-S3 Feather ([5477](https://www.adafruit.com/product/5477)) plus 2.0 inch IPS ([4311](https://www.adafruit.com/product/4311)) | $17.50 + $19.95 | The review's recommendation; replaced by the P4 module (D3). Still the fallback if the P4 display bring-up under Arduino stalls. |
| Waveshare ESP32-S3-Touch-LCD-4 (480 x 480) | $25.99 to $32.99 range | Lower resolution; native USB on its USB-C. |
| M5Stack Dial v1.1 | $34.90 ([store](https://shop.m5stack.com/products/m5stack-dial-v1-1)) | A stand-in for proving the bridge; the simulator does that for $0. |
| Adafruit MacroPad RP2040 kit ([5128](https://www.adafruit.com/product/5128)) | $49.95, out of stock | Mono 128 x 64 screen is too small for decision text. |
| Adafruit LED Arcade Button 1x4 I2C ([5296](https://www.adafruit.com/product/5296)) | $9.95 plus buttons | Round holes need no coupon, but one fixed color per button and no custom legends. |

## Not verified

- The exact price of the 4B variant, and its current stock.
- Whether the CH343P path drops bytes, whether opening the port resets the board, and macOS driver support.
- Arduino display bring-up on this board (no ready preset).
- The board's current draw with the backlight on.
- The thread size of the module's rear mounting holes.
- Knob fit on the 5880 encoder; which encoder that board carries.
- Keycap pack size for 5662 and prices for printed legends.
