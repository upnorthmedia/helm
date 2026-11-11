"""Draw the four keycap icons for Max Keyboard's custom backlit caps.

Run from the repository root:

    uv run --with shapely==2.2.0 --with pillow python docs/build/keycaps/make_keycaps.py

Each icon is built as filled outlines (no SVG strokes, so the vendor's
software cannot thin or drop them) on a 1000 x 1000 canvas with a white
background. Black is the shine-through area, as the listing states. Every
line has the same width, and each icon is centred in the middle 60 percent.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from shapely import affinity
from shapely.geometry import LineString, Point
from shapely.ops import unary_union

OUT = Path(__file__).resolve().parent
CANVAS = 1000
BOX = 600  # icons fit inside the middle 60 percent
STROKE = 90  # one line width for all four icons, 9 percent of the canvas
HALF = STROKE / 2


def line(*points):
    return LineString(points).buffer(HALF, cap_style="round", join_style="round", quad_segs=32)


def ring(r):
    """A circle outline whose outer edge has radius r."""
    mid = r - HALF
    return Point(0, 0).buffer(mid + HALF, quad_segs=64).difference(Point(0, 0).buffer(mid - HALF, quad_segs=64))


def later():
    # A clock face with the minute hand at twelve and the hour hand at three,
    # both kept well clear of the rim so the gap stays dark.
    r = BOX / 2
    return unary_union([ring(r), line((0, 0), (0, -110)), line((0, 0), (95, 0))])


def hold():
    gap = 160  # dark space between the bars
    x = (gap + STROKE) / 2
    h = BOX / 2 - HALF
    return unary_union([line((-x, -h), (-x, h)), line((x, -h), (x, h))])


def showme():
    # The render's SHOW ME: a ring with a dot in the middle.
    r = BOX / 2
    return unary_union([ring(r), Point(0, 0).buffer(110, quad_segs=64)])


def check_mark():
    # The render's check mark (assembly.py `_legend`), in render millimetres:
    # a short stroke down to the joint, a long one up. Scale its centreline so
    # the finished mark spans BOX across, then outline it at STROKE.
    pts = [(-4.0, -0.5), (-1.3, 2.5), (4.5, -3.5)]
    k = (BOX - STROKE) / (max(p[0] for p in pts) - min(p[0] for p in pts))
    return line(*[(x * k, y * k) for x, y in pts])


def centred(shape):
    x0, y0, x1, y1 = shape.bounds
    return affinity.translate(shape, CANVAS / 2 - (x0 + x1) / 2, CANVAS / 2 - (y0 + y1) / 2)


ICONS = {
    "yes": ("YES", check_mark),
    "later": ("LATER", later),
    "hold": ("HOLD", hold),
    "showme": ("SHOW ME", showme),
}


def polygons(shape):
    return list(getattr(shape, "geoms", [shape]))


def svg(shape, label):
    def ring_path(coords):
        pts = list(coords)[:-1]
        return "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in pts) + " Z"

    d = " ".join(
        ring_path(p.exterior.coords) + "".join(" " + ring_path(i.coords) for i in p.interiors) for p in polygons(shape)
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{CANVAS}" height="{CANVAS}" viewBox="0 0 {CANVAS} {CANVAS}">\n'
        f"  <title>Helm keycap: {label}. Black is the shine-through area.</title>\n"
        f'  <rect width="{CANVAS}" height="{CANVAS}" fill="#ffffff"/>\n'
        f'  <path fill="#000000" fill-rule="evenodd" d="{d}"/>\n'
        "</svg>\n"
    )


def mask(shape, size=CANVAS, oversample=4):
    """The icon as an 8-bit mask (255 = icon), antialiased by oversampling."""
    big = size * oversample
    k = big / CANVAS
    img = Image.new("L", (big, big), 0)
    draw = ImageDraw.Draw(img)
    # Largest first, so a ring's hole never paints over the hands or dot inside it.
    for p in sorted(polygons(shape), key=lambda p: p.area, reverse=True):
        draw.polygon([(x * k, y * k) for x, y in p.exterior.coords], fill=255)
        for hole in p.interiors:
            draw.polygon([(x * k, y * k) for x, y in hole.coords], fill=0)
    return img.resize((size, size), Image.LANCZOS)


def bilevel_png(shape, path):
    """1-bit black on white, thresholded from the antialiased mask."""
    m = mask(shape)
    Image.eval(m, lambda v: 0 if v >= 128 else 255).convert("1", dither=Image.NONE).save(path, optimize=True)


def lit_cap(shape, size=360):
    """A preview of the icon lit through a black cap (not a vendor proof)."""
    cap = Image.new("RGB", (size, size), (238, 240, 243))
    draw = ImageDraw.Draw(cap)
    pad = size * 0.06
    draw.rounded_rectangle([pad, pad, size - pad, size - pad], radius=size * 0.11, fill=(22, 22, 24))
    top = size * 0.15
    draw.rounded_rectangle([top, top, size - top, size - top], radius=size * 0.08, fill=(34, 34, 37))
    # The icon spans the cap top as the vendor's guideline image shows it.
    art = int(size - 2 * top)
    m = mask(shape, art)
    glow = Image.new("RGB", (art, art), (255, 236, 170))
    halo = m.filter(ImageFilter.GaussianBlur(art * 0.025)).point(lambda v: int(v * 0.55))
    cap.paste(glow, (int(top), int(top)), halo)
    cap.paste(Image.new("RGB", (art, art), (255, 248, 222)), (int(top), int(top)), m)
    return cap


def contact_sheet(shapes, path):
    cell, label_h, margin = 360, 70, 40
    sheet = Image.new("RGB", (margin * 2 + cell * len(shapes), margin * 2 + cell + label_h), (238, 240, 243))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=34)
    for n, (label, shape) in enumerate(shapes):
        x = margin + n * cell
        sheet.paste(lit_cap(shape, cell), (x, margin))
        w = draw.textlength(label, font=font)
        draw.text((x + (cell - w) / 2, margin + cell + 14), label, fill=(40, 40, 44), font=font)
    sheet.save(path, optimize=True)


def main():
    shapes = []
    for name, (label, build) in ICONS.items():
        shape = centred(build())
        x0, y0, x1, y1 = shape.bounds
        lo, hi = (CANVAS - BOX) / 2, (CANVAS + BOX) / 2
        assert lo - 0.5 <= min(x0, y0) and max(x1, y1) <= hi + 0.5, f"{name} leaves the middle 60 percent"
        (OUT / f"{name}.svg").write_text(svg(shape, label))
        bilevel_png(shape, OUT / f"{name}.png")
        shapes.append((label, shape))
    contact_sheet(shapes, OUT / "keycaps-lit.png")


if __name__ == "__main__":
    main()
