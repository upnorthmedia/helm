"""Printed parts: inside the metal case, the module's cradle and its locating
tabs, the light bar holder and the speaker holder; a printable copy of the
test coupon; and the printed test enclosure, a cover and base that stand in
for the metal ones on the bench."""

import math

import cadquery as cq

from . import params as P
from . import sheet
from .geom2d import FlatPart, extrude_part, rounded_rect
from .layout import face_cuts

PLATE_LOC = cq.Location(cq.Vector(0, 0, P.FRONT_HEIGHT), cq.Vector(1, 0, 0), P.SLOPE_DEG)


def plate_box(x0, x1, v0, v1, w0, w1):
    """Axis-aligned box in plate coordinates, left in plate coordinates."""
    return cq.Solid.makeBox(x1 - x0, v1 - v0, w1 - w0, cq.Vector(x0, v0, w0))


def plate_cyl(x, v, r, w0, w1):
    return cq.Solid.makeCylinder(r, w1 - w0, cq.Vector(x, v, w0))


def to_case(shape):
    return shape.moved(PLATE_LOC)


def light_holder(plate_t=P.SHEET_T):
    """White holder for the NeoPixel stick. Its tongue fills the face's light
    window, so the bar reads as a lit strip flush with the face. Modelled in
    plate coordinates around the window centre."""
    hx, hv = P.LIGHT_HOLDER
    depth = P.LIGHT_HOLDER_DEPTH
    cx, cv = P.LIGHT_X, P.LIGHT_V
    block = plate_box(cx - hx / 2, cx + hx / 2, cv - hv / 2, cv + hv / 2, -plate_t - depth, -plate_t)
    sx, sv = P.LIGHT_STICK
    pocket = plate_box(cx - sx / 2 - 0.25, cx + sx / 2 + 0.25, cv - sv / 2 - 0.25, cv + sv / 2 + 0.25, -plate_t - depth - 1, -plate_t - P.LIGHT_DIFFUSER)
    wx, wv = P.LIGHT_WINDOW
    tongue_face = rounded_rect(cx, cv, wx - 0.4, wv - 0.4, max(P.LIGHT_WINDOW_RADIUS - 0.2, 0.1))
    tongue = extrude_part(FlatPart("t", tongue_face), plate_t - 0.2).translate(cq.Vector(0, 0, -plate_t))
    return block.cut(pocket).fuse(tongue).clean()


def speaker_holder(t=P.SHEET_T):
    """Rectangular frame (gasket) bonded under the face around the oval
    speaker, so the speaker sits sealed against the slots."""
    bx, bv, bh = P.SPEAKER_BOX
    wl = P.SPEAKER_HOLDER_WALL
    outer = plate_box(P.SPEAKER_X - bx / 2 - wl, P.SPEAKER_X + bx / 2 + wl, P.SPEAKER_V - bv / 2 - wl, P.SPEAKER_V + bv / 2 + wl, -t - bh - 1.0, -t)
    return outer.cut(plate_box(P.SPEAKER_X - bx / 2, P.SPEAKER_X + bx / 2, P.SPEAKER_V - bv / 2, P.SPEAKER_V + bv / 2, -t - bh - 2, -t + 1))


def cradle_plate_rect():
    """Plate (x0, x1, v0, v1) of the cradle's plate, under the module: it
    stops short of the 40-pin header so jumper plugs can go in from below."""
    from .assembly import header_rect

    mx, mv, msx = P.MODULE_X, P.MODULE_V, P.MODULE_SX
    return mx + 4.0, mx + msx - 4.0, mv + P.CRADLE_INSET, header_rect()[2] - P.CRADLE_HEADER_GAP


def _tab_frames():
    """For each locating tab: its plate Location, and how far its arm
    reaches in from the glass edge to overlap the cradle's plate. The tab's
    local frame is x outward from the glass edge, y along it (centred), and
    z the plate's w."""
    mx, mv, msx, msv = P.MODULE_X, P.MODULE_V, P.MODULE_SX, P.MODULE_SV
    x0, x1, v0, v1 = cradle_plate_rect()
    edges = {  # translation of the tab's centre on the glass edge, rotation, reach
        "right": (lambda c: (mx + msx, mv + c), 0, mx + msx - x1),
        "left": (lambda c: (mx, mv + c), 180, x0 - mx),
        "back": (lambda c: (mx + c, mv + msv), 90, mv + msv - v1),
        "front": (lambda c: (mx + c, mv), 270, v0 - mv),
    }
    out = []
    for edge, c in P.CRADLE_TABS:
        at, angle, reach = edges[edge]
        x, v = at(c)
        out.append((cq.Location(cq.Vector(x, v, 0), cq.Vector(0, 0, 1), angle), reach + 2.0))
    return out


