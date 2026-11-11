"""The engraved face logo: wheel + "helm" (H1).

The mark is a source file, `case/logo/logo-h1-wheel-helm.dxf` (1:1 mm, closed
polylines on layer ENGRAVE, origin at its lower-left corner), drawn in code
during the logo design work, with the Outfit typeface turned to outlines. This module places it on the face at (LOGO_X, LOGO_V) and writes
the files a laser shop needs: the mark at 1:1, and a placement drawing.

SendCutSend does not engrave, so the mark never goes into a cut file.
"""

import shutil
from pathlib import Path

import ezdxf
from shapely import affinity
from shapely.geometry import Polygon, box

from . import params as P
from . import sheet
from .geom2d import Circle, arc_points
from .layout import face_cuts, window_centre

LOGO_DIR = Path(__file__).resolve().parents[1] / "logo"
NAME = "logo-h1-wheel-helm"
SOURCE_DXF = LOGO_DIR / f"{NAME}.dxf"


def mark():
    """The mark as shapely geometry in the file's own frame. Rings are filled
    with the even-odd rule, as laser software does."""
    doc = ezdxf.readfile(SOURCE_DXF)
    shape = Polygon()
    for e in doc.modelspace().query("LWPOLYLINE"):
        shape = shape.symmetric_difference(Polygon(list(e.get_points("xy"))))
    return shape


def mark_size():
    b = mark().bounds
    return (b[2] - b[0], b[3] - b[1])


def placed():
    """The mark on the face, in plate (x, v): centred on (LOGO_X, LOGO_V),
    reading left to right with its top toward the back of the deck."""
    m = mark()
    b = m.bounds
    return affinity.translate(m, P.LOGO_X - (b[0] + b[2]) / 2, P.LOGO_V - (b[1] + b[3]) / 2)


def placed_box():
    """The mark's bounding box on the face, plate (x, v)."""
    return box(*placed().bounds)


def face_flat_v():
    """Plate v range of the face's flat metal: from where the front bend ends
    to where the back bend starts."""
    st = sheet.cover_strip()
    s0, s1 = st._setbacks(sheet.FACE_SEG)
    return s0, P.FACE_LENGTH - s1


def face_x():
    """Case x range of the cover (it sits between the base's side walls)."""
    return sheet.METAL_PIECE_X0, sheet.METAL_PIECE_X0 + sheet.METAL_PIECE_WIDTH


def placement():
    """Named positions for the shop drawing and the README, in mm. Origin:
    the cover's left edge, and the face's front edge (its outside mold line,
    where the front wall's outer surface meets the face's, extended)."""
    lb = placed().bounds
    wx, wv = window_centre()
    x0, _ = face_x()
    return {
        "width": lb[2] - lb[0],
        "height": lb[3] - lb[1],
        "left_from_cover_left": lb[0] - x0,
        "right_from_cover_right": face_x()[1] - lb[2],
        "bottom_from_face_front": lb[1],
        "centre_from_cover_left": (lb[0] + lb[2]) / 2 - x0,
        "centre_off_window_centre": (lb[0] + lb[2]) / 2 - wx,
        "window_to_mark": lb[1] - (wv + P.SCREEN_WINDOW_V / 2),
        "mark_to_back_bend": face_flat_v()[1] - lb[3],
        "left_from_window_left": lb[0] - (wx - P.SCREEN_WINDOW_X / 2),
    }


# ---------------------------------------------------------------------------
# Files for the laser shop
# ---------------------------------------------------------------------------
def _rings(shape):
    polys = getattr(shape, "geoms", [shape])
    for poly in polys:
        yield list(poly.exterior.coords)[:-1]
        for hole in poly.interiors:
            yield list(hole.coords)[:-1]


def _to_drawing(x, v):
    """Plate (x, v) to drawing (x, y): x from the cover's left edge, y = v."""
    return (x - face_x()[0], v)


def write_placement_dxf(filename):
    """The face at 1:1: its flat outline and bend starts (layer FACE), its
    cuts for reference (layer CUTS) and the mark in place (layer ENGRAVE)."""
    doc = ezdxf.new("R2010", setup=False)
    doc.units = ezdxf.units.MM
    doc.header["$INSUNITS"] = 4
    doc.header["$MEASUREMENT"] = 1
    for name, color in (("FACE", 8), ("CUTS", 5), ("ENGRAVE", 1)):
        doc.layers.add(name, color=color)
    msp = doc.modelspace()
    v0, v1 = face_flat_v()
    w = sheet.METAL_PIECE_WIDTH
    msp.add_lwpolyline([(0, 0), (w, 0), (w, P.FACE_LENGTH), (0, P.FACE_LENGTH)], close=True, dxfattribs={"layer": "FACE"})
    for v in (v0, v1):
        msp.add_line((0, v), (w, v), dxfattribs={"layer": "FACE"})
    for c in face_cuts():
        if isinstance(c, Circle):
            msp.add_circle(_to_drawing(c.cx, c.cy), c.r, dxfattribs={"layer": "CUTS"})
        else:
            msp.add_lwpolyline([(*_to_drawing(x, y), b) for x, y, b in c.verts], format="xyb", close=True, dxfattribs={"layer": "CUTS"})
    for ring in _rings(placed()):
        msp.add_lwpolyline([_to_drawing(x, y) for x, y in ring], close=True, dxfattribs={"layer": "ENGRAVE"})
    doc.saveas(filename)


