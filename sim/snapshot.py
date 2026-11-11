"""Paint the simulator's shapes to a PNG with Pillow, with no window.

Used for the screenshots in docs and PRs: the same shape list the window
paints, so there is no screen capture (which would also catch whatever else
is on the desktop). Pillow is a development tool here, not a runtime
dependency of the simulator.

    python -m sim.snapshot OUT_DIR

writes one PNG per screen from fixture data.
"""

from __future__ import annotations

import argparse
import copy
from pathlib import Path

from sim import fixtures, render
from sim.state import Deck

FONT_FILE = "/System/Library/Fonts/Menlo.ttc"
ANCHORS = {"nw": "la", "n": "ma", "ne": "ra", "w": "lm", "center": "mm", "e": "rm", "sw": "ld", "s": "md", "se": "rd"}


def paint(shapes: list[render.Shape], path: Path, scale: int = 2) -> None:
    from PIL import Image, ImageDraw, ImageFont

    fonts: dict[tuple[int, bool], ImageFont.FreeTypeFont] = {}

    def font(size: int, bold: bool) -> ImageFont.FreeTypeFont:
        key = (size, bold)
        if key not in fonts:
            fonts[key] = ImageFont.truetype(FONT_FILE, size * scale, index=1 if bold else 0)
        return fonts[key]

    img = Image.new("RGB", (render.WINDOW_W * scale, render.WINDOW_H * scale))
    draw = ImageDraw.Draw(img)
    for sh in shapes:
        if isinstance(sh, (render.Rect, render.Oval)):
            box = [sh.x0 * scale, sh.y0 * scale, sh.x1 * scale, sh.y1 * scale]
            fn = draw.rectangle if isinstance(sh, render.Rect) else draw.ellipse
            fn(box, fill=sh.fill, outline=sh.outline, width=sh.width * scale if sh.outline else 0)
        elif isinstance(sh, render.Text):
            draw.text((sh.x * scale, sh.y * scale), sh.text, fill=sh.fill, font=font(sh.size, sh.bold), anchor=ANCHORS[sh.anchor])
        elif isinstance(sh, render.Line):
            draw.line([p * scale for p in sh.points], fill=sh.fill, width=sh.width * scale)
    img.save(path)


def screens() -> dict[str, tuple[Deck, float]]:
    """One deck per screen, built by driving the real state machine."""
    t = 1000.0
    out: dict[str, tuple[Deck, float]] = {}

    def fresh() -> Deck:
        deck = Deck()
        deck.on_model(fixtures.busy(seq=2), t)
        deck.take_outbox()
        return deck

    out["home"] = (fresh(), t + 0.3)

    calm = Deck()
    calm.on_model(fixtures.calm(seq=1), t)
    out["home-calm"] = (calm, t)

    near = Deck()
    near.on_model(fixtures.calm_near_limit(seq=1), t)
    out["home-context"] = (near, t)

    deck = fresh()
    deck.knob(1, t)
    deck.knob(1, t)
    out["list"] = (deck, t)

    deck = copy.deepcopy(deck)
    deck.knob_press(False, t)
    out["detail"] = (deck, t)

    deck = fresh()
    deck.key_down("yes", t)
    out["confirm"] = (deck, t + 0.6)

    deck = fresh()
    deck.key_down("yes", t)
    deck.tick(t + 1.0)
    replied = fixtures.busy(seq=3)
    from helm import contract as c

    replied.result = c.Result(request_id="helm-yes-fixture", state="replied", text="Firstmate: done. Fixture reply, nothing was changed.")
    deck.on_model(replied, t + 2)
    out["result"] = (deck, t + 2)

    stale = Deck()
    stale.on_model(fixtures.stale(seq=4), t)
    out["home-unknown"] = (stale, t)

    # The knob on Home turns to the widget-api view; a press opens its list.
    deck = Deck()
    deck.on_model(fixtures.projects(seq=5), t)
    deck.knob(-1, t)
    out["home-view"] = (deck, t + 0.3)
    deck = copy.deepcopy(deck)
    deck.knob_press(False, t)
    out["list-view"] = (deck, t)

    away = Deck()
    away.on_model(fixtures.away(seq=6), t)
    out["home-away"] = (away, t + 0.3)

    locked = Deck()
    locked.on_model(fixtures.mac_locked(seq=7), t)
    out["home-locked"] = (locked, t + 0.3)

    # Answers waiting on firstmate: the list says which item has one, the result how far it got.
    deck = Deck()
    deck.on_model(fixtures.answered(seq=8), t)
    deck.knob(1, t)
    out["list-answered"] = (deck, t)

    deck = fresh()
    deck.key_down("yes", t)
    deck.tick(t + 1.0)
    deck.on_model(fixtures.answered(seq=8), t + 2)
    out["result-seen"] = (deck, t + 2)

    deck = fresh()
    deck.knob(1, t)
    deck.knob(1, t)
    deck.key_down("hold", t)
    deck.tick(t + 1.0)
    deck.on_model(fixtures.stalled(seq=9), t + 2)
    out["result-stalled"] = (deck, t + 2)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m sim.snapshot", description="Write a PNG of each simulator screen.")
    parser.add_argument("out_dir", type=Path)
    args = parser.parse_args(argv)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for name, (deck, now) in screens().items():
        path = args.out_dir / f"{name}.png"
        paint(render.render(deck, now, render.View(mode="fixture data")), path)
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
