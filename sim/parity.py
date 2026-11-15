"""Compare every deck screen as the firmware draws it with the simulator's.

The firmware's screens come from firmware/host: the device core and
firmware/idf/main/ui.c under LVGL 9.5.0, the version the deck runs, drawn
into a 1280 x 720 RGB565 buffer. Both sides are driven by the same steps:
sim/snapshot.py builds each screen by calling the simulator's Deck, and a
recording Deck replays those calls on the firmware's deck, models as real
frames from helm/wire, at the same times.

Each screen is checked two ways.

Pixels. The simulator's shapes are painted without their text (rectangles,
ovals, lines) and compared with the firmware's image outside the text masks.
The fonts differ on purpose (Menlo there, LVGL's Montserrat on the deck), so
text is masked: every simulator text box (Menlo's advance width times the
character count, by the anchor) and the part of every LVGL label its text
covers, each grown by MASK_PAD. Outside the masks a pixel differs when any channel differs by more
than COLOR_TOLERANCE (RGB565 rounding is at most 7, the rest is anti-aliased
edges). A screen fails when more than MAX_DIFF_PIXELS pixels differ, or when
any TILE x TILE tile has more than MAX_TILE_SHARE of its pixels different,
which catches a small shape that moved or went missing.

Text. Every simulator string must be drawn by a firmware label, and every
label must be one the simulator draws, with the simulator's anchor point
inside the label's box grown by POSITION_PAD. Strings match when equal after
collapsing whitespace, or when one is a line of the other (a wrapped
paragraph), or when one was cut with "..." and the other starts with what is
left. Menlo is wider than Montserrat, so the simulator wraps a paragraph onto
more lines: a line of a paragraph may sit lower, down to PARAGRAPH_STRETCH
times the firmware paragraph's height below its top.

    python -m sim.parity --harness build/host/helm_screens --out OUT_DIR

writes, per screen, the firmware's image (`<screen>.fw.png`), the
simulator's shapes (`<screen>.sim.png`), and the differences
(`<screen>.diff.png`: red where pixels differ, grey where masked), prints a
line per screen, and exits 1 when any screen fails. Needs Pillow, a
development tool like it is for sim/snapshot.py; scripts/test-screens.sh
builds the harness and runs this.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from helm import contract as c
from helm.wire import codec
from sim import render, snapshot
from sim.state import Deck

# The tolerances, in one place. Changing one is a reviewed change to what "matches" means.
MASK_PAD = 4  # px added on every side of each text box before masking
COLOR_TOLERANCE = 10  # largest per-channel difference that still counts as the same color (RGB565 rounds by up to 7)
MAX_DIFF_PIXELS = 400  # differing pixels allowed outside the masks, per screen (anti-aliased edges)
TILE = 16  # px, the side of a tile for the local check
MAX_TILE_SHARE = 0.30  # share of one tile's pixels that may differ
POSITION_PAD = 6  # px a simulator anchor may sit outside its firmware label's box
PARAGRAPH_STRETCH = 1.6  # how much taller the simulator's wrapping of a paragraph may run
LINE_HEIGHT = 1.25  # Menlo's line box, in ems, for the simulator's text boxes (generous: it is a mask)

ANCHOR_X = {"nw": 0.0, "w": 0.0, "sw": 0.0, "n": 0.5, "center": 0.5, "s": 0.5, "ne": 1.0, "e": 1.0, "se": 1.0}
ANCHOR_Y = {"nw": 0.0, "n": 0.0, "ne": 0.0, "w": 0.5, "center": 0.5, "e": 0.5, "sw": 1.0, "s": 1.0, "se": 1.0}
CUT = "..."


@dataclass
class RecordingDeck(Deck):
    """The simulator's deck, keeping each input with its time so the firmware's deck can be given the same."""

    steps: list[tuple] = field(default_factory=list)

    def on_model(self, model: c.Model, now: float) -> None:
        self.steps.append(("model", now, codec.encode_model(model).hex()))
        super().on_model(model, now)

    def knob(self, delta: int, now: float) -> None:
        self.steps.append(("knob", now, str(delta)))
        super().knob(delta, now)

    def knob_press(self, long: bool, now: float) -> None:
        self.steps.append(("press", now, "1" if long else "0"))
        super().knob_press(long, now)

    def key_down(self, key: str, now: float) -> None:
        self.steps.append(("key", now, key, "down"))
        super().key_down(key, now)

    def key_up(self, key: str, now: float) -> None:
        self.steps.append(("key", now, key, "up"))
        super().key_up(key, now)

    def tick(self, now: float) -> None:
        self.steps.append(("tick", now))
        super().tick(now)


def ms(t: float) -> int:
    return int(round(t * 1000))


def harness_script(deck: RecordingDeck, now: float, image: Path, labels: Path) -> str:
    lines = [" ".join([op, str(ms(t)), *rest]) for op, t, *rest in deck.steps]
    lines.append("render %d %s %s" % (ms(now), image, labels))
    return "\n".join(lines) + "\n"


# The simulator's side.


@dataclass
class TextBox:
    text: str
    x: float  # the anchor point, in screen coordinates
    y: float
    box: tuple[float, float, float, float]


def screen_shapes(deck: Deck, now: float) -> list[render.Shape]:
    return render.render(deck, now, render.View(mode="fixture data"))


def _on_screen(x: float, y: float) -> bool:
    return render.SCREEN_X <= x <= render.SCREEN_X + render.SCREEN_W and render.SCREEN_Y <= y <= render.SCREEN_Y + render.SCREEN_H


def sim_texts(shapes: list[render.Shape]) -> list[TextBox]:
    """Each piece of text on the screen, with the box Menlo gives it, in screen coordinates."""
    out = []
    for sh in shapes:
        if not isinstance(sh, render.Text) or not sh.text.strip() or not _on_screen(sh.x, sh.y):
            continue
        w = len(sh.text) * sh.size * render.CHAR_W
        h = sh.size * LINE_HEIGHT
        x0 = sh.x - render.SCREEN_X - w * ANCHOR_X[sh.anchor]
        y0 = sh.y - render.SCREEN_Y - h * ANCHOR_Y[sh.anchor]
        out.append(TextBox(sh.text, sh.x - render.SCREEN_X, sh.y - render.SCREEN_Y, (x0, y0, x0 + w, y0 + h)))
    return out


def paint_shapes(shapes: list[render.Shape]):
    """The screen's shapes without text, at 1280 x 720, edges exclusive as LVGL draws them."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (render.WINDOW_W, render.WINDOW_H))
    draw = ImageDraw.Draw(img)
    for sh in shapes:
        if isinstance(sh, (render.Rect, render.Oval)):
            box = [round(sh.x0), round(sh.y0), round(sh.x1) - 1, round(sh.y1) - 1]
            if box[2] < box[0] or box[3] < box[1]:
                continue
            fn = draw.rectangle if isinstance(sh, render.Rect) else draw.ellipse
            fn(box, fill=sh.fill, outline=sh.outline, width=sh.width if sh.outline else 0)
        elif isinstance(sh, render.Line):
            draw.line([round(p) for p in sh.points], fill=sh.fill, width=sh.width)
    x0, y0 = render.SCREEN_X, render.SCREEN_Y
    return img.crop((x0, y0, x0 + render.SCREEN_W, y0 + render.SCREEN_H))


