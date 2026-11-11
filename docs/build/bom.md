# Bill of materials: Helm v2

One shopping list for the v2 deck (the 5 inch board in the option C case), grouped by the build phase that first needs each part: phase 1 the board and parts on a breadboard, phase 2 the printed parts and bench measurements, phase 3 the SendCutSend metal case. The same rows are in [`bom.csv`](bom.csv).

Prices and stock were checked live on **2026-11-10**, USD, quantity 1, before shipping and tax. Adafruit figures come from Adafruit's product API (`https://www.adafruit.com/api/product/<PID>`), Pololu figures from the product pages' price and stock data, Waveshare from the store page's offer data, Amazon and Max Keyboard from their product pages. Stock changes daily. **Unverified** means the vendor page could not be read (DigiKey, Mouser, Bolt Depot, and McMaster-Carr all blocked or required a login) or the part is generic; nothing is filled in from memory. Nothing has been ordered or uploaded.

Sources merged here: the plan's settled build, [`docs/research/parts.md`](../research/parts.md), [`case/README.md`](../../case/README.md), the firmware's settings in [`firmware/idf/main/Kconfig.projbuild`](../../firmware/idf/main/Kconfig.projbuild), and the captain's design v2 pick (option C: the 5 inch board, flat black keycaps with lit icons, a machined black knob, hidden fasteners, the wheel + "helm" logo).

## Totals

| Phase | Priced, required | Optional | Not priced |
| --- | --- | --- | --- |
| 1. Breadboard | **$93.49** | $27.40 (bench keycaps, two USB-C cables) | none |
| 2. Printed parts | **$15.92** | | PETG filament, VHB tape or epoxy |
| 3. SendCutSend case | **$62.10** | $15.95 (hook-up wire) | the SendCutSend orders, the logo engraving |
| **All three** | **$171.51** | $43.35 | |

The SendCutSend parts are not quoted. The plan estimated **$140 to $170** for the previous design's four metal parts across the coupon order and the case order. Option C has two bent parts instead, and the design study measured their flat blanks at 661 cm² against 870 cm² before, so that estimate should be an upper bound; the cover's four bends may cost more per part than the old parts' two. A logo this small is usually a minimum-charge job at a local laser shop; no quotes were collected. Shipping is per vendor: Waveshare, Adafruit, Amazon, Max Keyboard, Pololu, and SendCutSend are six separate orders.

## Phase 1: on the bench

