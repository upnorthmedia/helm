"""SendCutSend sheet-metal parts: bend math, bent solids, and flat patterns.

The metal case is two parts in 0.063 inch 5052 aluminum:

- cover: front flange, front wall, the sloped face, back wall, back flange;
  four parallel bends. Its flanges carry the S-M3-0 nuts the bottom screws
  go into, so nothing shows on the face.
- base: bottom and both side walls, two parallel bends. The side walls rise
  to the face's top surface beside the cover.

Both are constant-width strips whose bends are all parallel, so the flat
patterns need no corner reliefs. Bent shapes are described by their outside
mold line (the outer surface with sharp corners); the strip builder rounds
each corner with SendCutSend's fixed inside radius.
"""

import math
from dataclasses import dataclass

import cadquery as cq

from . import params as P
from .geom2d import Circle, FlatPart, Path, bulge_for, cq_wire, rounded_rect
from .layout import face_cuts


@dataclass
class Bend:
    index: int  # vertex index in the mold polyline
    angle: float  # signed turn, radians
    setback: float  # outside setback from the mold corner
    allowance: float


class Strip:
    """A sheet strip bent along parallel lines, from its outside mold polyline.

    pts are 2D points in the profile plane; every turn must go the same way.
    The material lies on the inside of the turns."""

    def __init__(self, pts, t=P.SHEET_T, r=P.BEND_RADIUS, k=P.K_FACTOR):
        self.pts, self.t, self.r, self.k = pts, t, r, k
        self.dirs, self.lengths = [], []
        for a, b in zip(pts, pts[1:]):
            dx, dy = b[0] - a[0], b[1] - a[1]
            n = math.hypot(dx, dy)
            self.dirs.append((dx / n, dy / n))
            self.lengths.append(n)
        self.bends = []
        for i in range(1, len(pts) - 1):
            d0, d1 = self.dirs[i - 1], self.dirs[i]
            ang = math.atan2(d0[0] * d1[1] - d0[1] * d1[0], d0[0] * d1[0] + d0[1] * d1[1])
            sb = (r + t) * math.tan(abs(ang) / 2)
            ba = abs(ang) * (r + k * t)
            self.bends.append(Bend(i, ang, sb, ba))
        signs = {math.copysign(1, b.angle) for b in self.bends}
        assert len(signs) == 1, "all bends must turn the same way"
        self.turn = signs.pop()  # +1 left (counter-clockwise), -1 right

    def inward(self, i):
        dx, dy = self.dirs[i]
        return (-dy * self.turn, dx * self.turn)

    def _setbacks(self, i):
        start = self.bends[i - 1].setback if i > 0 else 0.0
        end = self.bends[i].setback if i < len(self.bends) else 0.0
        return start, end

    def flat_segment(self, i):
        s, e = self._setbacks(i)
        return self.lengths[i] - s - e

    def flat_start(self, i):
        """Flat coordinate where segment i's straight part begins."""
        pos = 0.0
        for j in range(i):
            pos += self.flat_segment(j) + self.bends[j].allowance
        return pos

    def flat_length(self):
        return self.flat_start(len(self.lengths) - 1) + self.flat_segment(len(self.lengths) - 1)

    def to_flat(self, i, s):
        """Flat coordinate of a point at outside-mold distance s along segment i."""
        start, _ = self._setbacks(i)
        assert start - 1e-9 <= s <= self.lengths[i] - self._setbacks(i)[1] + 1e-9, "point lies in a bend"
        return self.flat_start(i) + s - start

    def bend_centrelines(self):
        return [self.flat_start(b.index - 1) + self.flat_segment(b.index - 1) + b.allowance / 2 for b in self.bends]

    def point(self, i, s):
        p, d = self.pts[i], self.dirs[i]
        return (p[0] + d[0] * s, p[1] + d[1] * s)

    def profile(self):
        """Closed cross-section path with exact bend arcs."""
        t = self.t
        outer, inner = [], []
        n0 = self.inward(0)
        outer.append((self.pts[0], 0.0))
        inner.append((self.pts[0][0] + n0[0] * t, self.pts[0][1] + n0[1] * t))
        for b in self.bends:
            i = b.index
            c = self.pts[i]
            d0, d1 = self.dirs[i - 1], self.dirs[i]
            ta = (c[0] - d0[0] * b.setback, c[1] - d0[1] * b.setback)
            tb = (c[0] + d1[0] * b.setback, c[1] + d1[1] * b.setback)
            na, nb = self.inward(i - 1), self.inward(i)
            outer.append((ta, bulge_for(b.angle)))
            outer.append((tb, 0.0))
            inner.append(((ta[0] + na[0] * t, ta[1] + na[1] * t), (tb[0] + nb[0] * t, tb[1] + nb[1] * t), b.angle))
        last = len(self.pts) - 1
        nl = self.inward(last - 1)
        outer.append((self.pts[last], 0.0))
        end_inner = (self.pts[last][0] + nl[0] * t, self.pts[last][1] + nl[1] * t)
        verts = [(p[0], p[1], b) for p, b in outer]
        # walk back along the inside surface
        verts.append((end_inner[0], end_inner[1], 0.0))
        for ia, ib, ang in reversed(inner[1:]):
            verts.append((ib[0], ib[1], bulge_for(-ang)))
            verts.append((ia[0], ia[1], 0.0))
        verts.append((inner[0][0], inner[0][1], 0.0))
        # merge zero-length steps
        clean = []
        for v in verts:
            if clean and math.hypot(v[0] - clean[-1][0], v[1] - clean[-1][1]) < 1e-9:
                clean[-1] = (clean[-1][0], clean[-1][1], v[2])
            else:
                clean.append(v)
        return Path(clean)

    def solid(self, plane, length):
        face = cq.Face.makeFromWires(cq_wire(self.profile(), plane))
        return cq.Solid.extrudeLinear(face, plane.zDir * length)


