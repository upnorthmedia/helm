# Case: a stock sloped console with a SendCutSend face plate

> **Superseded.** The captain's F2 answer replaced the Hammond 1595C/1595E plan below with no stock box: a SendCutSend case sized to the parts, with a 3D printed test version first. That case is in [`case/`](../../case/README.md). This page is kept for the SendCutSend design rules, which `case/` checks against, and as the record of the stock-box option.

This page compares ways to house Helm, gives SendCutSend's published design rules, and records the v1 case decided before F2: a Hammond 1595 sloped console with its aluminum panel replaced by a laser-cut 5052 aluminum plate, black anodized, with a printed label strip (D20, D21 in the [README](README.md#decisions)).

- Sources were read on 2026-11-09. Prices are USD with that date. Claims marked **(inferred)** or **(estimate)** are reasoning or rough numbers, not quotes. No CAD exists yet.

## What the case has to hold

| Feature | Size or rule | Source |
| --- | --- | --- |
| Waveshare ESP32-P4 4 inch module | 86.50 x 86.50 mm face, 14.50 mm deep; touch active area 72.53 x 72.53 mm; four rear holes on 74.00 x 70.00 mm centers; USB-C ports on one edge | [Waveshare 2D drawing](https://files.waveshare.com/wiki/ESP32-P4-WIFI6-Touch-LCD-4B/ESP32-P4-WIFI6-Touch-LCD-4B-2D.zip) |
| MX switch cutout | 14 mm square, +/- 0.05 mm, corner radius 0.3 mm max | [Cherry "Keymodule MX" (Farnell copy), p.4](https://www.farnell.com/datasheets/16916.pdf); [Cherry MX Series (SparkFun copy)](https://cdn.sparkfun.com/datasheets/Components/Switches/MX%20Series.pdf) |
| MX plate thickness | "1,5 +0,1 mm" in one Cherry document, 0.06 +/- 0.004 inch in the other. 1.60 mm sheet fits both; 1.0 mm fits neither. | same |
| Plate top to switch PCB top | 0.197 inch (5.0 mm) | Cherry MX Series (SparkFun copy), "Mounting Options" |
| Key pitch | 19.05 mm (0.75 inch); four keys in a row span about 76 mm | [Adafruit 5157](https://www.adafruit.com/product/5157) |
| Encoder bushing | Bourns PEC11R: M7 x 0.75 thread, 6.0 mm shaft; no panel hole size given. Whether Adafruit 5880 carries this exact encoder is unverified. | [Bourns PEC11R datasheet](https://www.bourns.com/docs/product-datasheets/pec11r.pdf) |
| Light bar | 51.1 x 10.2 mm | [Adafruit 1426](https://www.adafruit.com/product/1426) |

Two physical facts drive every option:

1. **MX switches clip into a plate near 1.5 mm thick.** Most stock lids are the wrong thickness, so a laser-cut plate is needed either way.
2. **The encoder sits higher than the switch plate.** Cherry puts the plate about 5.0 mm above the switch PCB, while the PEC11R mounting surface sits 5.5 to 6.5 mm above its PCB, so the encoder board needs its own standoffs **(inferred from both datasheets)**.

## The stock box: Hammond 1595

Hammond describes the 1595 as "Plastic Console Enclosures", with "Integral brass bushings with four M3 x 0.5” x 8 mm (0.31”) Phillips pan head screws hold recessed panel into sloping front of case" and a "0.04” (1.01mm) thick aluminum panel" ([Hammond 1595 series](https://www.hammfg.com/electronics/small-case/plastic/1595)). The panel is a separate flat plate meant to be replaced, which is why this box works where molded lids do not.

| | 1595C | 1595E |
| --- | --- | --- |
| Outside (W x L x back height) | 161 x 96 x 58 mm | 215 x 130 x 75.5 mm |
| Panel outline | 156.00 x 92.10 mm | 209.98 x 124.98 mm |
| Panel screw holes | 3.90 mm on 147.40 x 82.10 mm centers | 3.92 mm on 201.30 x 116.50 mm centers |
| Price | $13.22 ([Dale Electric](https://dale-electric.com/products/1595CBK)) | $16.36 ([Dale Electric](https://dale-electric.com/products/1595EBK)) |
| Lead time | "over 7 working days" (Dale Electric) | "over 7 working days" (Dale Electric) |
| Fits the P4 module? | **No.** The 92.10 mm panel leaves about 2.8 mm each side of an 86.5 mm module, below SendCutSend's 2x-thickness edge rule (3.2 mm at 0.063 inch), and the box walls sit inside the panel outline **(inferred)**. | **Yes**, with room for the keys, knob, and light bar beside it. |

Sizes and panel dimensions: [1595CBK drawing](https://www.hammfg.com/files/parts/pdf/1595CBK.pdf), [1595EBK drawing](https://www.hammfg.com/files/parts/pdf/1595EBK.pdf), [series page](https://www.hammfg.com/electronics/small-case/plastic/1595). Colors: black (BK) or gray (GY).

**The plan before F2 was the 1595E** (superseded; see the note at the top). The review recommended the 1595C for a 2.0 inch screen; the captain's choice of the 4 inch P4 module (D3) is what moves the case up one size.

Not on the drawings, so unverified: the slope angle and the depth under the front of the slope. Measure the box before cutting a plate.

### Layout check (arithmetic, not CAD)

On the 209.98 x 124.98 mm panel: a window for the module at left (about 87 mm square of panel), then to its right the light bar above the knob, and below them the four keys in a row (76.2 mm). Width: 10 + 87 + 12 + 76.2 + 10 = about 195 mm, inside the 201.30 mm screw pattern. Height: the module is the tallest item at 86.5 mm, leaving about 19 mm to each panel edge.

### Mounting the module

The module's face and body share the same 86.50 mm outline, so it cannot drop into a cutout and rest on a lip. The cleanest option **(inferred)**:

- Cut a window in the plate slightly larger than the 72.53 mm touch area, so the plate frames the glass and hides the black border.
- Mount the module behind the plate with a second flat 5052 part (a bracket) screwed to the module's four rear holes (74.00 x 70.00 mm centers) and to press-fit standoffs on the plate.
- Keep the module's USB-C edge toward the back of the box so the cable can leave through a hole in the rear wall.

The rear holes' thread size is unverified, and the window size needs a bench check so the plate never presses on the touch area.

## Other options considered

| Option | Verdict | Source |
| --- | --- | --- |
| Hammond 1456 sloped aluminum console | 0.064 inch aluminum top, close to MX plate thickness; price unverified | [Hammond 1456](https://www.hammfg.com/electronics/small-case/general-purpose/1456) |
| Hammond 1599T ABS sloping console | Molded top, so every hole is cut into plastic; price unverified | [Hammond 1599T](https://www.hammfg.com/electronics/small-case/plastic/1599t) |
| Hammond 1591XXC and similar boxes | 2.00 mm molded lid; flat | [aggregator listing](https://www.mymectronic.com/part-detail/Hammond-Manufacturing/1591XXCGY) |
| SendCutSend flat sandwich (two plates on standoffs) | 2D files only and cheap, but the screen lies flat and the sides are open | SendCutSend rules below |
| SendCutSend bent 5052 shell | Product look; needs a 3D sheet-metal model; a later upgrade | SendCutSend rules below |
| 3D-printed body with a metal key plate | Fast iteration on a home printer; JLC3DP accepts STL, STEP, OBJ, 3MF | [JLC3DP](https://jlc3dp.com/3d-printing-quote) |

## SendCutSend design rules

### Files

| Rule | What SendCutSend says | Source |
| --- | --- | --- |
| Formats | 2D: DXF, DWG, AI, EPS. 3D: STEP or STP. Not accepted: STL and raster images; SVG and PDF only for custom quotes | [Sheet cutting guidelines](https://sendcutsend.com/guidelines/sheet-cutting/); [file format FAQ](https://sendcutsend.com/faq/what-file-formats-do-you-accept/) |
| Units and scale | "Inch units are preferred. Mm is fine if you keep it consistent between your file and your quote inputs. We don't support cm or meter units." Draw at exact size. | [Sheet cutting guidelines](https://sendcutsend.com/guidelines/sheet-cutting/) |
| Geometry | "Every cut path must form a closed shape." No shared or overlapping lines; strip dimensions, notes, borders, and title blocks; one layer | [Sheet cutting guidelines](https://sendcutsend.com/guidelines/sheet-cutting/) |
| Text | "Convert all text to outlines"; bridge floating centers (the inside of an O or A) | [Sheet cutting guidelines](https://sendcutsend.com/guidelines/sheet-cutting/) |
| Bent parts as STEP | One solid sheet-metal body using SendCutSend's own K-factor and bend radius | [Sheet cutting guidelines](https://sendcutsend.com/guidelines/sheet-cutting/); [bending calculator](https://sendcutsend.com/bending-calculator/) |

### Holes, slots, and edges

| Rule | Value | Source |
| --- | --- | --- |
| Minimum hole, laser (general) | At least 50% of material thickness | [Sheet cutting guidelines](https://sendcutsend.com/guidelines/sheet-cutting/) |
| Minimum hole, 5052 page | "Equal to material thickness (e.g., .125″ hole in .125″ sheet)" | [5052 aluminum](https://sendcutsend.com/materials/5052-aluminum/) |
| Minimum slot, 5052 page | "Material thickness or larger for clean results" | [5052 aluminum](https://sendcutsend.com/materials/5052-aluminum/) |
| Hole to edge, 5052 page | "Leave at least 2x thickness between a hole and an edge" | [5052 aluminum](https://sendcutsend.com/materials/5052-aluminum/) |
| Laser tolerance, 5052 | +/- 0.005 inch (0.127 mm) | [5052 aluminum](https://sendcutsend.com/materials/5052-aluminum/) |
| Sheet tolerance, 5052 at 0.063 inch | +/- 0.004 inch, so 1.50 to 1.70 mm | SendCutSend material data feed for the page's spec panel |
| Engraving | "We do not offer laser engraving or solid etching at this time." Single-line etching "cannot be combined with" anodizing. | [Etching FAQ](https://sendcutsend.com/faq/do-you-offer-laser-etching-or-laser-engraving/) |

Design to the stricter 1x-thickness hole and 2x-thickness edge rule. The per-thickness spec panels on the material pages list smaller absolute minimums (for 5052 at 0.063 inch: minimum hole 0.014 inch, recommended 0.022 inch, bridge 0.024 inch); treat those as hard limits only. Those panel values were read from the JSON feed the page's own script loads them from.

The 14 mm key cutout must hold +/- 0.05 mm, tighter than the +/- 0.127 mm laser tolerance, so order a test coupon first.

### Bending (for a later shell)

| Rule | Value | Source |
| --- | --- | --- |
| Bendable materials | 5052 aluminum, mild steel, 304 stainless, polycarbonate, and others; not 6061 aluminum and not acrylic | [Bending guidelines](https://sendcutsend.com/guidelines/bending/) |
| Bend radius | Fixed per material and thickness: "we don't offer custom bend radii" | same |
| 5052 at 0.063 inch | Bend radius 0.035 inch, K-factor 0.42, die width 0.472 inch, minimum flange 0.303 inch | [Bending calculator](https://sendcutsend.com/bending-calculator/); 5052 spec panel |
| Features near bends | "at least ½ the die width away from the centerline of each bend", so 0.236 inch for 5052 at 0.063 inch | [Bending guidelines](https://sendcutsend.com/guidelines/bending/) |
| Flange length | Minimum flange "for at least ~50-60% of the bend's length on both sides" | same |
| Angle | "No acute angles greater than 130°"; +/- 1 degree for bends up to 24 inch | same |
| Boxes | Max 3.00 inch flange on a 4-sided box with hardware, 5 inch without | same |

### Finishing and hardware

| Service | Key rule | Added time | Source |
| --- | --- | --- | --- |
| Anodizing | Type II; clear, black, blue, gold, red; 0.063 inch and thicker; "Adds only 0.0002 to 0.0009 inch per side"; hardware is installed after anodizing | 1 to 3 days for clear and black, 5 to 7 for colors | [Anodizing](https://sendcutsend.com/services/anodizing/) |
| Powder coat | Adds 0.002 to 0.005 inch per side, which shrinks a 14.00 mm key hole by up to about 0.25 mm | 3 to 5 days | [Powder coating](https://sendcutsend.com/services/powder-coating/) |
| Countersinking | "Materials must be at least 0.125 inch thick", so not on a 0.063 inch plate: use pan-head screws | 1 to 2 days | [Countersinking](https://sendcutsend.com/services/countersinking/) |
| Press-fit hardware | PEM nuts, standoffs, studs, metals only. Example: SO-M3-6 M3 standoff, 0.236 inch long, for 0.040 to 0.100 inch aluminum, 0.250 inch minimum from hole center to edge | 1 to 2 days | [Hardware](https://sendcutsend.com/services/hardware/); [catalog](https://sendcutsend.com/guidelines/hardware/catalog/) |
| Deburring | Linear deburring on metals | None | [Deburring](https://sendcutsend.com/services/deburring-services/) |

Decided finish (D21): **black anodize**. It barely changes hole size, unlike powder coat.

### Cost and lead time

- Pricing is an instant quote on upload; no public per-part prices. The closest published example: a 5052, 0.063 inch, 5.5 x 6 inch part with "Laser cutting, bending, deburring, hardware insertion, anodizing" at $55.24 for one and $16.06 each at 100 ([hardware page](https://sendcutsend.com/services/hardware/)). Helm's plate is about 210 x 125 mm (8.3 x 4.9 inch), so expect a similar order of cost **(estimate)**.
- "Free US shipping on orders of $39 or more" ([shipping](https://sendcutsend.com/shipping/)). Older SendCutSend pages mention a $39 order minimum; current checkout behavior under $39 is unverified.
- Cutting takes 2 to 4 days; bending adds 1 to 2, hardware 1 to 2, anodizing 1 to 3 for black ([processing times](https://sendcutsend.com/sendcutsend-processing-times/)).

## Labels (D21)

SendCutSend cannot put legends on an anodized part (no engraving; etching cannot be combined with anodizing). Use custom-legend keycaps ([parts.md](parts.md#custom-keycaps-decision-d21)) plus a printed label strip on the plate for the knob and light bar.

## Steps

These steps are for the superseded 1595E plan; [`case/README.md`](../../case/README.md#order-plan) has the order plan for the case sized to the parts.

1. Bench first: phase 1 runs on a breadboard, not in a case.
2. Buy the 1595E and measure the slope angle and the depth under the front of the slope. The keys need roughly 12 mm below the plate (Cherry's 5.0 mm plate-to-PCB plus the socket board) and the module 14.5 mm plus its bracket **(estimate)**; if the front is too shallow, move the keys up the slope.
3. First SendCutSend order, raw and unfinished: a test coupon with key holes at 13.95, 14.00, 14.05, and 14.10 mm, knob holes at 7.2 and 7.5 mm, and one module window size, plus a first full plate. Together they should clear $39.
4. Second order: the corrected plate, black anodized, with SO-M3-6 standoffs for the module bracket, the Perma-Proto, and the knob board, plus the flat module bracket.
5. Add the label strip and the custom keycaps.

Case cost estimate (not quoted): box $16.36, two plate orders plus the bracket roughly $80 to $110 together **(estimate)**.

## Not verified

- SendCutSend's price for this plate and bracket (needs a file upload).
- The 1595E's slope angle and front depth.
- The P4 module's rear-hole thread size and the right window size.
- The encoder panel-hole size and knob fit.
- Whether M3 tapping is offered in 0.063 inch 5052 (press-fit hardware is the safe choice).
