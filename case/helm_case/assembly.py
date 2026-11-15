"""The metal case assembled with its printed parts and stand-ins for the
bought parts.

Stand-ins are simple boxes and cylinders at the vendor (or assumed) sizes in
params.py. They exist for two jobs: the interference check, which proves the
parts fit the case, and the preview renders.
"""

import math
from dataclasses import dataclass

import cadquery as cq

from . import logo, printed, sheet
from . import params as P
from .layout import window_centre
from .printed import plate_box, plate_cyl, to_case

# preview colours (r, g, b)
ANODIZED = (0.16, 0.16, 0.17)
ENGRAVED = (0.82, 0.82, 0.80)
PRINTED = (0.20, 0.21, 0.23)
MODULE = (0.05, 0.05, 0.06)
SCREEN = (0.10, 0.22, 0.40)
KEYCAP = (0.08, 0.08, 0.09)
LEGEND = (0.92, 0.92, 0.90)
WHITE = (0.95, 0.80, 0.45)
PCB = (0.10, 0.30, 0.15)
STEEL = (0.65, 0.66, 0.68)
FOAM = (0.15, 0.15, 0.15)
CABLE = (0.55, 0.55, 0.58)
SPEAKER = (0.35, 0.30, 0.25)


@dataclass
class Item:
    name: str
    shape: object
    color: tuple
    kind: str  # "case" (made here), "part" (bought), "hw" (fasteners), "wire" (the harness), "space" (room kept for spare wire), "look" (render only)
    through: tuple = ()  # items this one passes through by design, such as header pins through their board


def _p(shape):
    return to_case(shape)