# ---------------------------------------------------------------------------
# The bent parts
# ---------------------------------------------------------------------------
T = P.SHEET_T
METAL_PIECE_X0 = T + P.SIDE_CLEARANCE  # the cover sits between the side walls
METAL_PIECE_WIDTH = P.WIDTH - 2 * METAL_PIECE_X0
YZ_PLANE = cq.Plane(origin=(METAL_PIECE_X0, 0, 0), xDir=(0, 1, 0), normal=(1, 0, 0))
XZ_PLANE = cq.Plane(origin=(0, 0, 0), xDir=(1, 0, 0), normal=(0, -1, 0))


def base_strip():
    h = P.BACK_HEIGHT
    return Strip([(0.0, h), (0.0, 0.0), (P.WIDTH, 0.0), (P.WIDTH, h)])


@dataclass
class StripHole:
    segment: int
    s: float  # outside mold distance along the segment
    x: float  # across the strip (case x, or case y for the base)
    d: float
    hardware: str = ""


def base_holes():
    """Screw holes in the base's bottom, under the cover's flange nuts and
    under the cradle legs."""
    st = base_strip()
    holes = []
    for y in (P.BASE_SCREW_Y, P.DEPTH - P.BASE_SCREW_Y):
        holes += [StripHole(1, x, y, P.M3_CLEARANCE) for x in P.BASE_SCREWS_X]
    holes += [StripHole(1, x, y, P.M3_CLEARANCE) for x, y in cradle_leg_xy()]
    return st, holes


def cradle_underside_w():
    """Plate w of the cradle's underside."""
    return -(T + P.MODULE_THICKNESS + P.CRADLE_FOAM + P.CRADLE_T)


def cradle_leg_xy():
    """Case (x, y) of each cradle leg: straight below its point on the cradle."""
    w = cradle_underside_w()
    return [(x, P.plate_to_case(x, v, w)[1]) for x, v in P.cradle_leg_points()]