# Matching text.


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _core(text: str) -> tuple[str, bool]:
    """The text without a trailing cut mark, and whether it had one."""
    t = _norm(text)
    if t.endswith(CUT):
        return t[: -len(CUT)].rstrip(), True
    return t, False


def same_text(a: str, b: str) -> bool:
    """True when a and b are the same words as two renderers would draw them: equal, one a line of the
    other (a wrapped paragraph), or one cut with "..." where the other goes on."""
    (ca, cut_a), (cb, cut_b) = _core(a), _core(b)
    if ca == cb or line_of(a, b) or line_of(b, a):
        return True
    return (cut_a and cb.startswith(ca)) or (cut_b and ca.startswith(cb))


def line_of(line: str, paragraph: str) -> bool:
    """True when `line` is part of `paragraph` and not all of it."""
    cl, cp = _core(line)[0], _core(paragraph)[0]
    return bool(cl) and cl != cp and cl in cp


def placed(t: TextBox, label: dict) -> bool:
    """True when the simulator's anchor for t lies in the firmware label's box, give or take POSITION_PAD.
    A line of a wrapped paragraph may run lower, as the simulator's wider font wraps onto more lines."""
    x0, y0, x1, y1 = _box(label)
    if line_of(t.text, label["text"]):
        y1 = y0 + (y1 - y0) * PARAGRAPH_STRETCH
    pad = POSITION_PAD
    return x0 - pad <= t.x <= x1 + pad and y0 - pad <= t.y <= y1 + pad


def text_problems(sim: list[TextBox], fw: list[dict]) -> list[str]:
    """Simulator strings no firmware label draws there, and firmware labels the simulator does not draw."""
    labels = [lab for lab in fw if lab["text"].strip()]
    problems = []
    for t in sim:
        if not any(same_text(t.text, lab["text"]) and placed(t, lab) for lab in labels):
            problems.append("simulator text %r at (%d, %d) is not drawn there by the firmware" % (t.text, t.x, t.y))
    for lab in labels:
        if not any(same_text(t.text, lab["text"]) and placed(t, lab) for t in sim):
            problems.append("firmware label %r at %s is not in the simulator" % (lab["text"], _box(lab)))
    return problems