def bought_parts(keycap=None, back_wall_t=P.SHEET_T):
    """Stand-ins for the bought parts under and on the face.
    keycap: (square base, height) of the caps, default the chosen flat caps;
    the fit check also runs with the largest aluminum cap envelope.
    back_wall_t: the cover's back wall, which the jack's nut sits behind."""
    t = P.SHEET_T
    cap_size, cap_height = keycap or (P.KEYCAP, P.KEYCAP_HEIGHT)
    items = []
    mx, mv = P.MODULE_X, P.MODULE_V
    msx, msv = P.MODULE_SX, P.MODULE_SV
    items.append(Item("module", _p(plate_box(mx, mx + msx, mv, mv + msv, -t - P.MODULE_THICKNESS, -t)), MODULE, "part"))
    c = window_centre()
    sx, sv = P.TOUCH_X, P.TOUCH_V
    items.append(Item("screen", _p(plate_box(c[0] - sx / 2, c[0] + sx / 2, c[1] - sv / 2, c[1] + sv / 2, -t, -t + 0.05)), SCREEN, "look"))

    # keys: switch, NeoKey board, socket and wires below; switch top and cap above
    for i, x in enumerate(P.KEY_XS):
        v = P.KEY_V
        nx, nv = P.NEOKEY_PCB
        pcb_top = -P.KEY_PLATE_TO_PCB
        items.append(Item(f"switch{i}", _p(plate_box(x - 7, x + 7, v - 7, v + 7, pcb_top, -t)), (0.2, 0.2, 0.2), "part"))
        items.append(Item(f"neokey{i}", _p(plate_box(x - nx / 2, x + nx / 2, v - nv / 2, v + nv / 2, pcb_top - P.NEOKEY_PCB_THICKNESS, pcb_top)), PCB, "part"))
        items.append(Item(f"keywires{i}", _p(plate_box(x - nx / 2 + 1, x + nx / 2 - 1, v - nv / 2 + 1, v + nv / 2 - 1, -P.KEY_STACK_DEPTH, pcb_top - P.NEOKEY_PCB_THICKNESS)), (0.3, 0.3, 0.3), "part"))
        rows = (v + P.NEOKEY_PIN_ROW, v - P.NEOKEY_PIN_ROW)
        pins = header_pins(x, rows, P.NEOKEY_ROW_PINS, pcb_top, P.NEOKEY_PCB_THICKNESS)
        items.append(Item(f"keypins{i}", pins, STEEL, "part", through=(f"neokey{i}", f"keywires{i}")))
        items.append(Item(f"switchtop{i}", _p(plate_box(x - 7.8, x + 7.8, v - 7.8, v + 7.8, 0, P.SWITCH_TOP_HEIGHT)), (0.2, 0.2, 0.2), "part"))
        # the cap sits on the switch's MX cross stem, just clear of the housing
        k, top = cap_size, P.SWITCH_TOP_HEIGHT + 0.4 + cap_height
        cap = plate_box(x - k / 2, x + k / 2, v - k / 2, v + k / 2, P.SWITCH_TOP_HEIGHT + 0.4, top)
        cap = _fillet(cap, "|Z", 1.5)
        items.append(Item(f"keycap{i}", _p(cap), KEYCAP, "part"))
        items.append(Item(f"legend{i}", _p(_legend(i, x, v, top)), LEGEND, "look"))

    # knob: encoder body under the face, board below, knob above
    ex, ev = P.KNOB_X, P.KNOB_V
    body = plate_box(ex - P.ENCODER_BODY[0] / 2, ex + P.ENCODER_BODY[0] / 2, ev - P.ENCODER_BODY[1] / 2, ev + P.ENCODER_BODY[1] / 2, -P.SHEET_T - P.ENCODER_BODY_HEIGHT, -P.SHEET_T)
    body = body.rotate(cq.Vector(ex, ev, 0), cq.Vector(ex, ev, 1), 45)
    items.append(Item("encoder", _p(body), (0.6, 0.6, 0.62), "part"))
    b = P.ENCODER_BOARD
    pcb_w = -P.SHEET_T - P.ENCODER_BODY_HEIGHT
    items.append(Item("encoder_board", _p(plate_box(ex - b / 2, ex + b / 2, ev - b / 2, ev + b / 2, pcb_w - 1.6, pcb_w)), PCB, "part"))
    items.append(Item("encoder_parts", _p(plate_box(ex - b / 2 + 2, ex + b / 2 - 2, ev - b / 2 + 2, ev + b / 2 - 2, pcb_w - 5.0, pcb_w - 1.6)), (0.3, 0.3, 0.3), "part"))
    pins = header_pins(ex, (ev + P.KNOB_PIN_ROW,), P.KNOB_ROW_PINS, pcb_w, 1.6)
    items.append(Item("knobpins", pins, STEEL, "part", through=("encoder_board", "encoder_parts")))
    knob = plate_cyl(ex, ev, P.KNOB_D / 2, 1.0, 1.0 + P.KNOB_HEIGHT)
    knob = _fillet(knob, ">Z", 1.0, faces=True)
    items.append(Item("knob", _p(knob), (0.12, 0.12, 0.13), "part"))
    items.append(Item("knob_mark", _p(plate_box(ex - 0.6, ex + 0.6, ev + 4, ev + 8.5, 1.0 + P.KNOB_HEIGHT, 1.05 + P.KNOB_HEIGHT)), LEGEND, "look"))

    # speaker
    bx, bv, bh = P.SPEAKER_BOX
    items.append(Item("speaker", _p(plate_box(P.SPEAKER_X - bx / 2, P.SPEAKER_X + bx / 2, P.SPEAKER_V - bv / 2, P.SPEAKER_V + bv / 2, -t - bh, -t)), SPEAKER, "part"))

    # NeoPixel stick in its holder, LEDs up
    sx, sv = P.LIGHT_STICK
    top = -t - P.LIGHT_DIFFUSER
    items.append(Item("light_stick", _p(plate_box(P.LIGHT_X - sx / 2, P.LIGHT_X + sx / 2, P.LIGHT_V - sv / 2, P.LIGHT_V + sv / 2, top - P.LIGHT_STICK_THICKNESS, top)), PCB, "part"))

    # The 40-pin header socket on the board's back, and the harness plug
    # pushed into it from below with its wires' turn
    # (the module's box already holds the socket's first 4 mm)
    hx0, hx1, hv0, hv1 = header_rect()
    w_low = -t - P.MODULE_PCB_REAR - P.HEADER_HEIGHT
    items.append(Item("header", _p(plate_box(hx0, hx1, hv0, hv1, w_low, -t - P.MODULE_THICKNESS)), MODULE, "part"))
    items.append(Item("header_plugs", _p(plate_box(hx0, hx1, hv0, hv1, w_low - P.HEADER_PLUGS, w_low)), CABLE, "part"))

    # The flashing cable in the "USB TO UART" receptacle, through the left
    # wall's service slot; the overmold starts at the module edge
    ow, oh = P.USB_PLUG_OVERMOLD
    w_usb = -t - P.MODULE_USB_DEPTH
    v = P.MODULE_V + P.MODULE_USB_UART
    plug = plate_box(mx - 22, mx, v - ow / 2, v + ow / 2, w_usb - oh / 2, w_usb + oh / 2)
    items.append(Item("flash_plug", _p(_fillet(plug, "|X", oh / 2 - 0.01)), CABLE, "part"))
    items += usb_link_parts(t, back_wall_t, t)
    return items