| Part | Buy | Used | Vendor, SKU | Price | Stock | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| Waveshare ESP32-P4-WIFI6-Touch-LCD-5, standard version (no camera) | 1 | 1 | [Waveshare 33762](https://www.waveshare.com/esp32-p4-wifi6-touch-lcd-5.htm?sku=33762) | $44.99 | In stock (offer data; no count shown) | $43.99 from 2. **Comes with a GH1.25 8 ohm 2 W speaker**, the deck's speaker. Do not pick 33763 (with camera, $52.99): its camera shares the knob's I2C address. Amazon resellers are fine if the board's silkscreen reads ESP32-P4-WIFI6-Touch-LCD-5 and it is not the camera version (33763) |
| NeoKey Socket Breakout with NeoPixel | 5 | 4 + spare | [Adafruit 4978](https://www.adafruit.com/product/4978) | $1.75 each, $8.75 | In stock | Hot-swap MX socket, one SK6812 mini-E light, a 1N4148 diode in series with the switch |
| Kailh tactile brown switches, 10 pack | 1 | 4 | [Adafruit 4954](https://www.adafruit.com/product/4954) | $6.95 | 61 | |
| I2C STEMMA QT rotary encoder with encoder | 1 | 1 | [Adafruit 5880](https://www.adafruit.com/product/5880) | $7.95 | In stock | The knob, seesaw firmware at 0x36. EC11 encoder: 6 mm D-shaft, 15 mm long, M7 x 0.75 bushing (datasheet). Wired from the header to its 0.1 inch pads |
| Aluminum knob, 6 mm shaft, black, 2 pack | 1 | 1 | [DROK, Amazon B0F21X91R4](https://www.amazon.com/dp/B0F21X91R4) | $9.00 | "Only 14 left in stock" | The machined black knob: 24 mm flange, 19 mm body, 14.5 mm tall, set screw. See below |
| NeoPixel Stick, 8 RGB LEDs | 1 | 1 | [Adafruit 1426](https://www.adafruit.com/product/1426) | $5.95 | 61 | The light bar |
| Half-size breadboard | 1 | 1 | [Adafruit 64](https://www.adafruit.com/product/64) | $4.95 | In stock | |
| Male-male jumper wires, 20 x 150 mm | 1 | about 15 | [Adafruit 1957](https://www.adafruit.com/product/1957) | $1.95 | In stock | From the board's 40-pin socket to the breadboard |
| Extra-long break-away 0.1 inch male header, 5 x 16 pin | 1 | about 50 pins | [Adafruit 400](https://www.adafruit.com/product/400) | $3.00 | In stock | Headers for the four NeoKeys, the encoder board, the stick, and the Perma-Proto |
| Black relegendable keycaps, 10 pack (optional) | 1 | 4 | [Adafruit 5662](https://www.adafruit.com/product/5662) | $7.50 | 34 | Bench caps with paper legends until the backlit caps (phase 3) arrive |
| USB-C to USB-C cable, 1 m (optional) | 2 | 2 | [Adafruit 4199](https://www.adafruit.com/product/4199) | $9.95 each, $19.90 | In stock | One for the link ("USB" on the bench, the back jack in the case), one for flashing ("USB TO UART"). Any data-capable cables work |

### Tools

Only what the steps in [assembly.md](assembly.md) use:

- **Soldering iron and solder:** headers on the NeoKeys, the encoder board, and the NeoPixel stick; the 6153 jack's lead to the 4090 breakout; the Perma-Proto wiring.
- **The same iron sets the cradle's heat-set inserts.** A heat-set insert tip helps (optional).
- **Flush cutters** and **wire strippers:** trimming header pins, cutting the JST plug off the 6153's lead, and the Perma-Proto wires.
- **2 mm hex key** for the M3 button head screws (usually included with the screws).
- **The knob's set-screw key** (comes with the knob).
- **A 3D printer** for the PETG parts in phase 2.
- **Calipers** for the phase 2 measurements.
- **A multimeter** for the wiring checks.

## Phase 2: printed parts and measurements

| Part | Buy | Used | Vendor, SKU | Price | Stock | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| Brass heat-set inserts, M3 x 4 mm, 50 pack | 1 | 4 | [Adafruit 4255](https://www.adafruit.com/product/4255) | $5.95 | In stock | One in each cradle leg. Adafruit gives only the outside diameter (4.2 mm); the case's holes are 4.0 mm (`PRINT_INSERT_D`), so check what these want |
| Closed-cell neoprene foam sheet, 1/16 inch (1.6 mm), adhesive back, 12 x 59 inch | 1 | 1 pad about 100 x 40 mm, plus scraps | [Amazon B0FK5DWHXM](https://www.amazon.com/dp/B0FK5DWHXM) | $9.97 | In stock | The pad between the module and the cradle, and the tape under the USB-C breakout |
| PETG filament | | about 60 g (estimate) | Any | Unverified | | Black or grey for the cradle and speaker holder; **white or natural** for the light holder, which is the diffuser |
| VHB tape or epoxy | | a few cm | Any | Unverified | | Bonds the light holder and the speaker holder under the face |

## Phase 3: SendCutSend metal case

| Part | Buy | Used | Vendor, SKU | Price | Stock | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| Test coupon, `dxf/mx_coupon.dxf`, 0.063 inch 5052 H32, deburred, black anodized | 1 | 1 | [SendCutSend](https://sendcutsend.com/) | Not quoted | | Ordered first. Anodized because the coating slightly shrinks the holes, so the key and knob fit matches the finished case; the same coupon is then the laser shop's engraving test piece. See [assembly.md](assembly.md#31-order-1-the-coupon) |
| Cover and base, 0.063 inch 5052 H32, deburred, black anodized, 6 x S-M3-0 installed in the cover | 1 set | 1 set | [SendCutSend](https://sendcutsend.com/) | Not quoted | | Files and options in [assembly.md](assembly.md#32-order-2-the-case). No extra coupon: the order 1 coupon is the laser shop's test piece |
| Logo engraving, fiber laser, on the finished cover | 1 | 1 | A local trophy, sign, or laser shop | Not quoted | | Files and instructions in [`case/out/engrave/`](../../case/out/engrave/README.md). SendCutSend does not engrave |
| Custom backlit keycaps, 1x1, with your own icons | 4 | 4 | [Max Keyboard](https://maxkeyboard.com/custom-backlight-compatible-keycap-for-backlit-keyboard.html) | $10.00 each, $40.00 | In stock | The lit icons (YES, LATER, HOLD, SHOW ME): black caps, the icon shines through. MX stem. OEM profile, not low profile. See below |
| Machine screws, M3 x 6 mm, button head hex socket (ISO 7380), black oxide | | 10 | Any hardware vendor | | | Recommended: about 1.65 mm heads, 2 mm hex key. 6 up through the base into the cover's flange nuts, 4 up through the floor into the cradle's inserts. [Pololu 2694](https://www.pololu.com/product/2694) (Phillips pan head, 25 pack, $1.85) is an acceptable alternative: same thread and length |
| Little rubber bumper feet, 4 pack | 1 | 4 | [Adafruit 550](https://www.adafruit.com/product/550) | $0.95 | In stock | Under the base, clear of the screw heads |
| USB-C screw panel mount jack to 6-pin JST PH lead, 175 mm | 1 | 1 | [Adafruit 6153](https://www.adafruit.com/product/6153) | $2.95 | In stock | The everyday cable's jack, low in the back wall. CC pulled down with 5.1 kOhm inside; D+ and D- on the lead |
| USB Type C breakout board, downstream connection | 1 | 1 | [Adafruit 4090](https://www.adafruit.com/product/4090) | $2.95 | In stock | The jack's lead is soldered to it (VBUS, GND, D+, D-). 20.4 x 14.2 x 5.0 mm |
| Slim right-angle USB C to USB C cable, 100 mm | 1 | 1 | [Adafruit 6370](https://www.adafruit.com/product/6370) | $6.95 | In stock | From the breakout to the board's "USB" receptacle; Adafruit verified power, data, and CC |
| Perma-Proto half-size board | 1 | 1 | [Adafruit 1609](https://www.adafruit.com/product/1609) | $4.50 | 11 | Soldered 5 V and ground distribution inside the case |
| Female-male jumper wires, 20 x 150 mm | 1 | about 12 | [Adafruit 1954](https://www.adafruit.com/product/1954) | $1.95 | In stock | Male end into the board's 40-pin socket, female end onto the parts' header pins |
| Hook-up wire, 22 AWG solid, 6 colors (optional) | 1 | | [Adafruit 1311](https://www.adafruit.com/product/1311) | $15.95 | In stock | Skip if you have wire |

## Choices this list makes

### The board: Waveshare LCD-5, standard version

The captain picked option C, the 5 inch board turned to landscape: 1280 x 720 instead of 720 x 720, in a case 32 percent smaller than the 4 inch design's. Buy the **standard version (33762)**. The camera version's OV5647 sits on the same I2C bus as the knob and answers at 0x36, the knob's address (from the OV5647's datasheet; not verified here). Both ship with a speaker in the box ("GH1.25 2PIN 8Ω 2W speaker", Waveshare's package list).

### The speaker: the one in the box

The board's speaker connector is a **GH1.25 2-pin with a lock** (Waveshare's wiki and store), on the NS4150B amplifier, and the board ships with an 8 ohm 2 W speaker on that plug. The firmware plays the chime through that path (`HELM_CHIME_SPEAKER`), so the speaker needs no GPIO and no extra parts.

| Candidate | Plug | Stock 2026-11-10 | Verdict |
| --- | --- | --- | --- |
| **The speaker in the LCD-5 box**, 8 ohm 2 W | GH1.25 2-pin, plugs straight in | Comes with the board | **Chosen.** Size not published: the case's holder assumes 30 x 20 x 6.8 mm; measure it ([wiring.md check 14](wiring.md#verify-on-the-real-board)) |
| Adafruit 3923 mini oval, 8 ohm 1 W, 30 x 20 x 5 mm (the design study's pick) | Molex PicoBlade 1.25 mm, 30 mm lead | 0, $1.95 | Out of stock, and PicoBlade is a different connector family from JST GH: not expected to mate |
| Waveshare 2030 cavity speaker type B (27859), 8 ohm 2 W, 20 x 30 x 6.8 mm | "PH1.25" 2-pin, 120 mm lead | In stock, $1.99 | A spare in the holder's size; that its plug fits the LCD-5's GH socket is not verified |

If a GH lead is ever needed, the only readable source was a third-party GH1.25 crimp kit ([Amazon B0CKZCFC54](https://www.amazon.com/dp/B0CKZCFC54), $18.99, "only 10 left"); DigiKey, Mouser, and LCSC blocked the check.

### The keycaps: custom backlit icons now, aluminum later

The captain picked flat black caps with lit icons. The case only needs a cap with a **Cherry MX cross stem**: the face is a standard MX plate (14.00 mm holes on 19.05 mm pitch), and the fit check passes with any cap up to 18.6 mm square and 14 mm tall ([case/README.md](../../case/README.md#keys-and-caps)).

| Option | Price | MX stem | Lit icons | Profile | Verdict |
| --- | --- | --- | --- | --- | --- |
| **Max Keyboard custom backlight compatible keycap**, 1x1 | $10.00 each (in stock) | "Compatible with Cherry MX and MX-style switches" | **Yes**: upload black-and-white art; "Black color will be the shine through area" | OEM (sculpted), ABS; height not listed | **Chosen**: the only verified source of custom shine-through icons |
| Keychron low profile ABS LSA set | $19.99 per full set | "Stem: MX style" | Shine-through, but standard letter legends | LSA, low profile | Flat and low, but no custom icons |
| XVX low profile shine-through set, Amazon B0DHZSBBGN | $14.44 per set | "MX-stem (cross-shaped)" | Letter legends | Low profile | Same |
| Adafruit 5662 relegendable, 10 pack | $7.50 | MX | Paper insert under a clear cover; the light shows around and through the paper | DSA-like | Bench caps (phase 1) |

No readable vendor sells **flat low-profile** MX caps with **custom** shine-through icons, so the chosen caps are taller and sculpted rather than flat. The icon art (a check mark, a clock, pause bars, an eye, as drawn on the renders) still has to be made as black-and-white images for the order. Low-profile caps made for low-profile switches may also sit low or bottom out on full-height Kailh switches (a guess, untested): try one before buying a set.

**Machined aluminum caps later are a cap swap.** Two vendors state MX stem compatibility for 1u machined aluminum caps on their own pages: Keychron's aluminum alloy artisan keycap AT-26, **$24.99 per cap** (green and purple in stock, black sold out; [keychron.com](https://www.keychron.com/products/keychron-cute-computer-aluminum-alloy-artisan-keycap)), and a CNC-machined 6063 aluminum 1U set of four, **$22.99** ("only 7 left"; [Amazon B0HFW9C7RY](https://www.amazon.com/dp/B0HFW9C7RY)). Solid metal caps cannot shine through: engrave the icons instead, and the NeoKey lights show only as a glow around each cap's base.

### The knob: DROK 24 mm aluminum, black

The captain picked a machined black knob whose skirt hides the encoder's nut, over today's Adafruit 5527 (20 mm). The 5880's encoder has a 6 mm D-shaft (4.5 mm across the flat) standing about 7.5 mm above its M7 bushing (Adafruit's datasheet; Adafruit's second drawing shows an 18-tooth knurled shaft instead, so check the shaft on arrival), so any set-screw knob for 6 mm fits.

| Option | Price | Size | Verdict |
| --- | --- | --- | --- |
| **DROK aluminium knob, 6 mm, black, 2 pack** ([Amazon B0F21X91R4](https://www.amazon.com/dp/B0F21X91R4)) | $9.00, "only 14 left" | 24 mm flange, 19 mm body, 14.5 mm tall; "made entirely of aluminum"; set screw | **Chosen**: the right size, black, and its top-hat flange is the closest listed to a skirt |
| Taiss black aluminum knob, 2 pack ([Amazon B07F26WT4R](https://www.amazon.com/dp/B07F26WT4R)) | $9.99, "only 18 left" | 25 x 15 mm, solid machined, knurled, set screw | Fallback |
| Adafruit 2056 solid machined metal knob | $3.95, in stock | 25 x 15.5 mm, rubber grip band, color not stated | Not plain black machined |

**Not verified:** no listing gives a recess depth, so whether the DROK flange covers the encoder's nut (an M7 nut, about 2 mm tall on the face) is unknown until it is on the bench. If it does not, the Taiss or a knob with a stated recess replaces it; the case does not change.

### The header wires: 2.54 mm, male into the socket

The LCD-5's expansion header is a **40-pin, 2.54 mm female socket** (the 4B's was a 2.0 mm 2 x 7 header, which needed the Adafruit 1919 adapter wires). Plain 0.1 inch jumpers fit it: male-male (Adafruit 1957) from the socket to the breadboard on the bench, and female-male (Adafruit 1954) from the socket to header pins on the parts in the case. Waveshare numbers the pins with 5V on pin 1, not the Raspberry Pi's way; see [wiring.md](wiring.md#where-the-pin-numbers-come-from).

### The knob is wired, not plugged

The board has no STEMMA QT port, so the knob is wired from the header (3V3, GND, SDA, SCL) to the encoder board's 0.1 inch pads. **The knob's VIN goes to 3V3, never 5V** ([wiring.md](wiring.md#power)).

### Hidden fasteners

Nothing fastens through the face. The cover's two bottom flanges carry six S-M3-0 nuts that SendCutSend presses in, and six M3 x 6 screws come up through the base into them. The module rests on the printed cradle, held to the floor by four more M3 x 6 screws into heat-set inserts. So the whole case needs one screw size: M3 x 6, black oxide button heads recommended. They are all under the base, so plain zinc-plated pan heads (Pololu 2694) also do.

## Dropped from earlier lists

| Part | Was in | Why it is gone |
| --- | --- | --- |
| Waveshare ESP32-P4-WIFI6-Touch-LCD-4B (31416) | v1 list | Option C uses the 5 inch LCD-5 |
| Tinkersphere 4198 speaker and the Adafruit 3922 PicoBlade lead | v1 list | The LCD-5 ships with a speaker on its own GH1.25 plug, and its socket is not PicoBlade |
| Female-female 2.54 to 2.0 mm jumpers (Adafruit 1919) | v1 list | The LCD-5's header is 2.54 mm |
| Anodized aluminum knob, 20 mm (Adafruit 5527) | v1 list | The captain picked a machined black knob that hides the nut |
| M3 x 8 and M3 x 10 screws (Pololu 1076, 2695), M3 x 4 nylon spacers | v1 list | Face screws, module clips, and the printed test enclosure are gone; the case uses M3 x 6 throughout |
| Buzzer, 5 V (Adafruit 1536) | parts.md, plan 4.8 | The chime plays through the board's own speaker output, so no buzzer is needed |
| STEMMA QT cable, 50 mm (Adafruit 4399) | plan 0.3 | The board has no STEMMA QT port, see above |
| Translucent keycaps (Adafruit 4956) | plan 0.3 | Superseded by the backlit icon caps |
| M2.5 nylon standoff set (Adafruit 3299) | plan 4.8 | The module sits on the printed cradle |
| Level shifter (Adafruit 1787) | plan 4.8 note | Out of stock on 2026-11-09 and not needed unless the first light flickers ([wiring.md](wiring.md#verify-on-the-real-board)) |

## Not verified

- Waveshare stock for 33762: the page lists it as in stock but shows no count.
- SendCutSend prices: nothing uploaded or quoted. The logo engraving: not quoted.
- The boxed speaker's size, and that it fits the case's holder.
- Whether the DROK knob's flange hides the encoder's nut, and the 5880's shaft (D-flat per the datasheet, knurled per a second drawing).
- How the OEM-profile backlit caps look and feel on the Kailh switches; no icon art made yet.
- The hole size Adafruit's 4255 inserts want.
- Price and stock of PETG and the bonding tape or epoxy.
- USB high speed through the 6153's hand-soldered lead and the 4090 breakout ([wiring.md check 15](wiring.md#verify-on-the-real-board)), and the 6370 plug head's thickness, which is estimated from Adafruit's photo, not published.