def write_placement_svg(filename):
    """A 1:1 drawing of the face with the mark in place and its position
    dimensioned. Printed at 100 percent it is also a paper template."""
    m = 12.0  # margin
    w = sheet.METAL_PIECE_WIDTH
    h = P.FACE_LENGTH
    W, H = w + 2 * m + 62, h + 2 * m + 14
    v0, v1 = face_flat_v()
    pos = placement()
    lb = placed().bounds
    wx, wv = window_centre()

    def X(x):
        return m + x

    def Y(v):
        return m + 8 + (h - v)

    def pt(x, v):
        dx, dv = _to_drawing(x, v)
        return f"{X(dx):.3f},{Y(dv):.3f}"

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.1f}mm" height="{H:.1f}mm" viewBox="0 0 {W:.1f} {H:.1f}" font-family="Helvetica, Arial, sans-serif">',
        "  <title>Helm face: logo placement (1:1, mm)</title>",
        f'  <rect width="{W:.1f}" height="{H:.1f}" fill="#ffffff"/>',
        f'  <text x="{m}" y="{m - 3}" font-size="4" font-weight="bold">Helm face, logo placement. 1:1, millimetres. Back of the deck at the top.</text>',
        f'  <rect x="{X(0)}" y="{Y(h):.3f}" width="{w:.3f}" height="{h:.3f}" fill="none" stroke="#999" stroke-width="0.3"/>',
    ]
    for v in (v0, v1):
        out.append(f'  <line x1="{X(0)}" y1="{Y(v):.3f}" x2="{X(w):.3f}" y2="{Y(v):.3f}" stroke="#999" stroke-width="0.25" stroke-dasharray="1.5,1"/>')
    out.append(f'  <text x="{X(w) + 2:.3f}" y="{Y(v1) + 1:.3f}" font-size="2.6" fill="#666">back bend starts</text>')
    out.append(f'  <text x="{X(w) + 2:.3f}" y="{Y(v0) + 1:.3f}" font-size="2.6" fill="#666">front bend ends</text>')
    for c in face_cuts():
        if isinstance(c, Circle):
            dx, dv = _to_drawing(c.cx, c.cy)
            out.append(f'  <circle cx="{X(dx):.3f}" cy="{Y(dv):.3f}" r="{c.r:.3f}" fill="none" stroke="#2a5db0" stroke-width="0.25"/>')
        else:
            pts = []
            for p, q, b in c.segments():
                pts.append(p)
                if abs(b) > 1e-12:
                    pts.extend(arc_points(p, q, b, 0.1)[1:-1])
            out.append('  <polygon points="' + " ".join(pt(x, v) for x, v in pts) + '" fill="none" stroke="#2a5db0" stroke-width="0.25"/>')
    d = " ".join("M" + " L".join(pt(x, v) for x, v in ring) + " Z" for ring in _rings(placed()))
    out.append(f'  <path d="{d}" fill="#c0282d" fill-rule="evenodd"/>')

    def hdim(xa, xb, v, label, at_end=False):
        y = Y(v)
        tx, anchor = ((X(xb) + 1.5, "start") if at_end else ((X(xa) + X(xb)) / 2, "middle"))
        ty = y + 0.8 if at_end else y - 1.0
        return [
            f'  <line x1="{X(xa):.3f}" y1="{y:.3f}" x2="{X(xb):.3f}" y2="{y:.3f}" stroke="#000" stroke-width="0.2"/>',
            f'  <line x1="{X(xa):.3f}" y1="{y - 1.5:.3f}" x2="{X(xa):.3f}" y2="{y + 1.5:.3f}" stroke="#000" stroke-width="0.2"/>',
            f'  <line x1="{X(xb):.3f}" y1="{y - 1.5:.3f}" x2="{X(xb):.3f}" y2="{y + 1.5:.3f}" stroke="#000" stroke-width="0.2"/>',
            f'  <text x="{tx:.3f}" y="{ty:.3f}" font-size="2.4" text-anchor="{anchor}">{label}</text>',
        ]

    def vdim(x, va, vb, label):
        xx = X(x)
        return [
            f'  <line x1="{xx:.3f}" y1="{Y(va):.3f}" x2="{xx:.3f}" y2="{Y(vb):.3f}" stroke="#000" stroke-width="0.2"/>',
            f'  <line x1="{xx - 1.5:.3f}" y1="{Y(va):.3f}" x2="{xx + 1.5:.3f}" y2="{Y(va):.3f}" stroke="#000" stroke-width="0.2"/>',
            f'  <line x1="{xx - 1.5:.3f}" y1="{Y(vb):.3f}" x2="{xx + 1.5:.3f}" y2="{Y(vb):.3f}" stroke="#000" stroke-width="0.2"/>',
            f'  <text x="{xx + 2:.3f}" y="{(Y(va) + Y(vb)) / 2 + 0.8:.3f}" font-size="2.4">{label}</text>',
        ]

    l0, _ = _to_drawing(lb[0], 0)
    l1, _ = _to_drawing(lb[2], 0)
    win_back = wv + P.SCREEN_WINDOW_V / 2
    out += hdim(0, l0, P.LOGO_V, f"{pos['left_from_cover_left']:.2f}")
    out += hdim(l1, w, P.LOGO_V, f"{pos['right_from_cover_right']:.2f}")
    out += hdim(l0, l1, lb[1] - 1.5, f"mark {pos['width']:.2f} x {pos['height']:.2f}", at_end=True)
    out += vdim(l1 + 30, win_back, lb[1], f"{pos['window_to_mark']:.2f} window to mark")
    out += vdim(l1 + 30, lb[3], v1, f"{pos['mark_to_back_bend']:.2f} mark to bend")
    out.append(f'  <line x1="{X(_to_drawing(wx, 0)[0]):.3f}" y1="{Y(lb[3] + 1):.3f}" x2="{X(_to_drawing(wx, 0)[0]):.3f}" y2="{Y(wv):.3f}" stroke="#000" stroke-width="0.15" stroke-dasharray="2,1,0.5,1"/>')
    out.append(f'  <text x="{X(_to_drawing(wx, 0)[0]) + 1:.3f}" y="{Y(wv) - 1:.3f}" font-size="2.6">mark centred on the screen window</text>')
    out += vdim(w + 26, 0, lb[1], f"{pos['bottom_from_face_front']:.2f} from the face's front edge")
    notes = [
        "Red: engrave (fill, fiber laser, mark to white). Blue: the face's cuts, for reference only. Grey: the cover and its bend lines.",
        f"Cover width {w:.2f}. Face front edge = the outside mold line where the front wall meets the face (inside the front bend's radius).",
    ]
    for i, n in enumerate(notes):
        out.append(f'  <text x="{m}" y="{H - 8 + i * 4.5:.1f}" font-size="2.8">{n}</text>')
    out.append("</svg>")
    Path(filename).write_text("\n".join(out) + "\n")