def header_pins(cx, rows, n, pcb_top, pcb_t):
    """Extra-long header pins soldered with their plastic under a board whose
    top is at plate w pcb_top, trimmed to PIN_TRIM_TOP above it and
    PIN_TRIM_TAIL below the plastic: one row of n pins along x, centred on
    cx, at each plate v in rows. The plastic itself is not modelled."""
    h, top = P.HEADER_PIN / 2, pcb_top + P.PIN_TRIM_TOP
    bottom = pcb_top - pcb_t - P.HEADER_BODY - P.PIN_TRIM_TAIL
    xs = [cx + (k - (n - 1) / 2) * 2.54 for k in range(n)]
    return cq.Compound.makeCompound([_p(plate_box(x - h, x + h, v - h, v + h, bottom, top)) for v in rows for x in xs])


def socket_pin(n):
    """Plate (x, v) of pin n of the 40-pin header: Waveshare's numbering,
    odd pins on the row nearer the board's edge, pins 1 and 2 at the end away
    from the USB-C edge."""
    pcb_far_x = P.MODULE_X + P.MODULE_PCB_INSET_USB + P.MODULE_PCB[0]
    pcb_back_v = P.MODULE_V + P.MODULE_SV - P.MODULE_PCB_INSET_V
    outer, inner = P.HEADER_ROWS_IN
    return pcb_far_x - P.HEADER_PIN1_FROM_FAR_EDGE - (n - 1) // 2 * 2.54, pcb_back_v - (outer if n % 2 else inner)


def header_rect():
    """Plate (x0, x1, v0, v1) of the 40-pin header's socket body."""
    pin1_x = socket_pin(1)[0]
    x0, x1 = pin1_x - 19 * 2.54 - 1.27 - 0.5, pin1_x + 1.27 + 0.5
    rows = [socket_pin(1)[1], socket_pin(2)[1]]
    return x0, x1, min(rows) - 1.27 - 0.5, max(rows) + 1.27 + 0.5