def cradle_tab():
    """One locating tab in its local frame (see _tab_frames): a bar beside
    the glass from the cradle's top up to just under the face, with a tongue
    that goes down through the slot in the cradle's arm. The tongue is flush
    with the glass side and narrower than the bar, so the bar's shoulder
    sits on the arm."""
    g, t, tab_l, tongue = P.CRADLE_TAB_GAP, P.CRADLE_TAB_T, P.CRADLE_TAB_L, P.CRADLE_TAB_TONGUE
    w_low = sheet.cradle_underside_w()
    w_arm = w_low + P.CRADLE_T
    bar = cq.Solid.makeBox(t, tab_l, -P.SHEET_T - P.CRADLE_TAB_TOP - w_arm, cq.Vector(g, -tab_l / 2, w_arm))
    tl = tab_l - 2.0
    return bar.fuse(cq.Solid.makeBox(tongue, tl, P.CRADLE_T, cq.Vector(g, -tl / 2, w_low))).clean()


def cradle_tabs():
    """The locating tabs placed in the case frame."""
    return [to_case(cradle_tab().moved(loc)) for loc, _ in _tab_frames()]


def cradle_tab_for_print():
    """A tab lying on its glass side."""
    return cradle_tab().rotate(cq.Vector(0, 0, 0), cq.Vector(0, 1, 0), -90)


def cradle(insert_holes=True):
    """The printed cradle in the case frame: a plate under the module on four
    legs standing on the floor. Each leg takes a heat-set insert from below
    for a screw up through the floor. Arms reach out past the glass edges and
    carry the slots for the locating tabs."""
    t = P.SHEET_T
    w_low = sheet.cradle_underside_w()
    x0, x1, v0, v1 = cradle_plate_rect()
    plate = to_case(plate_box(x0, x1, v0, v1, w_low, w_low + P.CRADLE_T))
    legs, holes = [], []
    for (x, v), (_, y) in zip(P.cradle_leg_points(), sheet.cradle_leg_xy()):
        # From the floor's top up into the sloped plate: 1.5 mm past the
        # plate's underside at the leg's centre stays inside the plate across
        # the leg's whole width.
        z_top = P.plate_to_case(x, v, w_low)[2] + 1.5
        legs.append(cq.Solid.makeCylinder(P.CRADLE_LEG_D / 2, z_top - t, cq.Vector(x, y, t)))
        holes.append(cq.Solid.makeCylinder(P.PRINT_INSERT_D / 2, P.PRINT_INSERT_DEPTH + 1, cq.Vector(x, y, t - 1)))
    arms, slots = [], []
    g, tab_l, c = P.CRADLE_TAB_GAP, P.CRADLE_TAB_L, P.CRADLE_TAB_SLOT_CLEAR
    for loc, reach in _tab_frames():
        arm = cq.Solid.makeBox(reach + g + P.CRADLE_TAB_T, tab_l + 2.0, P.CRADLE_T, cq.Vector(-reach, -(tab_l + 2.0) / 2, w_low))
        arms.append(to_case(arm.moved(loc)))
        tl = tab_l - 2.0 + 2 * c
        slot = cq.Solid.makeBox(P.CRADLE_TAB_TONGUE + 2 * c, tl, P.CRADLE_T + 2, cq.Vector(g - c, -tl / 2, w_low - 1))
        slots.append(to_case(slot.moved(loc)))
    solid = plate.fuse(*legs, *arms).cut(*slots)
    if insert_holes:
        solid = solid.cut(*holes)
    return solid.clean()


def cradle_for_print():
    """The cradle turned so its module side lies on the bed: the legs then
    lean 15 degrees from vertical, which prints without supports."""
    return cradle().moved(PLATE_LOC.inverse).rotate(cq.Vector(0, 0, 0), cq.Vector(1, 0, 0), 180)


def coupon(flat):
    """Printable coupon: the metal coupon at Cherry's 1.5 mm plate thickness,
    with a stiffening rim around the edge."""
    plate = extrude_part(flat, 1.5)
    w, h = P.COUPON_SIZE
    rim_out = extrude_part(FlatPart("o", flat.outline), 3.0)
    rim_in = extrude_part(FlatPart("i", rounded_rect(w / 2, h / 2, w - 4, h - 4, 1.0)), 5.0).translate(cq.Vector(0, 0, -1))
    return plate.fuse(rim_out.cut(rim_in)).clean()