def _box(label: dict) -> tuple[float, float, float, float]:
    return (label["x0"], label["y0"], label["x1"], label["y1"])


def _ink(label: dict) -> tuple[float, float, float, float]:
    """The part of the label its text covers."""
    return (label["ix0"], label["iy0"], label["ix1"], label["iy1"])


# Comparing pixels.


@dataclass
class PixelResult:
    differing: int
    worst_tile: float
    masked_share: float
    diff_image: object  # PIL image: red where pixels differ, grey where masked


def compare_pixels(fw_img, sim_img, boxes: list[tuple[float, float, float, float]]) -> PixelResult:
    from PIL import Image, ImageChops, ImageDraw

    size = (render.SCREEN_W, render.SCREEN_H)
    diff = ImageChops.difference(fw_img.convert("RGB"), sim_img.convert("RGB"))
    r, g, b = diff.split()
    worst = ImageChops.lighter(ImageChops.lighter(r, g), b)
    differs = worst.point(lambda v: 255 if v > COLOR_TOLERANCE else 0)
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    for x0, y0, x1, y1 in boxes:
        draw.rectangle([x0 - MASK_PAD, y0 - MASK_PAD, x1 + MASK_PAD, y1 + MASK_PAD], fill=255)
    differs.paste(0, mask=mask)
    differing = differs.histogram()[255]
    tiles = differs.reduce(TILE)
    worst_tile = tiles.getextrema()[1] / 255
    masked_share = mask.histogram()[255] / (size[0] * size[1])
    shown = Image.blend(fw_img.convert("RGB"), Image.new("RGB", size), 0.6)
    shown.paste((90, 90, 90), mask=mask)
    shown.paste((255, 40, 40), mask=differs)
    return PixelResult(differing, worst_tile, masked_share, shown)


# Running it.


@dataclass
class ScreenResult:
    name: str
    pixels: PixelResult
    text: list[str]

    @property
    def problems(self) -> list[str]:
        out = list(self.text)
        if self.pixels.differing > MAX_DIFF_PIXELS:
            out.append("%d pixels differ outside the text masks (at most %d)" % (self.pixels.differing, MAX_DIFF_PIXELS))
        if self.pixels.worst_tile > MAX_TILE_SHARE:
            out.append("a %d px tile is %.0f%% different (at most %.0f%%)"
                       % (TILE, 100 * self.pixels.worst_tile, 100 * MAX_TILE_SHARE))
        return out


def check_screen(name: str, deck: RecordingDeck, now: float, harness: Path, out_dir: Path) -> ScreenResult:
    from PIL import Image

    ppm, labels_path = out_dir / ("%s.fw.ppm" % name), out_dir / ("%s.labels.json" % name)
    done = subprocess.run([str(harness)], input=harness_script(deck, now, ppm, labels_path), capture_output=True,
                          text=True, timeout=60)
    if done.returncode != 0:
        raise RuntimeError("%s: the harness exited %d: %s" % (name, done.returncode, done.stderr.strip()))
    fw_img = Image.open(ppm).convert("RGB")
    fw_img.save(out_dir / ("%s.fw.png" % name))
    ppm.unlink()
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    shapes = screen_shapes(deck, now)
    sim_img = paint_shapes(shapes)
    sim_img.save(out_dir / ("%s.sim.png" % name))
    texts = sim_texts(shapes)
    pixels = compare_pixels(fw_img, sim_img, [t.box for t in texts] + [_ink(lab) for lab in labels])
    pixels.diff_image.save(out_dir / ("%s.diff.png" % name))
    return ScreenResult(name, pixels, text_problems(texts, labels))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m sim.parity", description=__doc__.split("\n\n")[0])
    parser.add_argument("--harness", type=Path, required=True, help="firmware/host's helm_screens, built")
    parser.add_argument("--out", type=Path, required=True, help="where to write the images")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    results = [check_screen(name, deck, now, args.harness, args.out)
               for name, (deck, now) in snapshot.screens(RecordingDeck).items()]
    failed = 0
    for res in results:
        p = res.pixels
        status = "FAIL" if res.problems else "ok"
        print("%-15s %-4s %5d px differ, worst tile %3.0f%%, %2.0f%% masked"
              % (res.name, status, p.differing, 100 * p.worst_tile, 100 * p.masked_share))
        for problem in res.problems:
            print("    " + problem)
        failed += bool(res.problems)
    print("%d of %d screens match within the tolerances; images in %s" % (len(results) - failed, len(results), args.out))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