def usb_link_parts(plate_t, wall_t, floor_z):
    """The everyday USB-C path: the panel jack low in the back wall, its lead
    to the breakout under the cradle plate, and the slim ribbon from the
    breakout to the module's native USB port. wall_t is the back wall's
    thickness, floor_z the top of the floor."""
    items = []
    # panel jack: flange outside, body through the wall, nut inside
    jx, jz, depth = P.BACK_JACK_X, P.BACK_JACK_Z, P.DEPTH
    fd, ft = P.BACK_JACK_FLANGE
    flange = cq.Solid.makeCylinder(fd / 2, ft, cq.Vector(jx, depth, jz), cq.Vector(0, 1, 0))
    body = cq.Solid.makeCylinder(P.BACK_JACK_BODY_D / 2, P.BACK_JACK_LENGTH, cq.Vector(jx, depth - P.BACK_JACK_LENGTH, jz), cq.Vector(0, 1, 0))
    items.append(Item("back_jack", flange.fuse(body), MODULE, "part"))
    af, nt = P.BACK_JACK_NUT
    nut = cq.Workplane("XY").polygon(6, af / math.cos(math.radians(30))).extrude(nt).val()
    nut = nut.cut(cq.Solid.makeCylinder(P.BACK_JACK_BODY_D / 2 + 0.1, nt + 2, cq.Vector(0, 0, -1)))
    nut = nut.rotate(cq.Vector(0, 0, 0), cq.Vector(1, 0, 0), -90).translate(cq.Vector(jx, depth - wall_t - nt, jz))
    items.append(Item("back_jack_nut", nut, STEEL, "hw"))

    # breakout on foam tape under the cradle plate, hanging pads down,
    # receptacle facing the left wall
    bx, bv = P.BREAKOUT_XV
    bl, bw, bh = P.BREAKOUT
    w_tape = sheet.cradle_underside_w() - P.BREAKOUT_TAPE
    items.append(Item("usb_breakout", _p(plate_box(bx, bx + bl, bv, bv + bw, w_tape - bh, w_tape)), PCB, "part"))
    # the lead from the jack's inner end along the breakout's underside to its
    # pad row (along the long edge away from the receptacle), where it is
    # soldered on
    lead_r = P.BACK_JACK_LEAD_D / 2
    start = (jx, depth - P.BACK_JACK_LENGTH - lead_r, jz)
    end = P.plate_to_case(bx + bl - P.BREAKOUT_PADS_IN, bv + bw / 2, w_tape - bh - lead_r - 0.1)
    lead = tube((start,) + P.JACK_LEAD_PATH + (end,), lead_r)
    items.append(Item("jack_lead", lead, CABLE, "part", through=("usb_breakout",)))
    (x0, x1), (y0, y1), (z0, z1) = P.JACK_LOOP
    items.append(Item("jack_loop", cq.Solid.makeBox(x1 - x0, y1 - y0, z1 - z0, cq.Vector(x0, y0, z0)), CABLE, "space", through=("jack_lead",)))

    # slim ribbon: one plug in H2, a straight drop beside the module, the
    # other plug in the breakout
    hl, hn, hh = P.RIBBON_PLUG_HEAD
    x0 = P.MODULE_X
    v = P.MODULE_V + P.MODULE_USB_NATIVE
    w = -plate_t - P.MODULE_USB_DEPTH
    items.append(Item("ribbon_plug_native", _p(plate_box(x0 - hh, x0, v - hl / 2, v + hl / 2, w - hn / 2, w + hn / 2)), STEEL, "part"))
    xr = x0 - hh / 2
    w_end = (floor_z + P.RIBBON_DROP_END - P.FRONT_HEIGHT - v * math.sin(P.SLOPE)) / math.cos(P.SLOPE)
    rt, rw = P.RIBBON_THICKNESS, P.RIBBON_WIDTH
    items.append(Item("ribbon", _p(plate_box(xr - rt / 2, xr + rt / 2, v - rw / 2, v + rw / 2, w_end, w - hn / 2)), MODULE, "part"))
    wc = w_tape - P.BREAKOUT_USB_HEIGHT
    items.append(Item("ribbon_plug_breakout", _p(plate_box(bx - hh, bx, bv + bw / 2 - hl / 2, bv + bw / 2 + hl / 2, wc - hn / 2, wc + hn / 2)), STEEL, "part"))
    # the ribbon's turn from the drop to the breakout plug, render only
    drop_end = P.plate_to_case(xr, v, w_end)
    a, b = cq.Vector(*drop_end), cq.Vector(*P.plate_to_case(bx - hh / 2, bv + bw / 2, wc - hn / 2))
    items.append(Item("ribbon_turn", cq.Solid.makeCylinder(1.0, (b - a).Length, a, b - a), MODULE, "look"))
    # its spare length, folded flat under the cradle plate behind the breakout
    (fx0, fx1), (fv0, fv1), (fw0, fw1) = P.RIBBON_FOLD
    items.append(Item("ribbon_fold", _p(plate_box(fx0, fx1, fv0, fv1, fw0, fw1)), MODULE, "space"))

    # the everyday cable from the Mac, render only
    ow, oh = P.USB_PLUG_OVERMOLD
    plug = cq.Solid.makeBox(ow, 22, oh, cq.Vector(jx - ow / 2, depth + ft, jz - oh / 2))
    items.append(Item("mac_plug", _fillet(plug, "|Y", oh / 2 - 0.01), CABLE, "look"))
    items.append(Item("mac_cable", cq.Solid.makeCylinder(2.0, 40, cq.Vector(jx, depth + ft + 22, jz), cq.Vector(0, 1, 0)), CABLE, "look"))
    return items


def tube(points, r):
    """A round wire or bundle of radius r along a polyline of case-frame
    points, with a ball at each bend."""
    pts = [cq.Vector(*p) for p in points]
    parts = [cq.Solid.makeCylinder(r, (b - a).Length, a, b - a) for a, b in zip(pts, pts[1:])]
    parts += [cq.Solid.makeSphere(r, p, angleDegrees1=-90, angleDegrees2=90) for p in pts[1:-1]]
    return parts[0].fuse(*parts[1:]).clean() if len(parts) > 1 else parts[0]


# The harness wires beyond the bundles' ends, each to just short of the pin or
# rail it is soldered to (plate x, v, w): the trunk's 5 key wires (YES I, then
# the A pins of YES, LATER, HOLD and SHOW ME) and its 2 power wires (strip +
# and -), and the knob bundle's 4 wires (VIN, SDA, SCL, GND). The last stretch
# into each pin or rail is left out: it ends inside its part.
def _trunk_branches():
    kx, pin = P.KEY_XS, P.NEOKEY_PIN_X
    keys = [((36.0, 34.0, -16.0), (kx[0] + pin["IO"], 27.0, -12.0))]  # 27.0: behind the I rows, below the speaker holder
    keys += [((x0, 33.0, -16.0), (x + pin["A"], 27.0, -12.0)) for x0, x in zip((34.0, 50.0, 64.0, 79.0), kx)]
    rails = [((x, 46.0, -12.0), (x, 42.0, -8.0)) for x in P.STRIP_RAILS]
    return keys + rails


