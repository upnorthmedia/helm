# Assembly: Helm v2, phases 1 to 3

The build order from the plan: **phase 1** the board and parts on a breadboard, **phase 2** the printed parts and the bench measurements, **phase 3** the SendCutSend aluminum case (option C, the captain's design v2 pick). Phase 0, the bridge and simulator, is done ([README](../../README.md#run-it)).

Parts are in [bom.md](bom.md); pins and power are in [wiring.md](wiring.md). Nothing here has been done on real hardware yet: every step is written from the firmware, case, and vendor documents, and the checks to make on the real board are listed in [wiring.md](wiring.md#verify-on-the-real-board).

**Firmware state.** The firmware on main targets the LCD-5 and drives everything in this guide: the 1280 x 720 landscape screen, the four key switches, the knob, the light chain, and the chime, each on by default and each harmless when its part is not fitted ([`firmware/idf/README.md`](../../firmware/idf/README.md#keys-knob-lights-and-chime)). So one flash at step 1.2 serves the whole of phase 1, and parts can be added one at a time. The pins in [wiring.md](wiring.md) are its defaults. v1, the 4 inch board in the first case, is at commit `b2f7670`.

## Phase 1: on the bench

Goal: screen and USB first, then knob and light bar, then keys and hold-to-confirm. Exit: a week of daily use on the bench.

### 1.1 Install ESP-IDF and build once

Do this before the board arrives. From [`firmware/idf/README.md`](../../firmware/idf/README.md#build):

```sh
git clone -b v5.5.6 --depth 1 --recursive --shallow-submodules https://github.com/espressif/esp-idf.git ~/.cache/helm-esp-idf/esp-idf-v5.5.6
export IDF_TOOLS_PATH=~/.cache/helm-esp-idf/tools
~/.cache/helm-esp-idf/esp-idf-v5.5.6/install.sh esp32p4

# each new shell (same python3 as install.sh used):
export IDF_TOOLS_PATH=~/.cache/helm-esp-idf/tools
. ~/.cache/helm-esp-idf/esp-idf-v5.5.6/export.sh
idf.py -C firmware/idf build
```

Keep `export IDF_TOOLS_PATH=...` on its own line: in zsh, `IDF_TOOLS_PATH=... . export.sh` on one line does not reach the sourced script, which then falls back to `~/.espressif`.

The first build downloads the board package and LVGL into `firmware/idf/managed_components/` and takes about a minute.

### 1.2 Screen and USB: first power and flash

Nothing on the header yet. Use the board alone.

1. **Find the two USB-C receptacles** on the board's short edge: "USB TO UART" (flashing and the log console, through the CH343P) is the one nearer the RESET, BOOT, and POWER buttons, and "USB" (the ESP32-P4's native port, the Helm link) the one nearer the 40-pin header. Confirm on the silkscreen ([wiring.md check 1](wiring.md#verify-on-the-real-board)).
2. **Plug "USB TO UART" into the Mac.** Check the board powers on by itself ([wiring.md check 5](wiring.md#verify-on-the-real-board)); if the screen stays dark, press POWER once and note it. List serial ports before and after (`ls /dev/cu.*`) to learn its name. On the first board the CH343P showed up as `/dev/cu.wchusbserial<serial>`; whether that name depends on WCH's macOS driver was not checked. A `/dev/cu.usbmodem*` name is the native "USB" port (step 1.3), not this one.
3. **Read the chip revision and flash size** in the shell where you ran `export.sh`, so these use ESP-IDF's own esptool (4.13.0 with v5.5.6). On the first board a separately installed esptool 5.2.0 read the revision but stopped on `flash_id` with "The chip stopped responding".

   ```sh
   esptool.py --chip esp32p4 -p /dev/cu.wchusbserialXXXX chip_id
   esptool.py --chip esp32p4 -p /dev/cu.wchusbserialXXXX flash_id
   ```

   The first board read revision v3.2 and 32 MB of flash.

   If the revision is older than v3.0, build with the extra defaults file in its own build directory:

   ```sh
   idf.py -C firmware/idf -B build/idf-rev1 -D SDKCONFIG="$PWD/build/idf-rev1/sdkconfig" \
     -D "SDKCONFIG_DEFAULTS=sdkconfig.defaults;sdkconfig.p4-rev1" build
   ```

   and add `-B build/idf-rev1 -D SDKCONFIG="$PWD/build/idf-rev1/sdkconfig"` to every `idf.py` command below. Flash should read 32 MB. The board resets itself into the bootloader through the CH343P's DTR and RTS lines, so flashing needs no button presses (schematic); if esptool waits at "power-on sync", hold BOOT and press RESET.
4. **Flash and watch the log:**

   ```sh
   idf.py -C firmware/idf -p /dev/cu.wchusbserialXXXX flash monitor
   ```

   Quit the monitor with Ctrl+].
5. **Check the screen.** The panel lights with the "link unknown" screen in landscape. The default **Screen rotation**, 270 (90 counter-clockwise), is for the module as it sits in the case: glass up, USB-C edge on the left. On the bench, prop the board that way so the picture reads upright; "90 clockwise" in `idf.py -C firmware/idf menuconfig` is for a module turned the other way ([`firmware/idf/README.md`](../../firmware/idf/README.md#screen-rotation)).
6. **Check touch.** Tap the corners and the on-screen keys; a touch should land where the finger is.

### 1.3 Plug in the link port

Plug **"USB"** into the Mac as well (both cables at once are fine; each port powers the board through its own ideal diode). A new `/dev/cu.usbmodem*` appears (`/dev/cu.usbmodem1234561` on the first board): that is the Helm link, a CDC-ACM device named "Helm deck". Note which name is which: the bridge must use "USB", the `usbmodem` one, not the `wchusbserial` flashing port. If no new port appears at all, suspect the cable before the board: swap in the flashing cable, which you know carries data. On the first board, the first link cable showed no device until it was swapped. Then unplug "USB TO UART" and confirm "USB" alone powers the board.

### 1.4 Point the bridge at the board

From the repo root, in dry run (the default: notes and pane focus are logged, not sent):

```sh
python3 -m helm.bridge --port /dev/cu.usbmodemYYYY -v
```

Look for `device hello: fw=helm-idf-0.1 caps=screen-1280x720,...`. The deck should show a model within 2 s, and drop to "no word from the bridge for 10 s" after you stop the bridge. When the board stays put, install the login agent with the same port ([README](../../README.md#start-the-bridge-at-login)):

```sh
scripts/install-agent.sh --port /dev/cu.usbmodemYYYY          # dry run
scripts/install-agent.sh --port /dev/cu.usbmodemYYYY --live   # real notes and pane focus, when you trust it
```

`python3 -m helm.wire.decode` turns captured raw bytes into readable frames if you need to see what crossed the cable.

If "USB" misbehaves, **Helm deck > Link to the Mac > UART0** moves the link to "USB TO UART" (frames share UART0 with boot text, and opening the port may reset the board through DTR and RTS; see the firmware README).

### 1.5 Knob and light bar

**Unplug both USB cables before wiring.**

1. **Find header pin 1** (5V, at the end away from the USB ports) and confirm the header is a female socket ([wiring.md check 4](wiring.md#verify-on-the-real-board)). Waveshare numbers it its own way, 5V on pin 1 and 3V3 on pin 2: wire by the silkscreen labels.
2. **Solder headers:** a piece of the extra-long header (Adafruit 400) onto the encoder board's breakout pads (VIN, GND, SDA, SCL among them, by the silkscreen), and a piece onto the NeoPixel Stick's input-end pads (DIN, 5VDC, GND). Set both on the breadboard.
3. **Breadboard rails:** header pin 1 (5V) to the red rail, pin 5 (GND) to the blue rail, each with a male-male jumper (Adafruit 1957) from the socket into the breadboard.
4. **Knob:** pin 2 (3V3) to VIN, pin 4 (SDA) to SDA, pin 6 (SCL) to SCL, GND to the blue rail. **VIN on 3V3, not 5V.**
5. **Stick:** 5VDC to the red rail, GND to the blue rail, pin 15 (GPIO21) to DIN for now (the key lights go in front of it in step 1.6).
6. **Knob cap:** check the 5880's shaft is the 6 mm D-shaft its datasheet shows, push the DROK knob onto it, and tighten its set screw.
7. **Power up** with both cables and watch the monitor (`idf.py -C firmware/idf -p /dev/cu.wchusbserialXXXX monitor`): expect "seesaw hardware 0x87, product 4991". Turn the knob: clockwise moves down the list (else set **Helm deck > Knob (Adafruit 5880 I2C encoder) > Reverse the turn direction**). Press opens; a 0.8 s press mutes, and the knob's own light goes red.
8. **Light bar:** with the key lights not yet in the chain, the first four colors the firmware sends land on the stick's first four LEDs; that is expected until step 1.6. Check the bar is not flickering ([wiring.md check 12](wiring.md#verify-on-the-real-board)).

### 1.6 Keys and hold-to-confirm

1. **Leave header pin 8 (GPIO2) empty.** On this board it can carry the touch controller's interrupt, so YES is on GPIO22, pin 17 ([wiring.md check 6](wiring.md#verify-on-the-real-board)).
2. **Solder headers** onto each NeoKey (both 5-pin rows, for strength, as Adafruit recommends). Seat a Kailh brown switch in each socket; Adafruit suggests a dot of hot glue if a switch works loose.
3. **Keycaps:** on the bench, the Adafruit 5662 caps with printed paper legends (YES, LATER, HOLD, SHOW ME), or the backlit icon caps if they have arrived. Snap the caps on.
4. **Wire each NeoKey** ([wiring.md](wiring.md#wiring-table)): VDD to the red rail, GND and C to the blue rail, A to its key pin (YES pin 17, LATER pin 12, HOLD pin 14, SHOW ME pin 11).
5. **Rewire the light chain:** pin 15 to YES **I**; YES O to LATER I; LATER O to HOLD I; HOLD O to SHOW ME I; SHOW ME O to the stick's DIN.
6. **Key switches are on by default** (**Helm deck > Key switches (GPIO) > Read the four key switches from GPIO**), so no rebuild is needed. The on-screen keys keep working alongside them.
7. **Test with the bridge in dry run.** Select an item with the knob; only the keys whose action applies light up. Press and release SHOW ME: the bridge logs a pane focus. **Hold YES**: the deck shows Confirm with a 1 s fill bar; let go early and nothing is sent; hold past 1 s and the bridge logs the YES note it would send, and the deck shows Result. Check the hold time feels right.
8. Check a pressed key reads low enough through the NeoKey diode ([wiring.md check 8](wiring.md#verify-on-the-real-board)).

### 1.7 Chime

1. Plug the speaker that came in the LCD-5's box into **SPK** (GH1.25, it latches).
2. The speaker is rated 2 W, like the amplifier, so the firmware's default **Helm deck > Chime > Volume** of 60 is a safe start. Let something new arrive with the bridge running and set the volume by ear. A long press on the knob mutes.
3. Measure the speaker (width, depth, height) for the case's holder ([wiring.md check 14](wiring.md#verify-on-the-real-board)).

Then live with it on the bench for a week, in dry run first and `--live` once it behaves.

## Phase 2: printed parts and measurements

Goal: the printed parts made, the whole deck fitted in the printed test enclosure, and the case's assumptions measured before any metal is ordered. Files are in [`case/out/stl/`](../../case/out/stl/); details in [`case/README.md`](../../case/README.md#printed-parts).

The printed test enclosure is a printed copy of the metal cover and base: the same outside, holes and mounting positions, with thicker walls and heat-set inserts where the metal has its flange nuts ([case/README.md](../../case/README.md#printed-test-enclosure)). Every part inside sits where it does in the metal case, so the cradle, holders and wiring move straight across to the metal case later.

### 2.1 Print the coupon

`stl/print_mx_coupon.stl`, plate on the bed, rim up, no supports. It has key holes at 13.95, 14.00, 14.05, and 14.10 mm (1 to 4 dots below each) and knob holes at 7.2 and 7.5 mm (1 or 2 dots above). Push a switch into each key hole and the encoder's bushing into each knob hole. This is an early check only: printers often make holes 0.1 to 0.2 mm small, so the metal coupon in 3.1 decides the hole sizes.

### 2.2 Print the parts

| STL | Qty | Orientation | Supports | Material |
| --- | --- | --- | --- | --- |
| `print_cradle.stl` | 1 | Module side down, as exported (the legs lean 15 degrees) | None | PETG |
| `print_cradle_tab.stl` | 5 | Glass side down, as exported | None | PETG |
| `print_light_holder.stl` | 1 | Open side down, as exported (the diffuser bridges 10.6 mm) | None | **White or natural** PETG |
| `print_speaker_holder.stl` | 1 | Flat, as exported | None | PETG |
| `print_test_cover.stl` | 1 | Face down, as exported | **Under the two bottom flanges only** | PETG |
| `print_test_base.stl` | 1 | Floor down, as exported | None | PETG |

- 0.2 mm layers, 3 walls, 20 percent infill. PETG because the module and backlight run warm.
- Heat-set an M3 insert into the bottom of each cradle leg with a soldering iron. The holes are 4.0 mm (`PRINT_INSERT_D`); check what your inserts want.
- Heat-set an M3 x 4 insert into each of the six holes in the test cover's bottom flanges, from below, flush with the flange's underside. The flanges are 4.4 mm thick, so the insert must be no longer than that.
- Push each of the five locating tabs into its slot in the cradle's arms from the top, glass side toward the middle, until its shoulder sits on the arm, with a drop of CA glue.

### 2.3 Fit the deck in the printed test enclosure

Assemble it as the metal case in 3.5, steps 1 to 10, with the printed cover and base in place of the metal ones: the cradle on four M3 x 6 screws up through the printed floor, the switches, encoder, light holder, speaker holder and back jack in the printed cover, the module in the cradle's tabs, and the cover closed with six M3 x 6 screws into its flange inserts. The holders can be held with VHB tape here, so they come off cleanly for the metal cover. Then check what the model cannot: that the switches clip in firmly, the encoder's nut and the knob clear each other, the light bar reads through its window, the glass sits against the face without bowing and does not slide, the speaker is sealed under its slots, and both USB-C cables plug in (the flashing cable through the service slot). Use the deck in it for a while.

### 2.4 Measure before ordering metal

`case/README.md` lists every dimension that is a guess. Measure each on the real parts and change `params.py` where a value is off:

| What to measure | `params.py` name | Value used |
| --- | --- | --- |
| Each USB-C receptacle's centre from the glass edge, with the module held as mounted (USB edge to the left) | `MODULE_USB_CENTRES` | 26.36 and 44.31 mm from the front edge |
| Glass face to the USB-C receptacle centre | `MODULE_USB_DEPTH` | 6.0 mm |
| The window frames the lit area with no border and does not press the touch area | `SCREEN_WINDOW_X`, `SCREEN_WINDOW_V` | 111.8 x 63.8 mm |
| Module thickness, glass to the tallest part on its back | `MODULE_THICKNESS` | 11.6 mm |
| Encoder bushing thread and length; anti-rotation tab (add a hole if so) | `ENCODER_HOLE` | M7 x 0.75, 7.5 mm hole |
| Encoder body size and plate-to-PCB height | `ENCODER_BODY`, `ENCODER_BODY_HEIGHT` | 13.4 x 12.5 mm, 6.5 mm |
| Plate top to the lowest wire with a switch fitted | `KEY_STACK_DEPTH`, `NEOKEY_PCB_THICKNESS` | 13.0 mm, 1.6 mm |
| The keycaps | `KEYCAP`, `KEYCAP_HEIGHT` | 17.6 mm, 5.0 mm |
| The knob, and that its skirt clears the encoder's nut | `KNOB_D`, `KNOB_HEIGHT` | 24 mm, 11 mm |
| The speaker (Adafruit lists 30 x 20 x 5 mm) | `SPEAKER_BOX` | 30 x 20 x 5 mm |
| LED span and stick height with LEDs | `LIGHT_WINDOW`, `LIGHT_STICK_THICKNESS` | 49 x 6 mm, 3.2 mm |
| Your flashing cable's plug body | `USB_PLUG_OVERMOLD` | 12.35 x 6.5 mm |
| How far the 6370 ribbon's plug head stands out of the port | `RIBBON_PLUG_HEAD` | 3.5 mm (head 12 x 7.3 mm) |

### 2.5 Rebuild the case files (only if you changed a parameter)

```sh
uv venv --python 3.12 case/.venv
uv pip install --python case/.venv/bin/python -r case/requirements.txt
case/.venv/bin/python case/build.py
case/.venv/bin/python -m unittest discover -s case/tests
```

`build.py` stops with an error if a SendCutSend rule, the logo clearance, or the parts interference check fails. Reprint any printed part whose numbers changed.

## Phase 3: SendCutSend metal case

Goal: the black anodized aluminum case with the engraved logo and soldered wiring. Do not upload until phase 2's measurements are in `params.py` and `case/out/` is rebuilt. Details are in [`case/README.md`](../../case/README.md#sendcutsend-sheet-metal-case).

### 3.1 Order 1: the coupon

The printed coupon does not predict laser-cut holes, and the 14 mm key hole needs +/- 0.05 mm while the laser holds +/- 0.127 mm, so cut a metal coupon first. Anodize it: the coating slightly shrinks the holes, so the fit matches the finished case. Keep it afterwards as the laser shop's engraving test piece (3.3).

| Setting | Value |
| --- | --- |
| File | `case/out/dxf/mx_coupon.dxf` (130 x 38 mm) |
| Units | **mm** (set it in the quote) |
| Material | 5052 H32 aluminum, **0.063 inch** |
| Finish | Deburred, **black anodized** |
| Hardware | None |

Fit a switch in each key hole (13.95 to 14.10, by the dots) and the encoder bushing in each knob hole (7.2, 7.5). Set `KEY_HOLE` and `ENCODER_HOLE` to the holes that fit, and rebuild (2.5). SendCutSend's pricing page offers free US shipping from $39; what checkout does with a smaller order is unverified, so a coupon-only order may cost more than its parts.

### 3.2 Order 2: the case

| Part | Upload | Bends | Hardware SendCutSend installs |
| --- | --- | --- | --- |
| Cover: front flange, front wall, face, back wall, back flange | `step/cover.step` (reference flat: `dxf/cover_flat.dxf`, 139.60 x 231.61 mm) | 90, 75, 105, 90 degrees | 6 x **S-M3-0** nut, on the two bottom flanges |
| Base: bottom and both side walls | `step/base.step` (reference flat: `dxf/base_flat.dxf`, 248.68 x 135.71 mm) | 2 x 90 degrees | none |

For every part: **mm** units, **5052 H32 aluminum, 0.063 inch**, **deburred**, **black anodized** (Type II; SendCutSend installs hardware after anodizing). Bent parts go up as STEP, and SendCutSend makes its own flat pattern; compare the quote's bend positions with the table below (from `out/checks.txt`):

| Part | Bend 1 | Bend 2 | Bend 3 | Bend 4 |
| --- | --- | --- | --- | --- |
| Cover | 90 degrees at y = 14.94 mm | 75 degrees at y = 29.19 mm | 105 degrees at y = 166.98 mm | 90 degrees at y = 216.67 mm |
| Base | 90 degrees at x = 53.10 mm | 90 degrees at x = 195.57 mm | | |

**Check the cover's bend preview before paying.** The cover's last flange is formed inside a U, and only SendCutSend's preview shows whether their press brake can do it. If it is refused, the fallback in `case/README.md` (nut tabs on the base instead of flanges on the cover) needs a model change. Bend lines stay visible after anodizing.

### 3.3 Engrave the logo

Take the anodized cover and the anodized coupon from order 1 to a local shop with a fiber laser, with the files and instructions in [`case/out/engrave/`](../../case/out/engrave/README.md): the mark centred on the screen window, 5.00 mm above its back edge, test piece first.

### 3.4 Solder the wiring

Move the breadboard wiring onto the Perma-Proto board: one strip for 5V and one for GND, fed from header pins 1 and 5 with female-male jumpers (Adafruit 1954, male end into the socket). Solder header pins onto the Perma-Proto for the parts' 5V and GND, and run the signal wires (header pins 2, 4, 6, 11, 12, 14, 15, 17) with the same jumpers, female end onto each part's header pins. Keep the same table ([wiring.md](wiring.md#wiring-table)). The board's header faces down in the case, so the jumpers plug in from below, into the gap the cradle leaves under the header. Wire routing inside the case is not modelled.

### 3.5 Put it together

The cover carries everything on the face; the base carries the board. Wires join them, so leave enough slack (about 100 mm) to set the cover down beside the base while you work.

1. **Cradle:** check the five locating tabs are in their slots (2.2), and stick a pad of the 1.6 mm adhesive foam on the cradle's top. Screw the cradle to the base's floor with 4 M3 x 6 screws up through the floor into its leg inserts.
2. **Breakout:** stick the Adafruit 4090 to the floor with foam tape under where the module's left half will sit, about 66 mm from the front and 12 mm from the left wall, receptacle toward the left wall.
3. **Keys:** from the front of the cover, press each switch into its hole. From inside, push each NeoKey onto its switch's pins; the boards hang from the switches. Keep the order YES, LATER, HOLD, SHOW ME from left to right. Fit the caps.
4. **Knob:** take the nut off the encoder's bushing, push the bushing up through the knob hole from inside, and tighten the nut on the face. The encoder board hangs from it. Fit the knob; its skirt covers the nut.
5. **Light bar:** set the NeoPixel Stick in the light holder, LEDs toward the diffuser, **DIN end toward the keys** (to the left). Seat the holder's tongue in the 49 x 6 mm window from inside and bond the holder to the face's underside (VHB tape or epoxy).
6. **Speaker:** set the board's boxed speaker in the speaker holder and bond the holder under the slots, centred on them.
7. **Back jack:** cut the JST plug off the Adafruit 6153 jack's lead, leaving about 80 mm of wire. From outside, feed the lead in through the hole low in the cover's back wall, seat the jack with its flange outside, and tighten its nut inside, slot horizontal. Solder red to the breakout's VBUS, black to GND, white to D-, and blue to D+; insulate the green and yellow (CC) wires and leave them unconnected. Twist the white and blue wires together.
8. **Module:** set it face up on the cradle, between the locating tabs, with its **USB-C edge toward the left wall** (the service slot). Plug the Adafruit 6370 ribbon into the breakout and into the board's **native USB port** ("USB", the receptacle nearer the back), with the ribbon running down from the plug.
9. **Wiring:** plug the jumpers into the header from below ([wiring.md](wiring.md#wiring-table)) and the speaker into SPK. **Before closing**, plug in "USB" and check the board starts by itself ([wiring.md check 5](wiring.md#verify-on-the-real-board)): POWER is on the module's front edge, out of reach once the cover is on.
10. **Close:** lower the cover over the module between the base's side walls. The glass meets the underside of the face and the foam takes up the rest. Drive 6 M3 x 6 screws up through the base into the cover's flange nuts. Stick 4 feet under the base, clear of the screw heads.
11. Plug the Mac's cable into the back jack, and a cable into the flashing port through the left wall's service slot when flashing. Check the deck enumerates through the jack ([wiring.md check 15](wiring.md#verify-on-the-real-board)), the picture is upright, and touch lands under the finger.

When the four key actions are stable, the caps can be swapped for machined aluminum ones with no change to the case ([case/README.md](../../case/README.md#keys-and-caps)).