# ---------------------------------------------------------------------------
# The cover strip (front flange, front wall, face, back wall, back flange).
# The face is segment 2, and plate v is the outside mold distance along it,
# so face cuts map straight onto the flat.
# ---------------------------------------------------------------------------
FACE_SEG = 2


def cover_strip():
    return Strip([(P.BOTTOM_FLANGE, T), (0.0, T), (0.0, P.FRONT_HEIGHT), (P.DEPTH, P.BACK_HEIGHT), (P.DEPTH, T), (P.DEPTH - P.BOTTOM_FLANGE, T)])


def cover_holes():
    st = cover_strip()
    holes = [StripHole(0, P.BOTTOM_FLANGE - P.BASE_SCREW_Y, x, P.S_M3_HOLE, "S-M3-0") for x in P.BASE_SCREWS_X]
    holes += [StripHole(4, P.BASE_SCREW_Y, x, P.S_M3_HOLE, "S-M3-0") for x in P.BASE_SCREWS_X]
    holes.append(StripHole(3, P.BACK_HEIGHT - P.BACK_JACK_Z, P.BACK_JACK_X, P.BACK_JACK_HOLE))
    return st, holes


def cover_solid():
    st, holes = cover_holes()
    s = st.solid(YZ_PLANE, METAL_PIECE_WIDTH)
    cutters = _strip_hole_cutters(st, holes, True) + plate_cutters(face_cuts(), -T - 1, 1)
    return s.cut(*cutters)


def cover_flat():
    st, holes = cover_holes()
    part = _strip_flat("cover", st, holes, METAL_PIECE_WIDTH)
    shift = st.flat_start(FACE_SEG) - st._setbacks(FACE_SEG)[0]  # flat y of plate v = 0
    part.cuts += [c.moved(lambda x, v: (x - METAL_PIECE_X0, v + shift)) for c in face_cuts()]
    return part


def plate_cutters(cuts, w0, w1):
    """Solids that cut plate-frame shapes through the face, placed in the case."""
    out = []
    for c in cuts:
        if isinstance(c, Circle):
            solid = cq.Solid.makeCylinder(c.r, w1 - w0, cq.Vector(c.cx, c.cy, w0))
        else:
            solid = cq.Solid.extrudeLinear(cq.Face.makeFromWires(cq_wire(c)), cq.Vector(0, 0, w1 - w0)).translate(cq.Vector(0, 0, w0))
        out.append(solid.moved(_PLATE_LOC))
    return out


_PLATE_LOC = cq.Location(cq.Vector(0, 0, P.FRONT_HEIGHT), cq.Vector(1, 0, 0), P.SLOPE_DEG)


def service_slot_plate():
    """The closed service slot in the left wall, plate (v, w): the slot
    keeps 2 x the sheet below the wall's top edge, beside the cover."""
    v0, v1 = P.PORT_BAY_V
    return rounded_rect((v0 + v1) / 2, (-(T + P.PORT_BAY_BELOW_FACE) - (P.MIN_EDGE_WEB + 0.05)) / 2, v1 - v0, (T + P.PORT_BAY_BELOW_FACE) - (P.MIN_EDGE_WEB + 0.05), P.PORT_BAY_RADIUS)


def service_slot_prism(x0, x1):
    plane = cq.Plane(origin=(x0, 0, 0), xDir=(0, 1, 0), normal=(1, 0, 0))
    moved = service_slot_plate().moved(lambda v, w: P.plate_to_case(0, v, w)[1:])
    return cq.Solid.extrudeLinear(cq.Face.makeFromWires(cq_wire(moved, plane)), cq.Vector(x1 - x0, 0, 0))