def write_engraving(out_dir):
    """Everything in out/engrave/: the mark at 1:1 (SVG and DXF, copied from
    the source), the placement drawing (SVG and DXF) and the shop's README."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for ext in ("svg", "dxf"):
        shutil.copyfile(LOGO_DIR / f"{NAME}.{ext}", out_dir / f"{NAME}.{ext}")
    write_placement_dxf(out_dir / "face_logo_placement.dxf")
    write_placement_svg(out_dir / "face_logo_placement.svg")
    (out_dir / "README.md").write_text(shop_readme())


def shop_readme():
    """The laser shop's instructions, with the placement numbers filled in."""
    p = placement()
    return SHOP_README.format(
        name=NAME,
        w=p["width"],
        h=p["height"],
        left=p["left_from_cover_left"],
        right=p["right_from_cover_right"],
        window=p["window_to_mark"],
        bend=p["mark_to_back_bend"],
        front=p["bottom_from_face_front"],
        from_window_left=p["left_from_window_left"],
        cover_w=sheet.METAL_PIECE_WIDTH,
        slope=P.SLOPE_DEG,
        t=P.SHEET_T,
        clear=P.LOGO_CLEAR,
    )


SHOP_README = """# Logo engraving: wheel + helm

Generated by `case/build.py` (`helm_case/logo.py`); edit the source, not this file.

The Helm deck's face carries one engraved mark: a ship's wheel beside the word "helm" (logo H1), **{w:.2f} x {h:.2f} mm**, laser marked bright on the black anodized aluminum. SendCutSend cuts, bends and anodizes the cover, but does not engrave ("We do not offer laser engraving or solid etching at this time", their FAQ, read 2026-11-10; their single-line etch cannot be combined with anodizing). So a local shop with a fiber laser marks the finished, bent cover.

![Placement drawing](face_logo_placement.svg)

## Files

| File | What it is |
| --- | --- |
| `{name}.dxf` | The mark at 1:1, mm (`$INSUNITS` 4), closed polylines on layer `ENGRAVE`, origin at its lower-left corner. **This is the job file.** |
| `{name}.svg` | The same mark at 1:1: one black even-odd path, width and height in mm, with a 1 mm margin on each side. |
| `face_logo_placement.svg` | The face at 1:1 with the mark in place and dimensioned. Printed at 100 percent it doubles as a paper template. |
| `face_logo_placement.dxf` | The same face at 1:1: the cover's outline and bend lines (layer `FACE`), the face's cuts (layer `CUTS`) and the mark in place (layer `ENGRAVE`). Origin: the cover's left edge and the face's front edge. |

The filled area is what gets engraved: the wheel's gaps, its hub hole and the counters in the letters are inner contours, which laser software fills correctly with the even-odd rule (the usual default). The word is already outlines, so no font is needed. Curves are dense polylines (no splines), so any laser software reads them. Do not scale the mark: its thinnest line is 0.39 mm and narrowest gap 0.35 mm, and below 14.2 mm wide a feature would drop under 0.2 mm.

## Where it goes

The mark sits on the sloped face, above the screen window, reading left to right with its top toward the back of the deck:

| Position | mm |
| --- | --- |
| Centred left to right on the screen window (and on the {cover_w:.2f} mm wide cover) | 0.00 offset |
| Screen window's back edge to the mark's bottom edge | **{window:.2f}** |
| Mark's top edge to where the back bend starts | {bend:.2f} |
| Cover's left edge to the mark's left edge (and right edge to right edge) | {left:.2f} and {right:.2f} |
| Window's left edge to the mark's left edge | {from_window_left:.2f} |
| Face's front edge (outside mold line, inside the front bend's radius) to the mark's bottom edge | {front:.2f} |

Locate from the **screen window**: it is a sharp laser-cut edge on the same flat as the mark, so "centred on the window, {window:.2f} mm above its back edge" is the reference to jig from. The face's front edge is a virtual corner inside the bend radius, given only as a cross-check. `case/build.py` fails the build if the mark comes closer than {clear:.1f} mm to any cut, the cover's side edges or a bend.

## The part

- **Material:** 5052 H32 aluminum, 0.063 inch ({t:.2f} mm), black Type II anodized by SendCutSend.
- **Shape:** the cover is bent: the face is flat, with the front wall and back wall folded down from it. Resting on its bottom flanges the face slopes {slope:.0f} degrees, so prop the front up {slope:.0f} degrees (a wedge under the front flange, or a fixture that registers in the screen window) so the face sits square to the beam. Nothing stands above the face, so the lens has a clear path.
- **Cosmetic surface:** handle with gloves and protect the face from scratches in the fixture.

## Process

This is general practice for anodized aluminum, not a measured result on SendCutSend's anodize; a test mark comes first (below).

- **Fiber laser (1064 nm galvo marker, typically 20 to 50 W): the right tool.** It removes or bleaches the dyed anodic layer and leaves a crisp mark, usually white to light silver-grey and matte on black anodize. More energy ablates to bare aluminum, brighter and greyer. A MOPA fiber can tune the pulse for a whiter mark. Its 0.03 to 0.05 mm spot resolves the 0.35 mm gaps easily.
- **Settings to ask for:** a filled (hatched) engrave, not an outline: line spacing about 0.03 to 0.05 mm, cross-hatched at two angles for an even fill; optionally one outline pass for crisp edges; one or two passes, aiming for a uniform white or bright mark with no depth required (the anodize is only microns thick).
- **CO2 laser (10.6 um): second choice.** It cannot mark bare aluminum but can bleach dyed anodize white. Its larger spot (about 0.1 to 0.2 mm) can partly fill the 0.35 mm gaps inside the letters, so ask for a test first.
- **Diode lasers** can bleach anodize too, but slowly and with softer edges: fine for a trial, not the first pick.
- Expect a light satin mark rather than mirror chrome; judge it on the test piece.

## What to send the shop

1. `{name}.dxf` (or `.svg`): "filled area is the engrave area, mm units, do not scale".
2. `face_logo_placement.svg` (print it at 100 percent) or the numbers above: centred on the window, {window:.2f} mm above its back edge.
3. The material, finish and fixturing notes above.
4. Process: fiber laser fill engrave, mark to white or bright metal, no depth.
5. **A test piece first:** add one `mx_coupon.dxf` coupon, black anodized, to the SendCutSend case order and have the shop run the mark and a couple of power settings on it before touching the cover.
6. Quantity, and ask them to keep the job file so later units match.

Trophy and award shops, sign shops and makerspaces often have a fiber marker. A mark this small is usually a minimum-charge job; no quotes were collected.

## Not verified

- No test mark has been made, so how the mark looks on SendCutSend's black anodize is unverified.
- The DXF was read back with ezdxf only, not opened in LightBurn or EzCAD (it is plain R2010 closed polylines, which they import).
"""
