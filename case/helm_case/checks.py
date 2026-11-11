"""SendCutSend rule checks for the flat parts and their DXF files.

Rules come from docs/research/case.md and SendCutSend's hardware catalog;
params.py holds the numbers. Each check returns a list of failure strings,
empty when the part passes, plus the measured minimums for the report.
"""

import math

import ezdxf
from shapely.geometry import LineString, Point, Polygon

from . import params as P
from . import sheet
from .geom2d import Circle

HARDWARE_HOLES = {round(P.S_M3_HOLE, 4): "S-M3-0"}


def _is_hardware(cut):
    return isinstance(cut, Circle) and round(2 * cut.r, 4) in HARDWARE_HOLES


def check_flat(part):
    fails, stats = [], {}
    outline = part.outline.shapely()
    if not outline.is_valid:
        fails.append(f"{part.name}: outline is not a valid closed shape")
    edge = outline.exterior
    shapes = [c.shapely() for c in part.cuts]

    min_feature = math.inf
    for c, s in zip(part.cuts, shapes):
        if isinstance(c, Circle):
            size = 2 * c.r
        else:  # narrowest width of a slot or window
            size = _min_width(s)
        min_feature = min(min_feature, size)
        if size < P.MIN_HOLE - 1e-6:
            fails.append(f"{part.name}: cut {size:.3f} mm is under the {P.MIN_HOLE:.3f} mm minimum")
        if not outline.contains(s):
            fails.append(f"{part.name}: a cut crosses the outline")
    stats["smallest cut"] = min_feature

    min_edge = math.inf
    for c, s in zip(part.cuts, shapes):
        d = s.distance(edge)
        min_edge = min(min_edge, d)
        if d < P.MIN_EDGE_WEB - 1e-6:
            fails.append(f"{part.name}: cut at {_where(c)} is {d:.2f} mm from an edge (needs {P.MIN_EDGE_WEB:.2f})")
        if _is_hardware(c):
            dc = Point(c.cx, c.cy).distance(edge)
            if dc < P.HARDWARE_EDGE - 1e-6:
                fails.append(f"{part.name}: hardware hole at {_where(c)} centre is {dc:.2f} mm from an edge (needs {P.HARDWARE_EDGE:.2f})")
    stats["cut to edge"] = min_edge

    min_web = math.inf
    for i in range(len(shapes)):
        for j in range(i + 1, len(shapes)):
            if shapes[i].distance(shapes[j]) > 10:
                continue
            d = shapes[i].distance(shapes[j])
            min_web = min(min_web, d)
            if d < P.MIN_WEB - 1e-6:
                fails.append(f"{part.name}: web of {d:.2f} mm between cuts at {_where(part.cuts[i])} and {_where(part.cuts[j])}")
    stats["web between cuts"] = min_web

    if part.bend_lines:
        min_bend = math.inf
        for (p0, p1, angle, _) in part.bend_lines:
            if angle > P.MAX_BEND_DEG + 1e-6:
                fails.append(f"{part.name}: bend of {angle:.1f} degrees exceeds {P.MAX_BEND_DEG}")
            line = LineString([p0, p1])
            for c, s in zip(part.cuts, shapes):
                d = s.distance(line)
                min_bend = min(min_bend, d)
                if d < P.BEND_FEATURE_CLEARANCE - 1e-6:
                    fails.append(f"{part.name}: cut at {_where(c)} is {d:.2f} mm from a bend (needs {P.BEND_FEATURE_CLEARANCE:.2f})")
                if _is_hardware(c) and Point(c.cx, c.cy).distance(line) < P.HARDWARE_EDGE - 1e-6:
                    fails.append(f"{part.name}: hardware hole at {_where(c)} is too close to a bend")
        stats["feature to bend"] = min_bend
    return fails, stats


def check_strips():
    """Bend angles and flange lengths of the bent parts."""
    fails, stats = [], {}
    for name, st, _ in sheet.strips():
        for b in st.bends:
            if math.degrees(abs(b.angle)) > P.MAX_BEND_DEG + 1e-6:
                fails.append(f"{name}: bend of {math.degrees(abs(b.angle)):.1f} degrees")
        shortest = min(st.lengths)
        stats[f"{name} shortest flange"] = shortest
        if shortest < P.MIN_FLANGE - 1e-6:
            fails.append(f"{name}: flange of {shortest:.2f} mm is under the {P.MIN_FLANGE:.2f} mm minimum")
    return fails, stats


def check_dxf(filename):
    """The file SendCutSend receives: millimetres, one layer, closed cut
    paths only, no text or dimensions."""
    fails = []
    doc = ezdxf.readfile(filename)
    if doc.header.get("$INSUNITS") != 4:
        fails.append(f"{filename}: units are not millimetres")
    for e in doc.modelspace():
        kind = e.dxftype()
        if kind not in ("LWPOLYLINE", "CIRCLE"):
            fails.append(f"{filename}: unexpected {kind}")
        if e.dxf.layer != "0":
            fails.append(f"{filename}: entity on layer {e.dxf.layer}")
        if kind == "LWPOLYLINE" and not e.closed:
            fails.append(f"{filename}: open polyline")
    return fails


def _min_width(poly):
    """Smallest width of a convex-ish cut: twice the largest inscribed radius
    is not enough for slots, so search for the buffer at which it vanishes."""
    lo, hi = 0.0, 50.0
    for _ in range(40):
        mid = (lo + hi) / 2
        if poly.buffer(-mid / 2).is_empty:
            hi = mid
        else:
            lo = mid
    return lo


def _where(c):
    if isinstance(c, Circle):
        return f"({c.cx:.1f}, {c.cy:.1f})"
    b = Polygon(c.points()).bounds
    return f"({(b[0] + b[2]) / 2:.1f}, {(b[1] + b[3]) / 2:.1f})"


def check_logo():
    """The engraved logo's clearance on the face: at least LOGO_CLEAR from
    every face cut, from the cover's side edges, and from where the front and
    back bends start, so the mark sits on flat metal with room around it.
    Measured on the mark's bounding box, so it is conservative. Returns
    failures and the measured minimums."""
    from . import layout, logo

    mark = logo.placed_box()
    gaps = {"cut": min(mark.distance(c.shapely()) for c in layout.face_cuts())}
    x0, x1 = logo.face_x()
    v0, v1 = logo.face_flat_v()
    b = mark.bounds
    gaps["side edge"] = min(b[0] - x0, x1 - b[2])
    gaps["bend"] = min(b[1] - v0, v1 - b[3])
    fails = [f"logo: {k} clearance {v:.2f} mm (needs {P.LOGO_CLEAR:.2f})" for k, v in gaps.items() if v < P.LOGO_CLEAR - 1e-6]
    return fails, {f"logo to {k}": v for k, v in gaps.items()}