# ---------------------------------------------------------------------------
# Printed test enclosure: the metal cover and base as prints, for fitting
# every part on the bench before ordering metal
# ---------------------------------------------------------------------------
def _face_pockets(t):
    """Plate-frame cutters that take the printed face back to the metal's
    thickness wherever a part bears on its underside: the module and its
    locating tabs, the switches, the encoder, the speaker and light holders."""
    g, w0, w1 = P.PRINT_POCKET_GAP, -t - 1, -P.SHEET_T
    m = P.CRADLE_TAB_GAP + P.CRADLE_TAB_T + g
    mx, mv = P.MODULE_X, P.MODULE_V
    cuts = [plate_box(mx - m, mx + P.MODULE_SX + m, mv - m, mv + P.MODULE_SV + m, w0, w1)]
    k = P.KEY_HOLE / 2 + g
    cuts += [plate_box(x - k, x + k, P.KEY_V - k, P.KEY_V + k, w0, w1) for x in P.KEY_XS]
    cuts.append(plate_cyl(P.KNOB_X, P.KNOB_V, math.hypot(*P.ENCODER_BODY) / 2 + g, w0, w1))
    bx, bv, _ = P.SPEAKER_BOX
    sx, sv = bx / 2 + P.SPEAKER_HOLDER_WALL + g, bv / 2 + P.SPEAKER_HOLDER_WALL + g
    cuts.append(plate_box(P.SPEAKER_X - sx, P.SPEAKER_X + sx, P.SPEAKER_V - sv, P.SPEAKER_V + sv, w0, w1))
    hx, hv = P.LIGHT_HOLDER[0] / 2 + g, P.LIGHT_HOLDER[1] / 2 + g
    cuts.append(plate_box(P.LIGHT_X - hx, P.LIGHT_X + hx, P.LIGHT_V - hv, P.LIGHT_V + hv, w0, w1))
    return cuts


def base_screw_xy():
    """Case (x, y) of the screws up through the base: into the cover's
    flanges, then into the cradle's legs."""
    flange = [(x, y) for y in (P.BASE_SCREW_Y, P.DEPTH - P.BASE_SCREW_Y) for x in P.BASE_SCREWS_X]
    return flange, sheet.cradle_leg_xy()


def printed_cover():
    """The printed cover in the case frame: the metal cover's outside mold
    line with thicker walls and face, its face cuts and back-wall jack hole,
    and heat-set insert holes in thickened flanges where the metal has its
    S-M3-0 nuts. The flanges' undersides sit on the floor's top, as the
    metal's do."""
    t = P.PRINT_WALL
    st = sheet.Strip(sheet.cover_strip().pts, t=t, r=P.PRINT_BEND_R)
    body = st.solid(sheet.YZ_PLANE, sheet.METAL_PIECE_WIDTH)
    x0, wd, fl, ft = sheet.METAL_PIECE_X0, sheet.METAL_PIECE_WIDTH, P.BOTTOM_FLANGE, P.PRINT_FLANGE_T
    z = P.SHEET_T
    body = body.fuse(cq.Solid.makeBox(wd, fl, ft, cq.Vector(x0, 0, z)), cq.Solid.makeBox(wd, fl, ft, cq.Vector(x0, P.DEPTH - fl, z)))
    cutters = [to_case(c) for c in _face_pockets(t)] + sheet.plate_cutters(face_cuts(), -t - 1, 1)
    cutters.append(cq.Solid.makeCylinder(P.BACK_JACK_HOLE / 2, t + 2, cq.Vector(P.BACK_JACK_X, P.DEPTH - t - 1, P.BACK_JACK_Z), cq.Vector(0, 1, 0)))
    cutters += [cq.Solid.makeCylinder(P.PRINT_INSERT_D / 2, ft + 2, cq.Vector(x, y, z - 1)) for x, y in base_screw_xy()[0]]
    return body.cut(*cutters).clean()


def cover_for_print():
    """The printed cover face down: the face prints flat on the bed, so its
    holes come out true; the two bottom flanges need support."""
    return printed_cover().moved(PLATE_LOC.inverse).rotate(cq.Vector(0, 0, 0), cq.Vector(1, 0, 0), 180)


def printed_base():
    """The printed base in the case frame: the metal base's outside with
    thicker side walls, the same service slot and screw holes, and a floor
    thickened downward so its top stays at the metal floor's top."""
    w = P.PRINT_SIDE_WALL
    z0 = P.SHEET_T - P.PRINT_FLOOR
    sil = [(0.0, z0), (P.DEPTH, z0), (P.DEPTH, P.underside_z(P.DEPTH, 0.0)), (0.0, P.underside_z(0.0, 0.0))]
    body = sheet.yz_prism(sil, 0, P.WIDTH)
    body = body.cut(cq.Solid.makeBox(P.WIDTH - 2 * w, P.DEPTH + 2, 200, cq.Vector(w, -1, P.SHEET_T)))
    body = body.cut(sheet.service_slot_prism(-1, w + 1))
    flange, legs = base_screw_xy()
    holes = [cq.Solid.makeCylinder(P.M3_CLEARANCE / 2, P.PRINT_FLOOR + 2, cq.Vector(x, y, z0 - 1)) for x, y in flange + legs]
    return body.cut(*holes).clean()