def _knob_branches():
    pin_x = {name: P.KNOB_X + (k - (P.KNOB_ROW_PINS - 1) / 2) * 2.54 for k, name in enumerate(("INT", "SDA", "SCL", "GND", "3Vo", "VIN"))}
    return [((pin_x[name], 31.0, -15.5),) for name in ("VIN", "SDA", "SCL", "GND")]


def _harness(pins, path, bundle_d, branches):
    """One harness channel: the wires leave the plug at the end of its tails,
    run together as a bundle along path, and split there to their parts."""
    w_tails = -P.SHEET_T - P.MODULE_PCB_REAR - P.HEADER_HEIGHT - P.HEADER_PLUGS + P.PLUG_TURN
    xs, vs = zip(*(socket_pin(n) for n in pins))
    start = (sum(xs) / len(xs), sum(vs) / len(vs), w_tails)
    shape = tube([P.plate_to_case(*p) for p in (start,) + path], bundle_d / 2)
    wires = [tube([P.plate_to_case(*p) for p in (path[-1],) + b], P.HARNESS_WIRE_D / 2) for b in branches]
    return shape.fuse(*wires).clean()


def wiring_items(face_t):
    """The wiring inside the case that the fit check keeps room for: the power
    strip under the face, and the harness from the plug in the 40-pin socket
    under the cradle plate: the trunk to the keys and the strip, and the knob
    bundle. face_t is the face's thickness where the strip sticks on."""
    x0, x1 = P.STRIP_X
    v0, v1 = P.STRIP_V
    strip = plate_box(x0, x1, v0, v1, -face_t - P.STRIP_FOAM - P.STRIP_BOARD, -face_t)
    trunk = _harness((1, 5, 11, 12, 14, 15, 17), P.TRUNK_PATH, P.TRUNK_D, _trunk_branches())
    knob = _harness((2, 4, 6, 10), P.KNOB_PATH, P.KNOB_BUNDLE_D, _knob_branches())
    return [
        Item("power_strip", _p(strip), PCB, "part"),
        Item("harness_trunk", trunk, CABLE, "wire", through=("header_plugs",)),
        Item("harness_knob", knob, CABLE, "wire", through=("header_plugs",)),
    ]


def _fillet(shape, selector, r, faces=False):
    wp = cq.Workplane().add(shape)
    wp = wp.faces(selector).edges() if faces else wp.edges(selector)
    return wp.fillet(r).val()


def _stroke(p0, p1, w, width=1.2):
    """Flat bar from p0 to p1 (plate x, v) lying on the plane w, round ends."""
    length = ((p1[0] - p0[0]) ** 2 + (p1[1] - p0[1]) ** 2) ** 0.5
    angle = math.degrees(math.atan2(p1[1] - p0[1], p1[0] - p0[0]))
    bar = plate_box(0, length, -width / 2, width / 2, w, w + 0.05)
    bar = bar.fuse(plate_cyl(0, 0, width / 2, w, w + 0.05), plate_cyl(length, 0, width / 2, w, w + 0.05))
    return bar.rotate(cq.Vector(0, 0, 0), cq.Vector(0, 0, 1), angle).translate(cq.Vector(p0[0], p0[1], 0))


def _legend(i, x, v, w):
    """Simple raised icons on the key tops, standing in for the paper inserts."""
    if i == 0:  # check mark: YES
        return _stroke((x - 4.0, v + 0.5), (x - 1.3, v - 2.5), w).fuse(_stroke((x - 1.3, v - 2.5), (x + 4.5, v + 3.5), w))
    if i == 1:  # clock face: LATER
        ring = plate_cyl(x, v, 4.5, w, w + 0.05).cut(plate_cyl(x, v, 3.4, w - 1, w + 1))
        return ring.fuse(plate_box(x - 0.5, x + 0.5, v, v + 3, w, w + 0.05), plate_box(x, x + 2.5, v - 0.5, v + 0.5, w, w + 0.05))
    if i == 2:  # pause bars: HOLD
        return plate_box(x - 3, x - 1.2, v - 4, v + 4, w, w + 0.05).fuse(plate_box(x + 1.2, x + 3, v - 4, v + 4, w, w + 0.05))
    eye = plate_cyl(x, v, 4.8, w, w + 0.05).cut(plate_cyl(x, v, 3.8, w - 1, w + 1))  # SHOW ME
    return eye.fuse(plate_cyl(x, v, 1.8, w, w + 0.05))


