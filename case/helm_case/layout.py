"""The face layout, in plate coordinates (x, v), and the test coupon."""

from . import params as P
from .geom2d import Circle, FlatPart, rounded_rect


def module_centre():
    return (P.MODULE_X + P.MODULE_SX / 2, P.MODULE_V + P.MODULE_SV / 2)


def window_centre():
    mx, mv = module_centre()
    return (mx + P.WINDOW_OFFSET[0], mv + P.WINDOW_OFFSET[1])


def face_cuts():
    """Through cuts of the face. The face carries no screw or standoff holes:
    the cover is screwed up from the bottom."""
    wx, wv = window_centre()
    cuts = [rounded_rect(wx, wv, P.SCREEN_WINDOW_X, P.SCREEN_WINDOW_V, P.SCREEN_WINDOW_RADIUS)]
    cuts += [rounded_rect(x, P.KEY_V, P.KEY_HOLE, P.KEY_HOLE) for x in P.KEY_XS]
    cuts.append(Circle(P.KNOB_X, P.KNOB_V, P.ENCODER_HOLE / 2))
    cuts.append(rounded_rect(P.LIGHT_X, P.LIGHT_V, *P.LIGHT_WINDOW, P.LIGHT_WINDOW_RADIUS))
    sw, sv = P.SLOT_SIZE
    cuts += [rounded_rect(x, v, sw, sv, sw / 2 - 0.001) for x, v in P.slot_centres()]
    return cuts


def coupon():
    """Key holes 13.95 to 14.10 and knob holes 7.2 and 7.5. Each hole is
    identified by a row of small dots, since SendCutSend parts carry no text:
    key holes get 1 to 4 dots below them, knob holes 1 or 2 dots above."""
    cw, ch = P.COUPON_SIZE
    cuts = []
    key_y = 21.0
    for i, size in enumerate(P.COUPON_KEY_HOLES):
        x = 16.0 + i * 24.0
        cuts.append(rounded_rect(x, key_y, size, size))
        cuts += _dots(x, 6.0, i + 1)
    for i, d in enumerate(P.COUPON_KNOB_HOLES):
        x = 108.0 + i * 13.0
        cuts.append(Circle(x, key_y, d / 2))
        cuts += _dots(x, 32.0, i + 1)
    return FlatPart("mx_coupon", rounded_rect(cw / 2, ch / 2, cw, ch, 2.0), cuts)


def _dots(cx, y, n):
    x0 = cx - (n - 1) * P.COUPON_DOT_PITCH / 2
    return [Circle(x0 + i * P.COUPON_DOT_PITCH, y, P.COUPON_DOT_D / 2) for i in range(n)]
