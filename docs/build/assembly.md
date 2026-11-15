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

Look for `device hello: fw=helm-idf-<version> proto=1 caps=screen-1280x720,...`. The deck should show a model within 2 s, and drop to "no word from the bridge for 10 s" after you stop the bridge. When the board stays put, install the login agent with the same port ([README](../../README.md#start-the-bridge-at-login)):

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

Prepare the wiring as in 3.4 and assemble it face down as in 3.5, with the printed cover and base in place of the metal ones: the switches, encoder, light holder, speaker holder, power strip and back jack in the printed cover, the module face down in the face's pocket, the cradle on its back with the breakout under its plate, the harness plugged in and soldered at the parts, then the base as a lid on six M3 x 6 screws into the cover's flange inserts and four into the cradle's legs. Trim the tall header pins first (3.4 step 1): untrimmed, a NeoKey cannot seat on its switch in the printed cover either. The holders can be held with VHB tape here, so they come off cleanly for the metal cover. Then check what the model cannot: that the switches clip in firmly, the encoder's nut and the knob clear each other, the light bar reads through its window, the glass sits against the face without bowing and does not slide, the speaker is sealed under its slots, and both USB-C cables plug in (the flashing cable through the service slot). Use the deck in it for a while.

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

The case goes together **face down**: the cover lies on its face and takes every part, then the module, then the cradle, and the base goes on last as a lid. Every wire is cut and soldered with its part already in its final place, so no wire has to reach from the cover to a base set down beside it. Only one connection comes apart: the plug in the board's 40-pin socket. The parts, the plug and the wire lengths are in [wiring.md](wiring.md#wires); the routes are checked against the case model ([case/README.md](../../case/README.md#fit-check)).

Do these on the bench, in this order, before any case work:

1. **Trim the tall pins.** On each NeoKey and on the knob board, clip the header pins that stand up beside the switch or the encoder to about 1 mm above the board. As soldered they stand 6.1 mm proud and hit the underside of the face: a NeoKey cannot seat on its switch. Leave the long ends below the plastic for now; the wires are soldered to them, and they are trimmed in 3.5.
2. **Link the key row.** Join the four NeoKeys in a row at the case's 19.05 mm pitch, YES, LATER, HOLD, SHOW ME: VDD to VDD and GND to GND along the row, C to GND on each, and each O to the next I (YES O to LATER I, and so on).
3. **Cut the power strip.** Cut columns 1 to 6 of the Perma-Proto's two power rails off the long edge where the red line is outermost, as a strip 8.89 x 17.78 mm. The lengthwise cut runs between the blue line and the row of printed numbers, 8.89 mm in from the edge, midway between the - rail and row A: there is no hole row to follow there, so saw it, or score both faces deeply and snap. The cross cut runs between columns 6 and 7. If joints are already in the rails, cut around them; each rail is one connection along its whole length, so any 6 holes work. Meter it: each rail beeps end to end, and + to - stays silent. Solder SHOW ME's VDD and GND (O row) to the strip's + and - rails, the strip's rails to the stick's 5VDC and GND, and SHOW ME O to the stick's DIN, with at least the lengths in [wiring.md](wiring.md#wires). The strip and the stick then hang off the key row on their wires.
4. **Make the plug and the harness.** Glue two 10-pin pieces of the extra-long header into a 2 x 10 block, trim one side's pins to about 3 mm, and solder the 11 harness wires to those tails at full length, each joint heat-shrunk ([wiring.md](wiring.md#wires)). Mark the pin 1 corner. Do this now: the tails are only reachable on the bench. The wires' other ends wait until 3.5 step 13.

### 3.5 Put it together, face down

**Cover**

1. **Switches and knob, cover face up:** press each switch into its hole from the front, **its two metal pins toward the cover's front edge**: the square hole takes a switch four ways, and only that way meets the NeoKey's socket with the I rows toward the module. Push the encoder's bushing up through the knob hole from inside, **header row toward the module** (the back; no other edge clears the case), and tighten its nut on the face. No caps yet. Then lay the cover face down on a towel.
2. **Keys:** push the key row onto the switches' pins, I rows toward the module, YES nearest the left wall.
3. **Light bar:** set the NeoPixel Stick in the light holder, LEDs toward the diffuser, **DIN end toward the keys**. Seat the holder's tongue in the 49 x 6 mm window and bond the holder to the face's underside (VHB tape or epoxy).
4. **Speaker:** set the board's boxed speaker in the speaker holder and bond the holder under the slots, centred on them.
5. **Power strip:** stick the strip under the face between the speaker holder and the light holder, on a square of the 1.6 mm adhesive foam, joint side against the foam. Check every wire to it reaches.
6. **Back jack:** from outside, feed the Adafruit 6153's lead in through the hole low in the back wall, seat the jack with its flange outside, and tighten its nut inside, slot horizontal. **Only then** cut the JST plug off, leaving about 80 mm of lead from the jack body, and solder the breakout. The lead runs up to the rim (about 62 mm above the bench with the cover face down) and down the outside, so it ends about 15 mm short of the bench: rest the breakout on a box about 5 cm tall against the back wall, or hold it in helping hands. Solder red to VBUS, black to GND, white to D-, blue to D+; insulate the green and yellow (CC) wires and leave them unconnected, and twist white and blue together. The breakout cannot pass the 11.4 mm hole, so the lead goes through first. Leave the breakout loose.

**Module and cradle**

7. **Module:** lay it face down in the cover, glass on the face's underside, **USB-C edge toward the left wall** (the service slot), centred on the screen window (in the printed cover, about 4 mm from each edge of its pocket).
8. **Speaker and ribbon:** plug the speaker into SPK now, on the module's button edge at the USB-C end; SPK is J5, and the other two small white sockets (the batteries' J2 beside the 40-pin socket and H3) are not it. The cradle plate stops only about 0.3 mm short of SPK, so check the plug's body does not foul the plate's front edge when the cradle goes on. Plug the Adafruit 6370 ribbon into the board's **native USB port** ("USB", the receptacle nearer the header).
9. **Cradle:** check the five locating tabs are in their slots (2.2) and stick a pad of the 1.6 mm adhesive foam on the cradle's module side. Set it on the module's back, legs up, tabs around the glass.
10. **Breakout:** stick the breakout with foam tape on the cradle plate's outer face (its underside in the closed case) at its left front corner, pads facing away from the plate. Its receptacle is in the middle of a long edge: turn that edge toward the left wall, so the board runs front to back. Plug in the ribbon and fold its spare flat on the plate behind the breakout. Lay the jack lead along the left side, its spare in a loop to the left of the back left leg.

**Harness**

11. **Plug:** push the plug onto socket pins 1 to 20, flush against the socket's pin-1 end (away from the USB-C ports). It fits either way round and anywhere along the socket, so first check the pin 1 wire lands on the "5V" silkscreen and the pin 2 wire on "3V3". Tape the wires to the cradle plate within 20 mm of the plug.
12. **Lay the bundles:** the trunk (the 5 key wires and the strip's 5V and GND) diagonally across the cradle plate between the legs, then under the module's front edge to the parts; the knob's 4 wires straight forward on the right, inside the right legs and under the cradle's front arm. Tape each bundle to the plate about every 30 mm, clear of the leg ends and the flange edges.
13. **Solder at the parts:** cut each harness wire to fit and solder it ([wiring.md](wiring.md#wiring-table)): A on each NeoKey and YES I (I rows), VIN, SDA, SCL and GND on the knob's header row, 5V and GND to the strip's rails.
14. **Trim the long pin ends** on the NeoKeys and the knob to about 3 mm below the plastic, now that their joints are made. Untrimmed, the NeoKeys' front row hits the front flange.
15. **Power test:** plug the Mac's cable into the back jack and check the board starts by itself ([wiring.md check 5](wiring.md#verify-on-the-real-board)): POWER is on the module's front edge and reachable only now. The bridge should log `device hello`. Unplug it again.

**Close**

16. **Base:** lower the base onto the cover as a lid, its side walls outside the cover, its floor onto the leg ends and the flanges.
17. **Screws:** drive the 6 M3 x 6 screws through the base into the cover's flange nuts first, then the 4 into the cradle's leg inserts. The tabs let the cradle shift about 0.5 mm if a leg screw needs coaxing.
18. **Turn it over.** Fit the caps and the knob, and stick 4 feet under the base, clear of the screw heads.
19. Plug the Mac's cable into the back jack, and a cable into the flashing port through the left wall's service slot when flashing. Check the deck enumerates through the jack ([wiring.md check 15](wiring.md#verify-on-the-real-board)), the keys, the knob and the light order, the chime, that the picture is upright, and that touch lands under the finger.

To open the case later, turn it upside down, take out the ten screws and lift the base off. Untape the harness or pull the plug before lifting the cradle.

When the four key actions are stable, the caps can be swapped for machined aluminum ones with no change to the case ([case/README.md](../../case/README.md#keys-and-caps)).