def cradle_items():
    """The printed cradle under the module on four legs, each screwed up
    through the floor into a heat-set insert, with foam between the module's
    back and the cradle, and the locating tabs around the glass."""
    t = P.SHEET_T
    w_back = -t - P.MODULE_THICKNESS
    x0, x1, v0, v1 = printed.cradle_plate_rect()
    foam = Item("cradle_foam", _p(plate_box(x0 + 4, x1 - 4, v0 + 4, v1 - 4, w_back - P.CRADLE_FOAM, w_back)), FOAM, "part")
    tabs = [Item(f"cradle_tab{i}", tab, PRINTED, "case") for i, tab in enumerate(printed.cradle_tabs())]
    return [Item("cradle", printed.cradle(), PRINTED, "case"), foam] + tabs


def logo_item():
    """The engraved logo as a thin skin on the face (render only)."""
    faces = []
    for poly in getattr(logo.placed(), "geoms", [logo.placed()]):
        outer = cq.Wire.makePolygon([cq.Vector(x, v, 0) for x, v in poly.exterior.coords], close=True)
        inner = [cq.Wire.makePolygon([cq.Vector(x, v, 0) for x, v in r.coords], close=True) for r in poly.interiors]
        faces.append(cq.Solid.extrudeLinear(cq.Face.makeFromWires(outer, inner), cq.Vector(0, 0, 0.05)))
    return Item("logo", _p(cq.Compound.makeCompound(faces)), ENGRAVED, "look")


def metal_items(keycap=None):
    """Every part of the metal build. keycap: see bought_parts."""
    t = P.SHEET_T
    items = [
        Item("cover", sheet.cover_solid(), ANODIZED, "case"),
        Item("base", sheet.base_solid(), ANODIZED, "case"),
        Item("light_holder", to_case(printed.light_holder(t)), WHITE, "case"),
        Item("speaker_holder", to_case(printed.speaker_holder(t)), PRINTED, "case"),
    ]
    items += cradle_items()
    for y in (P.BASE_SCREW_Y, P.DEPTH - P.BASE_SCREW_Y):
        for x in P.BASE_SCREWS_X:
            items.append(Item(f"flangenut{len(items)}", cq.Solid.makeCylinder(3.0, P.S_M3_PROUD, cq.Vector(x, y, 2 * t)), STEEL, "hw"))
    items += bought_parts(keycap)
    items += wiring_items(t)
    items.append(logo_item())
    return items


def printed_items(keycap=None):
    """Every part of the printed test enclosure: the printed cover and base
    with the same printed parts and bought parts as the metal build. The
    flange inserts sit inside their holes and are not modelled."""
    t = P.SHEET_T
    items = [
        Item("print_cover", printed.printed_cover(), PRINTED, "case"),
        Item("print_base", printed.printed_base(), PRINTED, "case"),
        Item("light_holder", to_case(printed.light_holder(t)), WHITE, "case"),
        Item("speaker_holder", to_case(printed.speaker_holder(t)), PRINTED, "case"),
    ]
    items += cradle_items()
    items += bought_parts(keycap, back_wall_t=P.PRINT_WALL)
    items += wiring_items(P.PRINT_WALL)
    return items


def interference(items, tol=0.01):
    """Pairs of items whose solids overlap by more than tol cubic mm.
    Items marked "look" are render-only and skipped, and so are pairs one of
    which names the other in its through list."""
    solid = [it for it in items if it.kind != "look"]
    boxes = [it.shape.BoundingBox() for it in solid]
    hits = []
    for i in range(len(solid)):
        for j in range(i + 1, len(solid)):
            a, b = boxes[i], boxes[j]
            if a.xmax < b.xmin or b.xmax < a.xmin or a.ymax < b.ymin or b.ymax < a.ymin or a.zmax < b.zmin or b.zmax < a.zmin:
                continue
            if solid[j].name in solid[i].through or solid[i].name in solid[j].through:
                continue
            vol = solid[i].shape.intersect(solid[j].shape).Volume()
            if vol > tol:
                hits.append((solid[i].name, solid[j].name, vol))
    return hits
