"""Printed parts inside the metal case: the module's cradle, the light bar
holder, the speaker holder, and a printable copy of the test coupon."""

import cadquery as cq

from . import params as P
from . import sheet
from .geom2d import FlatPart, extrude_part, rounded_rect

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


def cradle(insert_holes=True):
    """The printed cradle in the case frame: a plate under the module on four
    legs standing on the floor. Each leg takes a heat-set insert from below
    for a screw up through the floor."""
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
    solid = plate.fuse(*legs)
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