# ---------------------------------------------------------------------------
# Bent solids, placed in the case frame
# ---------------------------------------------------------------------------
def _strip_hole_cutters(st, holes, across_is_x):
    cutters = []
    for h in holes:
        py, pz = st.point(h.segment, h.s)
        n = st.inward(h.segment)
        if across_is_x:
            base = cq.Vector(h.x, py, pz) - cq.Vector(0, n[0], n[1]) * 2
            axis = cq.Vector(0, n[0], n[1])
        else:  # base strip: profile is (x, z), across is y
            base = cq.Vector(py, h.x, pz) - cq.Vector(n[0], 0, n[1]) * 2
            axis = cq.Vector(n[0], 0, n[1])
        cutters.append(cq.Solid.makeCylinder(h.d / 2, T + 4, base, axis))
    return cutters


def side_silhouette(plate_t):
    """Polygon (y, z) of a side wall: desk up to the face's underside."""
    return [(0.0, 0.0), (P.DEPTH, 0.0), (P.DEPTH, P.underside_z(P.DEPTH, plate_t)), (0.0, P.underside_z(0.0, plate_t))]


def yz_prism(pts, x0, x1):
    plane = cq.Plane(origin=(x0, 0, 0), xDir=(0, 1, 0), normal=(1, 0, 0))
    wire = cq.Wire.makePolygon([cq.Vector(*plane.toWorldCoords((a, b)).toTuple()) for a, b in pts], close=True)
    return cq.Solid.extrudeLinear(cq.Face.makeFromWires(wire), cq.Vector(x1 - x0, 0, 0))


def base_solid():
    st, holes = base_strip(), base_holes()[1]
    u = st.solid(XZ_PLANE, P.DEPTH)
    u = u.translate(cq.Vector(0, -u.BoundingBox().ymin, 0))
    u = u.intersect(yz_prism(side_silhouette(0.0), -1, P.WIDTH + 1))  # side walls rise to the face's top surface
    u = u.cut(service_slot_prism(-1, T + 1))
    return u.cut(*_strip_hole_cutters(st, holes, False))


# ---------------------------------------------------------------------------
# Flat patterns
# ---------------------------------------------------------------------------
def _strip_flat(name, st, holes, width):
    """Flat pattern of a constant-width strip: x across, y along the flat."""
    L = st.flat_length()
    outline = Path([(0, 0, 0), (width, 0, 0), (width, L, 0), (0, L, 0)])
    cuts = [Circle(h.x - METAL_PIECE_X0, st.to_flat(h.segment, h.s), h.d / 2) for h in holes]
    bends = [((0, c), (width, c), math.degrees(abs(b.angle)), "") for c, b in zip(st.bend_centrelines(), st.bends)]
    return FlatPart(name, outline, cuts, bends)


def base_flat():
    """Flat pattern of the base: x along the flat (left wall, bottom, right
    wall), y is case depth. The left wall carries the service slot."""
    st, holes = base_holes()
    h = P.BACK_HEIGHT

    def left_u(z):  # left wall: mold distance from the top corner is h - z
        return st.to_flat(0, h - z)

    def right_u(z):
        return st.to_flat(2, z)

    zf, zb = P.underside_z(0, 0.0), P.underside_z(P.DEPTH, 0.0)
    verts = [(left_u(zf), 0.0, 0), (right_u(zf), 0.0, 0), (right_u(zb), P.DEPTH, 0), (left_u(zb), P.DEPTH, 0)]
    cuts = [Circle(st.to_flat(hh.segment, hh.s), hh.x, hh.d / 2) for hh in holes]

    # the service slot; plate (v, w) maps to flat (x, y) by two rotations
    def to_flat(v, w):
        _, y, z = P.plate_to_case(0, v, w)
        return (st.to_flat(0, P.BACK_HEIGHT - z), y)

    cuts.append(service_slot_plate().moved(to_flat))
    outline = Path(verts)
    bends = [((c, 0), (c, P.DEPTH), math.degrees(abs(b.angle)), "") for c, b in zip(st.bend_centrelines(), st.bends)]
    return FlatPart("base", outline, cuts, bends)


def strips():
    """Name, strip, holes for the rule checks."""
    return [("cover", *cover_holes()), ("base", *base_holes())]
