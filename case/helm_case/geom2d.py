"""Exact 2D cut geometry: closed paths of lines and arcs, plus circles.

One flat part is an outline plus inner cuts. The same objects write the
SendCutSend DXF (true arcs and circles), feed the rule checks (through
shapely), and become CadQuery faces for the 3D models.
"""

import math
from dataclasses import dataclass, field

import cadquery as cq
import ezdxf
from shapely.geometry import Point, Polygon


@dataclass
class Circle:
    cx: float
    cy: float
    r: float

    def moved(self, fn):
        x, y = fn(self.cx, self.cy)
        return Circle(x, y, self.r)

    def shapely(self):
        return Point(self.cx, self.cy).buffer(self.r, quad_segs=64)


@dataclass
class Path:
    """Closed path. Each vertex is (x, y, bulge); the bulge belongs to the
    segment that starts at that vertex (DXF LWPOLYLINE convention: positive
    bulge turns counter-clockwise, bulge = tan(sweep / 4))."""

    verts: list

    def moved(self, fn):
        return Path([(*fn(x, y), b) for x, y, b in self.verts])

    def segments(self):
        n = len(self.verts)
        for i in range(n):
            x0, y0, b = self.verts[i]
            x1, y1, _ = self.verts[(i + 1) % n]
            yield (x0, y0), (x1, y1), b

    def points(self, chord=0.05):
        pts = []
        for p, q, b in self.segments():
            pts.append(p)
            if abs(b) > 1e-12:
                pts.extend(arc_points(p, q, b, chord)[1:-1])
        return pts

    def shapely(self):
        return Polygon(self.points())


@dataclass
class FlatPart:
    name: str
    outline: Path
    cuts: list = field(default_factory=list)  # Path or Circle
    bend_lines: list = field(default_factory=list)  # ((x0, y0), (x1, y1), angle_deg, note)

    def shapely(self):
        poly = self.outline.shapely()
        for c in self.cuts:
            poly = poly.difference(c.shapely())
        return poly


def arc_geometry(p, q, b):
    """Centre, radius, and sweep (signed radians) of a bulge segment."""
    theta = 4 * math.atan(b)
    dx, dy = q[0] - p[0], q[1] - p[1]
    chord = math.hypot(dx, dy)
    r = chord / (2 * math.sin(abs(theta) / 2))
    mx, my = (p[0] + q[0]) / 2, (p[1] + q[1]) / 2
    # the centre sits on the left of p->q for a counter-clockwise arc
    lx, ly = -dy / chord, dx / chord
    sign = 1 if theta > 0 else -1
    h = math.sqrt(max(r * r - (chord / 2) ** 2, 0.0))
    if abs(theta) > math.pi:
        h = -h
    cx, cy = mx + sign * lx * h, my + sign * ly * h
    return (cx, cy), r, theta


def arc_mid(p, q, b):
    dx, dy = q[0] - p[0], q[1] - p[1]
    chord = math.hypot(dx, dy)
    s = b * chord / 2  # sagitta, to the right of p->q for a positive bulge
    rx, ry = dy / chord, -dx / chord
    return ((p[0] + q[0]) / 2 + rx * s, (p[1] + q[1]) / 2 + ry * s)


def arc_points(p, q, b, chord=0.05):
    (cx, cy), r, theta = arc_geometry(p, q, b)
    a0 = math.atan2(p[1] - cy, p[0] - cx)
    n = max(4, int(abs(theta) * r / chord) + 1)
    return [(cx + r * math.cos(a0 + theta * i / n), cy + r * math.sin(a0 + theta * i / n)) for i in range(n + 1)]


def bulge_for(sweep_rad):
    return math.tan(sweep_rad / 4)


def rounded_rect(cx, cy, w, h, r=0.0):
    """Axis-aligned rectangle, counter-clockwise, optional corner radius."""
    x0, x1, y0, y1 = cx - w / 2, cx + w / 2, cy - h / 2, cy + h / 2
    if r <= 0:
        return Path([(x0, y0, 0), (x1, y0, 0), (x1, y1, 0), (x0, y1, 0)])
    b = bulge_for(math.pi / 2)
    return Path(
        [
            (x0 + r, y0, 0),
            (x1 - r, y0, b),
            (x1, y0 + r, 0),
            (x1, y1 - r, b),
            (x1 - r, y1, 0),
            (x0 + r, y1, b),
            (x0, y1 - r, 0),
            (x0, y0 + r, b),
        ]
    )


def cq_wire(path, plane=None):
    """CadQuery wire on the XY plane (or the given Plane)."""
    edges = []
    for p, q, b in path.segments():
        v0, v1 = cq.Vector(p[0], p[1], 0), cq.Vector(q[0], q[1], 0)
        if abs(b) < 1e-12:
            edges.append(cq.Edge.makeLine(v0, v1))
        else:
            m = arc_mid(p, q, b)
            edges.append(cq.Edge.makeThreePointArc(v0, cq.Vector(m[0], m[1], 0), v1))
    wire = cq.Wire.assembleEdges(edges)
    if plane is not None:
        wire = wire.transformShape(plane.rG)
    return wire


def extrude_part(part, thickness):
    """Solid of a flat part on the XY plane, from z = 0 up to the thickness."""
    face = cq.Face.makeFromWires(cq_wire(part.outline))
    solid = cq.Solid.extrudeLinear(face, cq.Vector(0, 0, thickness))
    cutters = []
    for c in part.cuts:
        if isinstance(c, Circle):
            cutters.append(cq.Solid.makeCylinder(c.r, thickness + 2, cq.Vector(c.cx, c.cy, -1)))
        else:
            f = cq.Face.makeFromWires(cq_wire(c))
            cutters.append(cq.Solid.extrudeLinear(f, cq.Vector(0, 0, thickness + 2)).translate(cq.Vector(0, 0, -1)))
    if cutters:
        solid = solid.cut(*cutters)
    return solid


def write_dxf(part, filename):
    """Write cut paths only: one layer, millimetres, no text or dimensions."""
    doc = ezdxf.new("R2010", setup=False)
    doc.units = ezdxf.units.MM
    doc.header["$INSUNITS"] = 4
    doc.header["$MEASUREMENT"] = 1
    msp = doc.modelspace()
    shapes = [part.outline] + list(part.cuts)
    for s in shapes:
        if isinstance(s, Circle):
            msp.add_circle((s.cx, s.cy), s.r, dxfattribs={"layer": "0"})
        else:
            msp.add_lwpolyline([(x, y, 0, 0, b) for x, y, b in s.verts], format="xyseb", close=True, dxfattribs={"layer": "0"})
    doc.saveas(filename)
