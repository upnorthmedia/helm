# Helm deck firmware (ESP-IDF)

The firmware for the Waveshare ESP32-P4-WIFI6-Touch-LCD-5 (5 inch, 720 x 1280 touch), turned landscape to 1280 x 720 as the v2 case mounts it. It speaks the Harness frame to the bridge over USB, runs the deck logic from `firmware/core`, and draws the Home, List, Detail, Confirm, Result, and link-unknown screens laid out like `sim/render.py`. It drives the four MX key switches and their lights, the I2C knob and its light, the 8-light bar, and the chime through the board's speaker output (see [Keys, knob, lights, and chime](#keys-knob-lights-and-chime)). None of those parts is needed: with none fitted the board works alone from touch, with four on-screen keys and swipe, tap, and long-press gestures.

One board has run it so far, on the bench with nothing on the header: it flashed, booted to the link-unknown screen, and talked to the bridge over the native USB port. Beyond that, it builds, the screens were rendered on the Mac through the same LVGL and compared with the simulator (see [How it was checked](#how-it-was-checked)), and every pin, port, and timing assumption is listed under [Verify on the board](#verify-on-the-board), with the checks that board passed marked.

**The 4 inch board is no longer a build target.** v1's Waveshare ESP32-P4-WIFI6-Touch-LCD-4B needs its own board package, which defines the same `bsp_*` functions as this one, and its own 720 x 720 layout, so one tree cannot build both without carrying two board layers and two sets of screens. The last firmware for it is on main at commit `b2f7670`.

## The board

Sources, read 2026-11-10:

- Wiki: [docs.waveshare.com/ESP32-P4-WIFI6-Touch-LCD-5](https://docs.waveshare.com/ESP32-P4-WIFI6-Touch-LCD-5). Store: [SKU 33762](https://www.waveshare.com/esp32-p4-wifi6-touch-lcd-5.htm?sku=33762) (33763 is the same board with an OV5647 camera).
- Waveshare's board repository, [waveshareteam/ESP32-P4-WIFI6-Touch-LCD-5](https://github.com/waveshareteam/ESP32-P4-WIFI6-Touch-LCD-5) at commit `a334bad`: the schematic (`hardware/schematic/ESP32-P4-WIFI6-Touch-LCD-5-Schematic.pdf`), its I/O list (`docs/IO.md`) and schematic cross-check (`docs/HARDWARE.md`), and the LVGL example (`examples/esp-idf/08_lvgl_demo_v9`).
- The board package source, [`bsp/esp32_p4_wifi6_touch_lcd_5`](https://github.com/waveshareteam/Waveshare-ESP32-components/tree/master/bsp/esp32_p4_wifi6_touch_lcd_5) in waveshareteam/Waveshare-ESP32-components.

| Part | What it is | Source |
| --- | --- | --- |
| Module | ESP32-P4NRW32 (32 MB PSRAM in the package), 32 MB NOR flash (GD25Q256), ESP32-C6-MINI-1 for Wi-Fi over SDIO | Wiki; `docs/HARDWARE.md` |
| Panel | 5 inch IPS, 720 x 1280 portrait, HX8394 over 2-lane MIPI DSI at 700 Mbit/s per lane | Board package `display.h` and `esp32_p4_wifi6_touch_lcd_5.c`; `docs/IO.md` |
| Panel timing | `HX8394_720_1280_PANEL_30HZ_DPI_CONFIG`: 58 MHz pixel clock over 800 x 1318 total, so about 55 Hz (derived) despite the macro's name | `waveshare/esp_lcd_hx8394` 2.1.0, `esp_lcd_hx8394.h` |
| Touch | GT911, 5 points, at 0x5D or 0x14 on the shared I2C bus. The package drives neither its reset nor its interrupt (`GPIO_NUM_NC`); on the schematic reset goes to GPIO23 through R37 and the interrupt to GPIO2 through R108, marked "NC/0R" | Board package header; `docs/IO.md`; schematic "5inch Display" block |
| Backlight | LEDC PWM on GPIO26, 5 kHz, 10 bit; enable on GPIO33 | Board package; schematic |
| Audio | ES8311 codec into an NS4150B amplifier (enable GPIO53), out on J5, a GH1.25 2-pin header with a lock for an 8 ohm, 2 W speaker | Wiki "Speaker Header"; schematic "PA&SPEAKER&MIC" |
| Expansion | J3, 40 pins at 2.54 mm, Raspberry Pi HAT style | Wiki "40PIN Header Expansion Header"; schematic "Interface" |

## Versions

| What | Version | Why |
| --- | --- | --- |
| ESP-IDF | **v5.5.6** (2026-10-16) | The board package needs ESP-IDF 5.4 or newer (`idf: '>=5.4'`); v5.5.6 is the newest patch of the 5.5 line, as before. |
| Board package | [`waveshare/esp32_p4_wifi6_touch_lcd_5`](https://components.espressif.com/components/waveshare/esp32_p4_wifi6_touch_lcd_5) **1.0.4** (2026-08-25, source commit `9c772a1`) | Display (HX8394, `waveshare/esp_lcd_hx8394` 2.1.0), touch (GT911), and LVGL through `espressif/esp_lvgl_adapter` 0.6.4. The newest release; the source on GitHub is still 1.0.4. |
| LVGL | **9.5.0** | The board package pins `lvgl/lvgl: 9.5.0` exactly, so the component manager cannot resolve any other version beside it. `ui.c` uses the 9.5 API; LVGL 9.6's `lv_obj_set_clickable` and friends are a small `set_flag` helper there. |
| USB device stack | `espressif/esp_tinyusb` **2.4.0** (TinyUSB 0.21.0) | CDC-ACM on the P4's native USB. |
| Light chain | `espressif/led_strip` **3.0.3** | NeoPixels over RMT. |

`main/idf_component.yml` names the direct dependencies and `dependencies.lock` pins every component with its hash, so a build fetches exactly these.

**Why not keep LVGL 9.6.** v1 pinned `~9.6.0`. The LCD-5 package's exact `9.5.0` pin leaves three ways out: move Helm to 9.5 (done), override the package's dependency, or copy the package into the tree. Overriding fights the component manager on every update, and a copied package stops getting Waveshare's fixes. The 9.6 API `ui.c` used was only the four object-flag setters.

## Build

Install ESP-IDF v5.5.6 anywhere you like (it does not need to be system wide). For example, under `~/.cache`:

```sh
git clone -b v5.5.6 --depth 1 --recursive --shallow-submodules https://github.com/espressif/esp-idf.git ~/.cache/helm-esp-idf/esp-idf-v5.5.6
export IDF_TOOLS_PATH=~/.cache/helm-esp-idf/tools
~/.cache/helm-esp-idf/esp-idf-v5.5.6/install.sh esp32p4
```

`export.sh` looks for the Python environment `install.sh` made for the `python3` on the PATH, so run both with the same `python3` (this was built with 3.13). Then, in each new shell:

```sh
export IDF_TOOLS_PATH=~/.cache/helm-esp-idf/tools
. ~/.cache/helm-esp-idf/esp-idf-v5.5.6/export.sh
idf.py -C firmware/idf build
```

Set `IDF_TOOLS_PATH` with `export` on its own line. In zsh, `IDF_TOOLS_PATH=... . export.sh` on one line does not pass the variable into the sourced script, which then falls back to `~/.espressif`.

The first build downloads the components into `firmware/idf/managed_components/` (ignored by git) and takes a few minutes on an M-series Mac. A tree that built the 4 inch firmware still has that board's components there: delete `firmware/idf/managed_components/` and `firmware/idf/sdkconfig` before the first LCD-5 build. After changing `main/Kconfig.projbuild` or `sdkconfig.defaults`, run `idf.py reconfigure` (or delete `firmware/idf/sdkconfig`) so the new options are picked up. Settings live in `idf.py menuconfig` under **Helm deck**.

CI (`.github/workflows/tests.yml`, job `firmware-idf`) builds the default configuration, which has every hardware part on, and one with every alternative (`sdkconfig.p4-rev1` and `sdkconfig.ci-alt`: the UART link, the 90 degree rotation, no on-screen keys, key switches, lights, and chime off, the knob reversed at 0x37) in Espressif's `espressif/idf:v5.5.6` image.

**Chip revision.** ESP-IDF 5.5 builds for ESP32-P4 silicon v3.1 and newer by default, and those builds do not run on v0.x or v1.x chips (and the reverse). Waveshare's LCD-5 LVGL example targets v3.0 and newer (`CONFIG_ESP32P4_REV_MIN_300`), and its `docs/IO.md` mentions both "rev1.3 and rev3.x" silicon, so a given board's revision is not known until it is here: `esptool.py --chip esp32p4 chip_id` prints it (the first board read v3.2, which takes the default build). For a chip older than v3.0:

```sh
idf.py -C firmware/idf -B build/idf-rev1 -D SDKCONFIG="$PWD/build/idf-rev1/sdkconfig" \
  -D "SDKCONFIG_DEFAULTS=sdkconfig.defaults;sdkconfig.p4-rev1" build
```

This keeps its own `sdkconfig` beside its own build directory. Defaults files only fill in a new `sdkconfig` and never override an existing one, so adding `sdkconfig.p4-rev1` to the default build's `firmware/idf/sdkconfig` would not change it.

**PSRAM speed.** Waveshare's example runs the PSRAM at 250 MHz, which ESP-IDF 5.5 offers only with `CONFIG_IDF_EXPERIMENTAL_FEATURES`. Helm keeps the 200 MHz setting v1 used.

**Flashing** goes through the "USB TO UART" connector, the CH343P: `idf.py -C firmware/idf -p /dev/cu.wchusbserialXXXX flash monitor`. On the first board macOS named that port `/dev/cu.wchusbserial<serial>` (whether that name depends on WCH's driver being installed was not checked). The native port, the Helm link, shows up as `/dev/cu.usbmodem*` (`/dev/cu.usbmodem1234561` on that board), so `wchusbserial` is the flashing port and `usbmodem` the link.

Run esptool from the ESP-IDF environment (after `export.sh`), not a separately installed one. On the first board a standalone esptool 5.2.0 read the chip revision but stopped on `flash_id` after loading its stub ("The chip stopped responding"), while ESP-IDF's bundled esptool 4.13.0 read the flash as 32 MB.

The schematic's "USB to UART" block has the usual auto-reset pair (an EMH4T2R: RTS drives EN, DTR drives GPIO35, the BOOT strap), so flashing needs no button press. That matters in the v2 case, where BOOT and RESET sit on the module's long edge inside the case.

## The USB-C ports

The board has two USB-C receptacles on one short edge. From the schematic ("USB" and "USB to UART" blocks) and the wiki:

| Schematic | Wiki name | Data lines go to | Use |
| --- | --- | --- | --- |
| H1 "Type-C UART" | "USB TO UART" | `USB_DBG_D_P/N` into the **CH343P** USB-to-serial bridge, which is UART0 on GPIO37 (TX) and GPIO38 (RX). The CH343P's RTS and DTR drive EN and GPIO35. | Flashing and the log console. |
| H2 "Type-C" | "USB OTG", "USB OTG 2.0 High Speed" | `USBD_P/N`, the **ESP32-P4's native USB 2.0 high-speed** port. | **The Helm link.** |

This is the same arrangement as the 4 inch board, so the link code is unchanged. Both receptacles have 5.1 kOhm pull-downs on CC1 and CC2 (R1/R4 and R2/R3) and feed the 5 V rail through their own AO3401 ideal-diode switch (Q2 for H1, Q3 for H2), so either cable alone powers the board and both together are fine.

`USBD_N` and `USBD_P` also run to J3 pins 25 and 27 (the wiki: "dedicated USB 2.0 High-Speed OTG pins ... cannot be used as regular I/O"). Leave those two header pins unconnected: anything on them is a stub on the high-speed link.

**The link uses H2, the native port**, as a TinyUSB CDC-ACM device (`main/link_usb.c`). The Mac sees a standard CDC-ACM device and opens it with its built-in driver as `/dev/cu.usbmodem*`; the USB strings name it "Helm" / "Helm deck" (VID 0x303A, Espressif's, from esp_tinyusb). Why not the CH343P:

- Opening a serial port usually asserts DTR and RTS, and on H1 those lines reset the chip or put it in download mode. The bridge opens the port with pyserial's defaults, so the deck could reset on every bridge start. On H2, DTR and RTS are only flags: the firmware reads DTR to know a program has the port open.
- UART0 also carries the boot ROM's and ESP-IDF's console output, which would be mixed into the frames.

The cost is that flashing still uses H1, so on the bench both cables may be plugged in (fine, see above). If the native port misbehaves on the real board, **Helm deck > Link to the Mac > UART0** switches the link to H1 (`main/link_uart.c`): frames share UART0 with the boot ROM text (the bridge's decoder skips it), and log lines go out as Harness log frames (type 0x04) instead of raw text.

Hello names the product: the core writes `"product":"helm"` in every hello (`HELM_PRODUCT` in `firmware/core/helm_event.h`). Which receptacle on the edge is H2 is not on the drawing; read the silkscreen.

## Screen rotation

The panel is 720 x 1280 portrait. The v2 case (option C in the design report) mounts the module turned so its USB-C edge faces the case's left wall, as v1 did, and the screens are laid out landscape at 1280 x 720. **Helm deck > Screen rotation** offers the two quarter turns: "270 (90 counter-clockwise)", the default and the case's orientation, and "90 clockwise" for a module turned the other way. Unturned and 180 are gone: they would give a 720 x 1280 portrait screen that the landscape layout does not fit.

How it works (`display_start` in `main/main.c`): `esp_lvgl_adapter` turns the picture as it copies each area to the panel, and reports the turned size (1280 x 720) to LVGL. Touch is turned through the touch driver's flags, which `esp_lcd_touch` applies in software against the panel's own 720 x 1280: for 270, mirror Y, then swap X and Y, so a touch at panel (px, py) lands at screen (1280 - py, px). Turned, the adapter needs three frame buffers (the package's `CONFIG_BSP_LCD_DPI_BUFFER_NUMS` default is 3), and the screen uses the adapter's double-direct mode rather than triple-partial: the adapter's README warns that triple-partial with rotation can freeze the P4's PPA under an unpatched ESP-IDF, and v5.5.6 does not carry that patch. The package leaves PPA acceleration off (`enable_ppa_accel = false`), as the 4 inch package did, so the CPU turns each changed area. At 1280 x 720 and RGB565 a frame is 1.8 MB (derived), three of them 5.5 MB of the 32 MB PSRAM.

This assumes the panel's native top is the short edge away from the USB-C ports, which is what the case assumes too. Waveshare publishes no rotated example to confirm it. If the picture comes out upside down in the case, choose 90 instead.

## Screens and touch

`main/ui.c` draws with LVGL 9 in the same places, sizes, and colors as `sim/render.py`, at 1280 x 720:

- **Status strip** across the top, as before, with more room for the reason text.
- **Home**: the headline, the usage and context lines, the four count tiles, and the herdr and queued lines on the left; on the right, "Needs you" with up to five of the view's items as compact rows (tinted strip, short id, kind and project, NEW, age), the selection outlined, and "turn for list" (or "press for list" when items name projects). With no items it says "Nothing needs you". This replaces v1's single selected-item strip at the bottom: the column only shows what the list would, never the full text (that stays behind a knob press, D18).
- **List**: six full-width rows (five with the on-screen keys).
- **Detail**, **Confirm**, **Result**: as before, wider. The Confirm fill bar is 800 px across, centered.
- **Answers out**: list rows, Home's column, and Detail say "YES sent" (or LATER, HOLD) in the key's color while that answer waits on firstmate's reply, and Result reads "Seen" once firstmate has read the note, with how long ago it was sent, turning amber with "firstmate has not picked this up" when the bridge says it stalled. `docs/sim/list-answered.png`, `result-seen.png`, and `result-stalled.png` show them.

One retained screen is rebuilt only when what it shows changes (screen, model, selection, scroll, project view, link state, mute, result), and the Confirm fill bar and the on-screen keys update every frame (about 30 a second).

| Touch | Does what the deck would do for |
| --- | --- |
| Hold an on-screen key (YES, LATER, HOLD) | Holding that key: Confirm with the 1 s fill bar; lifting early or sliding off the key cancels |
| Tap SHOW ME | Tapping SHOW ME (sliding off before lifting cancels it) |
| Swipe up or down, 48 px per step | Turning the knob (finger up moves down the list or the text) |
| Tap a list row | Turning the knob to that row; a tap on the selected row opens it (a knob press) |
| Swipe on Home, when items name projects | Turning through the project views (all, then each project); a tap opens that view's list, and swiping down past the list's first row goes back to Home |
| Tap anywhere else, Home's item column included | A knob press (open, back, leave the result) |
| Long press (0.8 s) without moving | The knob's long press: mute |

Touch only selects and opens; only a held key acts, as with the real keys. The keys light only when their action applies to the selected item (`helm_deck_key_lit`).

Differences from the simulator:

- The on-screen keys take the bottom 92 px (**Helm deck > On-screen keys**, on by default), four keys about 300 px wide. With them on, the list shows 5 rows instead of 6, Detail and Result show fewer lines, and the hints say swipe and tap instead of turn and press. Home's layout is the same either way. With the option off the layout is the simulator's.
- Text is LVGL's built-in Montserrat, not Menlo, and is never bold. Sizes above 48 px use 48; the big YES / LATER / HOLD on Confirm is 48 px scaled up to 110.
- Long text is cut with "..." at the same widths the simulator clips at, and wrapping follows the real font rather than a character count.
- The light bar is not drawn on screen.

## Keys, knob, lights, and chime

`main/io.c` wires the physical parts to the deck; the logic behind them is portable code in `firmware/core` with host tests (`helm_controls`, `helm_knob`, `helm_lights`, `helm_tone`, see `firmware/README.md`). Every part is a setting under **Helm deck**, on by default, and each is safe on a board without it:

| Part | Settings (defaults) | Driver | With nothing fitted |
| --- | --- | --- | --- |
| YES, LATER, HOLD, SHOW ME switches (MX on NeoKey socket breakouts, Adafruit 4978) | `HELM_KEYS_GPIO` (on), `HELM_PIN_KEY_YES`, `_LATER`, `_HOLD`, `_FOCUS` (GPIO22, 3, 4, 5), `HELM_KEY_DEBOUNCE_MS` (20) | Switch to GND, internal pull-up, debounced; a press or release goes to the deck as the matching key | The pull-up reads "not pressed" |
| Knob (Adafruit 5880, seesaw firmware) | `HELM_KNOB` (on), `HELM_KNOB_I2C_ADDR` (0x36), `HELM_KNOB_REVERSE` (off), `HELM_KNOB_LONG_PRESS_MS` (800, as the touch screen) | Seesaw over the board's shared I2C bus (GPIO7 SDA, GPIO8 SCL) at 100 kHz, polled every 10 ms: the encoder's delta becomes `knob` turns, the push switch a press on release or a long press (mute) at 800 ms while held | Logged once ("no knob at I2C 0x36"), then looked for every 2 s with a quiet `i2c_master_probe`; it is set up when it appears. A knob that stops answering three polls in a row is logged once and looked for again |
| Knob light (the 5880's NeoPixel, seesaw pin 6) | | Red at 35 % while muted, else off; written only when it changes | |
| Light chain: the four key lights (YES, LATER, HOLD, SHOW ME, in that order), then the NeoPixel Stick (Adafruit 1426) | `HELM_LIGHTS` (on), `HELM_PIN_LIGHTS` (GPIO21), `HELM_LIGHT_BRIGHTNESS` (64 of 255) | `espressif/led_strip` over RMT, GRB, WS2812 timing, refreshed only when a color changes | A pin driving nothing |
| Chime | `HELM_CHIME_OUTPUT`: the board's speaker output (default) or log only; `HELM_CHIME_HZ` (1320), `HELM_CHIME_MS` (120), `HELM_CHIME_VOLUME` (60 of 100) | One tone per model that asks for a chime, unless muted, from its own task so the deck never waits on audio | Plays to an empty speaker header |

What the lights show (`helm_lights`, a port of `_light_bar` and `_keys` in `sim/render.py`): a key is lit at 75 % in its own color (YES green, LATER blue, HOLD amber, SHOW ME white) only when its action applies to the selected item, and while a key is held only that key is lit. The bar runs a green head left to right for 2 s after something lands; is all amber at 55 % while the link or firstmate is unknown; shows one light per unseen item in its kind's color, pulsing between 55 and 100 % every 1.4 s, while there is something new; and is the usage gauge when calm. Lights fade toward black rather than the simulator's grey key face.

**The chime uses the board's audio.** The LCD-5 has the same path as the 4 inch board: the ES8311's output into an NS4150B (U15, its CTRL on GPIO53 through R100 with the R101 10 kOhm pull-down) and out on J5. Waveshare's package exposes it as `bsp_audio_codec_speaker_init()`, which brings up I2S1 (MCLK GPIO13, BCLK 12, WS 10, DOUT 9) and the codec over I2C and switches the amplifier on GPIO53. The design report's speaker, the Adafruit 3923 oval, has a 1.25 mm PicoBlade plug; whether it mates with J5's GH1.25 header (a different 1.25 mm family) is not checked. The tone is a 1320 Hz sine with a 3 ms rise and a squared fall to silence over 120 ms, at 22050 Hz (the package's default rate).

Hello lists what started: `screen-1280x720`, `touch`, `keys-4` always (on screen or as switches), then `knob` if the knob answered at start, `lightbar-8` if the light chain started, and `chime` if the speaker output opened. v1 sent `screen-720`; the bridge only logs capabilities, so nothing on the Mac changes.

## Pins

The defaults are general pins on the 40-pin header J3 and the shared I2C bus, all clear of the board's own parts. From the schematic's "Interface" block, which the wiki's pinout table matches pin for pin:

| J3 pin | Signal | Helm use |
| --- | --- | --- |
| 1, 3 | 5V | Power for the lights |
| 2, 18 | 3V3 | Power for the knob (never 5 V: its I2C pull-ups go to its VIN) |
| 4, 6 | GPIO7 (I2C SDA), GPIO8 (I2C SCL) | The knob, sharing the bus with the GT911 touch (0x5D or 0x14), ES8311 (0x18), and ES7210 (0x40); esp_codec_dev writes those two as 8-bit addresses, `ES8311_CODEC_DEFAULT_ADDR` 0x30 and `ES7210_CODEC_DEFAULT_ADDR` 0x80. The knob's settable range, 0x36 to 0x3D, clears all of them |
| 5, 10, 13, 19, 26, 29, 33, 40 | GND | |
| 17 | GPIO22 | YES key switch |
| 12, 14, 11 | GPIO3, GPIO4, GPIO5 | LATER, HOLD, SHOW ME key switches |
| 15 | GPIO21 | Light chain data |
| 8 | GPIO2 | Not used: may be the touch interrupt (below) |
| 7, 9 | GPIO37, GPIO38 | UART0 to the CH343P: not used |
| 21, 23 | GPIO24, GPIO25 (`USB1P1_N/P`) | The USB Serial/JTAG pads: not used |
| 25, 27 | `USBD_N`, `USBD_P` | The native USB link's data lines: leave unconnected |
| 28, 30 | GPIO34, GPIO35 | Strapping pins (35 is BOOT): not used |
| 16, 20, 22, 24, 31, 32, 34, 35, 36, 37, 38, 39 | GPIO28 to 32 and 46 to 52 | Spare. The schematic shows them only on J3 |

**Why YES moved off GPIO2.** v1 read YES on GPIO2. On the LCD-5, Waveshare's `docs/IO.md` says the schematic "routes `TP_INT` through the optional R108 (`NC/0R`) footprint to GPIO2", and the schematic's "5inch Display" block shows R108 marked "NC/0R" between `TP_INT` and GPIO2. With R108 fitted, the GT911 drives GPIO2 low on every touch, which a key on that pin would read as YES pressed, and a pressed key would hold the touch controller's interrupt line low. Which way R108 is fitted is not published, so Helm leaves GPIO2 alone and uses GPIO22, which v1 kept spare. LATER, HOLD, SHOW ME, and the light chain keep their v1 GPIOs.

Pins the board itself uses (`io.c` fails the build if a Helm pin setting names one): GPIO0/1 (32 kHz crystal), 2 (the touch interrupt when R108 is fitted), 6, 14 to 19, and 54 (the ESP32-C6 Wi-Fi module), 7/8 (I2C), 9 to 13 (I2S to the codecs), 20 (the battery voltage divider, new on this board), 23, 26, 27, 33 (touch reset, backlight PWM, panel reset, backlight enable), 24/25 (the USB Serial/JTAG pads), 34 to 38 (the chip's strapping pins, ESP-IDF's GPIO table for the P4; 35 is also BOOT, 37/38 UART0), 39 to 45 (microSD and its power), and 53 (amplifier enable). That leaves exactly GPIO3, 4, 5, 21, 22, 28 to 32, and 46 to 52 settable. The native USB port uses the P4's dedicated high-speed PHY pins, not GPIOs.

## How it is put together

- `main/main.c`: one deck task owns the `helm_deck_t` (the core is single-threaded). Every 20 ms at most it reads the link, applies queued touch input, polls the controls, runs `helm_deck_tick`, updates the lights and chime, and redraws under the display lock. Touch handlers run in the LVGL task and only queue input.
- The display lock is `display_lock()` in `main.c`, which calls `esp_lv_adapter_lock()` and checks for `ESP_OK`. Do not replace it with the board package's `bsp_display_lock()`: in 1.0.4 that returns the adapter's `esp_err_t` as a `bool`, so it reads false when it took the lock and true when it did not. Trusting it left the first board's screen white, with the UI never built, the lock never released, and the task watchdog firing in `lv_obj_clean`. Releasing through `bsp_display_unlock()` is fine.
- `main/link.h`: the byte link, `link_usb.c` or `link_uart.c`. Writes never block for more than 100 ms and drop a frame nobody is reading, as `helm/wire/transport.py` does. Over USB a frame is queued only once all of it fits, so a slow host never gets half a frame in front of the next one.
- `main/ui.c`: the screens and touch.
- `main/io.c`: the key switches, knob, light chain, and chime, on the portable logic in `firmware/core`.
- `partitions.csv`: one 6 MB app partition (the app is about 1.4 MB) on the 32 MB flash.

## How it was checked

- `idf.py build` for the default configuration (every hardware part on, rotation 270) and for the alternatives (UART link, rotation 90, no on-screen keys, key switches, lights, and chime off, the knob reversed at 0x37, pre-v3.0 silicon), with ESP-IDF v5.5.6 on macOS, no warnings from Helm's code.
- The pin check: setting `HELM_PIN_KEY_YES` back to 2 fails the build with "A key switch pin is one the board already uses", and evaluating `BOARD_PIN` for GPIO0 to 54 leaves exactly the J3 general pins listed above.
- `ui.c` and the core were compiled on the Mac against the same LVGL 9.5.0 sources, with a 1280 x 720 buffer standing in for the turned panel, and fed the simulator's fixture models as real frames from `helm/wire`, driven through the same knob, key, and tick steps `sim/snapshot.py` uses. All twelve screens in `docs/sim/` (Home, calm, context near the limit, link unknown, project view, away, Mac locked, List, project List, Detail, Confirm, Result) were compared side by side with the simulator's and match in layout and content; the fonts differ as listed above. The same screens with the on-screen keys on were checked for fit. That harness is not in the repo. The three answer screens added after it (List with answers out, Result seen, Result not picked up) were not run through it: `ui.c` draws them from the same positions and strings as `sim/render.py`, and both builds compile.
- The light colors, debounce, knob presses, chime tone, and the knob's seesaw driver are covered by the host tests in `firmware/test/test_core.c`.
- On the first board (chip revision v3.2, 32 MB flash), the bench bring-up with nothing on the header: the default build flashed through the CH343P, booted to the link-unknown screen, enumerated on the native port as a CDC-ACM device named "Helm deck", sent device hello to the bridge, and showed "no word from the bridge for 10 s" after the bridge stopped.
- Not checked on the real board: the rotation, the touch mapping, the key switches, knob, lights, chime, and timing other than the 10 s message. The touch handling was not re-run through a scripted pointer for the new layout; the tap targets come from the same row constants the drawing uses.

## Verify on the board

Checks marked "Seen on the first board" were observed during the first bench bring-up; the rest are still open.

Ports and silicon:

1. Which USB-C receptacle is H2 ("Type-C", the wiki's "USB OTG") and which H1 ("Type-C UART", "USB TO UART"): read the silkscreen. The case's back-wall jack goes to H2.
2. H2 enumerates on the Mac as a CDC-ACM device, `/dev/cu.usbmodem*`, and the bridge opens it (`python3 -m helm.bridge --port /dev/cu.usbmodemXXXX`) and logs `device hello: fw=helm-idf-0.1 caps=screen-1280x720,...`. Seen on the first board: H2 came up as `/dev/cu.usbmodem1234561`, product "Helm deck", and the bridge logged device hello.
3. H2 alone powers the board, and both cables together cause no trouble.
4. `idf.py flash` through H1 resets into the bootloader and back without touching BOOT or RESET (the auto-reset pair).
5. The chip revision (`esptool.py --chip esp32p4 chip_id`); add `sdkconfig.p4-rev1` if it is older than v3.0. Seen on the first board: v3.2.
6. Flash is 32 MB (`esptool.py flash_id`, a GD25Q256) and the 200 MHz PSRAM setting works. Seen on the first board: 32 MB flash.

Display and touch:

7. The HX8394 panel comes up with the backlight on, at the package's timing (about 55 Hz).
8. In the case, the picture is upright with the default rotation (270). If it is upside down, choose 90.
9. A touch lands where the finger is: tap the four corners, a list row, and each on-screen key. A mirrored or swapped touch means the touch flags in `display_start` do not match the panel.
10. The GT911 is found at 0x5D or 0x14 (the package logs "Touch 0x5d found" or "Touch 0x14 found").
11. Whether R108 is fitted (continuity from the GT911's INT to J3 pin 8, GPIO2). Helm does not use GPIO2 either way; if it is not fitted, GPIO2 is one more spare pin.
12. The turned double-direct mode keeps up with the CPU doing the rotation: the Confirm fill bar should move smoothly, a list scroll should not tear, and nothing should freeze. If it is slow, try the adapter's PPA acceleration (off in the package) before changing modes.

Keys, knob, lights, chime:

13. Pin 1 of J3, by the silkscreen, before wiring anything. The wiki warns that its pinout image is the silkscreen turned 90 degrees counter-clockwise. With the board unpowered, J3 pin 5 (GND) should beep to a USB-C shell on a meter's continuity setting.
14. GPIO22, 3, 4, and 5 read the key switches (pressed is low). GPIO3 to 5 default to the JTAG function (MTDI, MTMS, MTDO); `gpio_config` takes them over, which assumes JTAG runs over USB, as it does unless an eFuse selects pad JTAG.
15. The knob answers at 0x36 on GPIO7/GPIO8 alongside the GT911, ES8311, and ES7210; the log shows "seesaw hardware 0x87, product 4991". The 100 kHz knob clock coexists with the bus's 400 kHz.
16. Clockwise moves down the list (else set `HELM_KNOB_REVERSE`), one step per detent, and the push switch reads low on seesaw pin 24.
17. The knob's NeoPixel is on seesaw pin 6 and lights red while muted.
18. Unplugging the knob logs one "stopped answering" and nothing more; plugging it back in finds it within 2 s; no knob at boot logs one "no knob" line and the touch screen is unaffected.
19. GPIO21 drives the light chain: the first pixel is YES's key light, then LATER, HOLD, SHOW ME, then the stick from the end nearest the keys, GRB, colors not swapped.
20. 3.3 V data into lights powered from 5 V is marginal (WS2812B wants 0.7 x VDD, 3.5 V, for a high). If the first light flickers, power the chain from 3V3 at the low brightness cap, or add a level shifter. Twelve lights at the 64/255 cap draw at most about 180 mA; measure the board's own draw with the 5 inch backlight first.
21. A small 8 ohm speaker on J5 (GH1.25 2-pin) plays the chime at a sensible level at volume 60, the amplifier is quiet between chimes, and two chimes in a row are two distinct tones. Check that the chosen speaker's plug mates with J5.

Timing:

22. The 1 s hold feels right with the deck task's 20 ms loop and 33 ms redraws.
23. Swipe step (48 px), drag threshold (12 px), and long press (0.8 s) suit the 5 inch glass.
24. The deck sees a model within 2 s of the bridge starting and drops to "no word from the bridge for 10 s" when it stops. Seen on the first board: the 10 s message after the bridge stopped.
25. A frame written while the Mac is not reading is dropped after 100 ms rather than stalling the deck.
