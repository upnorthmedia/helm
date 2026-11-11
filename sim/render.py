"""Deck state to a flat list of shapes for the whole simulator window.

The window (sim/app.py, tkinter) and the headless PNG exporter
(sim/snapshot.py) paint the same list, so screenshots match the live window
without capturing the desktop. Text is set in Menlo, a monospace font, so
wrapping is decided here and comes out the same in both painters.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from helm import contract as c
from sim.state import HOLD_KEYS, KEY_LABELS, Deck

# The Waveshare ESP32-P4-WIFI6-Touch-LCD-5 turned landscape: 1280 x 720. The
# window follows the case's face: the screen on top, then the keys, the light
# bar, and the knob in one row below it.
WINDOW_W, WINDOW_H = 1400, 940
SCREEN_X, SCREEN_Y = 60, 40
SCREEN_W, SCREEN_H = 1280, 720
FONT = "Menlo"
CHAR_W = 0.602  # Menlo advance width, in ems

COLORS = {
    "body": "#1b1d22",
    "bezel": "#060708",
    "screen": "#0f1115",
    "panel": "#1a1d23",
    "panel_hi": "#262a32",
    "text": "#ebe8e3",
    "dim": "#8b919b",
    "faint": "#4a4f58",
    "off": "#2a2d33",
    "red": "#ef4b4b",
    "amber": "#f0a92e",
    "blue": "#4c9ef5",
    "green": "#43c26b",
    "white": "#e9edf2",
}
KEY_COLORS = {"yes": "green", "later": "blue", "hold": "amber", "focus": "white"}
KEY_SHORTCUTS = {"yes": "Y", "later": "L", "hold": "H", "focus": "S"}
KIND_LABELS = {
    "decision": "decision",
    "pr_ready": "PR ready",
    "worker_problem": "worker problem",
    "herdr_blocked": "herdr blocked",
}
KEY_RECTS = {
    "yes": (60, 784, 180, 884),
    "later": (196, 784, 316, 884),
    "hold": (332, 784, 452, 884),
    "focus": (468, 784, 588, 884),
}
KNOB_CENTER, KNOB_R = (1268, 840), 54
LED_COUNT = 8
BAR_X0, BAR_X1, BAR_Y0, BAR_Y1 = 630, 1062, 812, 848  # the light bar's bezel
LIGHT_Y0, LIGHT_Y1 = 818, 842
# Home's right column: the view's items, as the list shows them, smaller.
COLUMN_X0, COLUMN_X1 = 740, SCREEN_W - 40
COLUMN_ROWS = 5
LIST_ROWS, LIST_TOP, LIST_ROW_H, LIST_GAP = 6, 132, 80, 6
VIEW_LABEL_W = 260  # the project view's label in the status strip
CONTEXT_HINT = 0.30  # calm: the last light, amber, while an agent is near its context limit
# White mixed into a kind's color for each project tint (firmware/core/helm_lights.h
# explains the rule): tint 0 is an item with no project.
TINT_WHITE_PERMILLE = (0, 180, 360, 540)


@dataclass
class Rect:
    x0: float
    y0: float
    x1: float
    y1: float
    fill: str | None
    outline: str | None = None
    width: int = 0


@dataclass
class Oval:
    x0: float
    y0: float
    x1: float
    y1: float
    fill: str | None
    outline: str | None = None
    width: int = 0


@dataclass
class Text:
    x: float
    y: float
    text: str
    fill: str
    size: int
    bold: bool = False
    anchor: str = "nw"  # tk anchors: nw n ne w center e sw s se


@dataclass
class Line:
    points: list[float]
    fill: str
    width: int = 1


Shape = Rect | Oval | Text | Line


@dataclass
class View:
    """What the window shows beyond the deck itself."""

    mode: str = ""  # "fake mode", or the port path
    keys_down: set[str] = field(default_factory=set)
    knob_down: bool = False


def mix(color: str, factor: float, base: str = COLORS["off"]) -> str:
    a = [int(color[i : i + 2], 16) for i in (1, 3, 5)]
    b = [int(base[i : i + 2], 16) for i in (1, 3, 5)]
    f = max(0.0, min(1.0, factor))
    return "#" + "".join(f"{round(bb + (aa - bb) * f):02x}" for aa, bb in zip(a, b))


def wrap(text: str, size: int, width_px: float) -> list[str]:
    per_line = max(8, int(width_px / (size * CHAR_W)))
    lines: list[str] = []
    for para in text.split("\n"):
        line = ""
        for word in para.split():
            while len(word) > per_line:
                if line:
                    lines.append(line)
                    line = ""
                lines.append(word[:per_line])
                word = word[per_line:]
            candidate = f"{line} {word}" if line else word
            if len(candidate) > per_line:
                lines.append(line)
                line = word
            else:
                line = candidate
        lines.append(line)
    return lines


def clip(text: str, size: int, width_px: float) -> str:
    n = max(4, int(width_px / (size * CHAR_W)))
    return text if len(text) <= n else text[: n - 3] + "..."


def age(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


def answer_tag(item: c.Item) -> str | None:
    """"YES sent" while the item's answer waits on firstmate's reply."""
    return f"{KEY_LABELS[item.pending]} sent" if item.pending else None


def result_progress(result: c.Result) -> tuple[str, str] | None:
    """A queued note's progress line and its color, or None when the bridge sent no wait time."""
    if result.state != "queued" or result.waited_s is None:
        return None
    sent = f"sent {age(result.waited_s)} ago"
    if result.seen:
        return f"{sent}, firstmate has read it", "dim"
    if result.stalled:
        return f"firstmate has not picked this up: {sent}", "amber"
    return f"{sent}, waiting for firstmate to read it", "dim"


def project_tint(project: str | None) -> int:
    """0 for no project, else 1 + (32-bit FNV-1a of its UTF-8 bytes) % 3, as helm_lights_project_tint."""
    if not project:
        return 0
    h = 2166136261
    for byte in project.encode("utf-8"):
        h = ((h ^ byte) * 16777619) & 0xFFFFFFFF
    return 1 + h % (len(TINT_WHITE_PERMILLE) - 1)


def tinted(color: str, tint: int) -> str:
    """`color` with the tint's share of pure white mixed in: paler, never another hue."""
    p = TINT_WHITE_PERMILLE[tint]
    rgb = [int(color[i : i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{v + ((255 - v) * p + 500) // 1000:02x}" for v in rgb)


def item_light(item: c.Item) -> str:
    """An item's color on the light bar and its list row: its kind's color, tinted by its project."""
    return tinted(COLORS[item.color], project_tint(item.project))


def context_line(x: c.Context) -> str:
    """The context gauge as one line: "Context  fm-25m 64% used  2 near limit"."""
    if x.top_used is None:
        return "Agent context unknown"
    near = f"  {x.near_limit} near limit" if x.near_limit else ""
    return f"Context  {x.top_agent or '?'} {x.top_used}% used{near}"


def gauge_lights(u: c.Usage) -> int | None:
    """Lights the calm bar fills: what is left of the tighter window, out of 8,
    rounded up. None when either window is unknown, which lights none."""
    if u.five_hour_left is None or u.week_left is None:
        return None
    left = max(0, min(100, min(u.five_hour_left, u.week_left)))
    return (left * LED_COUNT + 99) // 100


def usage_line(u: c.Usage) -> str:
    """The usage gauge as one line: "Claude left  5h 62% for 1h  week 40% for 3d"."""
    if u.five_hour_left is None and u.week_left is None:
        return "Claude usage unknown"
    parts = []
    for name, left, resets in (("5h", u.five_hour_left, u.five_hour_resets_s), ("week", u.week_left, u.week_resets_s)):
        if left is None:
            parts.append(f"{name} ?")
        else:
            parts.append(f"{name} {left}%" + (f" for {age(resets)}" if resets is not None else ""))
    return "Claude left  " + "  ".join(parts)


class _Screen:
    """Shapes in screen coordinates (0..1280 across, 0..720 down), shifted into the window."""

    def __init__(self, out: list[Shape]) -> None:
        self.out = out

    def rect(self, x0, y0, x1, y1, fill, outline=None, width=0):
        self.out.append(Rect(SCREEN_X + x0, SCREEN_Y + y0, SCREEN_X + x1, SCREEN_Y + y1, fill, outline, width))

    def oval(self, x0, y0, x1, y1, fill, outline=None, width=0):
        self.out.append(Oval(SCREEN_X + x0, SCREEN_Y + y0, SCREEN_X + x1, SCREEN_Y + y1, fill, outline, width))

    def text(self, x, y, text, fill, size, bold=False, anchor="nw"):
        self.out.append(Text(SCREEN_X + x, SCREEN_Y + y, text, fill, size, bold, anchor))


def render(deck: Deck, now: float, view: View) -> list[Shape]:
    out: list[Shape] = [Rect(0, 0, WINDOW_W, WINDOW_H, COLORS["body"])]
    _light_bar(out, deck, now)
    out.append(Rect(SCREEN_X - 14, SCREEN_Y - 14, SCREEN_X + SCREEN_W + 14, SCREEN_Y + SCREEN_H + 14, COLORS["bezel"]))
    out.append(Rect(SCREEN_X, SCREEN_Y, SCREEN_X + SCREEN_W, SCREEN_Y + SCREEN_H, COLORS["screen"]))
    s = _Screen(out)
    _status_strip(s, deck, now)
    {
        "home": _home,
        "list": _list,
        "detail": _detail,
        "confirm": _confirm,
        "result": _result,
    }[deck.screen](s, deck, now)
    _knob(out, deck, view)
    _keys(out, deck, now, view)
    footer = f"Helm simulator  |  {view.mode}" if view.mode else "Helm simulator"
    out.append(Text(SCREEN_X, WINDOW_H - 30, footer, COLORS["faint"], 16))
    out.append(Text(SCREEN_X + SCREEN_W, WINDOW_H - 30, "arrows/wheel turn  Enter press  M mute", COLORS["faint"], 14, anchor="ne"))
    return out


def _light_bar(out: list[Shape], deck: Deck, now: float) -> None:
    attention = deck.attention(now)
    colors: list[str]
    if now < deck.sweep_until:
        head = (now * 10) % (LED_COUNT + 3)
        colors = [mix(COLORS["green"], 1 - min(1, abs(i - head) / 2.5)) for i in range(LED_COUNT)]
    elif attention == "unknown":
        colors = [mix(COLORS["amber"], 0.55)] * LED_COUNT
    elif attention == "new":
        pulse = 0.55 + 0.45 * (0.5 + 0.5 * math.sin(now * 2 * math.pi / 1.4))
        unseen = [i for i in deck.items if i.unseen][:LED_COUNT]
        colors = [mix(item_light(i), pulse) for i in unseen]
        colors += [COLORS["off"]] * (LED_COUNT - len(colors))
    else:
        # Calm: the usage gauge (firmware/core/helm_lights.c does the same).
        lit = gauge_lights(deck.model.usage) if deck.model else None
        colors = [mix(COLORS["white"], 0.12 if lit is not None and i < lit else 0.03) for i in range(LED_COUNT)]
        if deck.model and deck.model.context.near_limit:
            colors[-1] = mix(COLORS["amber"], CONTEXT_HINT)
    out.append(Rect(BAR_X0, BAR_Y0, BAR_X1, BAR_Y1, COLORS["bezel"]))
    step = (BAR_X1 - BAR_X0) / LED_COUNT
    for i, color in enumerate(colors):
        x = BAR_X0 + i * step + step / 2
        out.append(Oval(x - 22, LIGHT_Y0, x + 22, LIGHT_Y1, color))


def _status_strip(s: _Screen, deck: Deck, now: float) -> None:
    s.rect(0, 0, SCREEN_W, 60, COLORS["panel"])
    # Right side, from the edge in: MUTED, then the project view when there is more than one.
    right, left_w = SCREEN_W - 22, 900
    if deck.muted:
        s.text(right, 30, "MUTED", COLORS["dim"], 22, bold=True, anchor="e")
        right -= 96
    if deck.projects():
        s.text(right, 30, clip(f"view: {deck.view or 'all'}", 22, VIEW_LABEL_W), COLORS["text"], 22, anchor="e")
        left_w = right - VIEW_LABEL_W - 64
    reason = deck.link_down_reason(now)
    if reason is not None:
        s.oval(22, 21, 40, 39, COLORS["amber"])
        s.text(52, 30, clip(reason, 22, left_w), COLORS["amber"], 22, anchor="w")
    elif deck.mac_locked:
        # Not a fault either: every key is dark until the Mac is unlocked.
        s.oval(22, 21, 40, 39, COLORS["blue"])
        s.text(52, 30, clip("Mac locked: keys locked", 22, left_w), COLORS["text"], 22, anchor="w")
    elif deck.away:
        # Follow away mode: not a fault, so blue rather than amber, and it says what it means.
        assert deck.model is not None
        s.oval(22, 21, 40, 39, COLORS["blue"])
        s.text(52, 30, clip(f"firstmate {deck.model.link.posture or 'away'}: keys locked", 22, left_w), COLORS["text"], 22, anchor="w")
    else:
        assert deck.model is not None
        posture = deck.model.link.posture or "listening"
        s.oval(22, 21, 40, 39, COLORS["green"])
        s.text(52, 30, clip(f"firstmate {posture}", 22, left_w), COLORS["text"], 22, anchor="w")


def _chip(s: _Screen, x: float, y: float, color: str, size: int = 26) -> None:
    s.rect(x, y, x + size, y + size, COLORS[color])


def _item_row(s: _Screen, item: c.Item, x0: float, x1: float, y: float, h: float, selected: bool, id_size: int) -> None:
    """One item as a row: tinted strip, short id, kind and project (and the answer sent), NEW, age."""
    small = id_size < 34
    badge_right = x1 - (110 if small else 130)
    # Text runs up to the NEW badge, or to the age when there is none.
    text_w = (badge_right - 90 if item.unseen else x1 - 90) - (x0 + 36)
    s.rect(x0, y, x1, y + h, COLORS["panel_hi" if selected else "panel"], COLORS["text"] if selected else None, 2 if selected else 0)
    s.rect(x0, y, x0 + 14, y + h, item_light(item))
    s.text(x0 + 36, y + 10, clip(item.short_id, id_size, text_w), COLORS["text"], id_size, bold=True)
    kind = f"{KIND_LABELS[item.kind]}   {item.project}" if item.project else KIND_LABELS[item.kind]
    kind_w = text_w
    tag = answer_tag(item)
    if tag:
        # Right-aligned at the end of the text, in its key's color; the kind line gives way.
        s.text(x0 + 36 + text_w, y + h - 30, tag, COLORS[KEY_COLORS[item.pending]], 20, bold=True, anchor="ne")
        kind_w = text_w - len(tag) * 20 * CHAR_W - 20
    s.text(x0 + 36, y + h - 30, clip(kind, 20, kind_w), COLORS["dim"], 20)
    s.text(x1 - 24, y + h / 2, age(item.age_s), COLORS["dim"], 24 if small else 28, anchor="e")
    if item.unseen:
        s.rect(badge_right - 80, y + h / 2 - 16, badge_right, y + h / 2 + 16, COLORS[item.color])
        s.text(badge_right - 40, y + h / 2, "NEW", COLORS["screen"], 20, bold=True, anchor="center")


def _first_row(sel: int, count: int, rows: int) -> int:
    """The first row shown so the selection sits mid-window, as helm_deck_list_first."""
    return max(0, min(sel - rows // 2, count - rows))


def _home(s: _Screen, deck: Deck, now: float) -> None:
    attention = deck.attention(now)
    m = deck.model
    # Left column: the headline, the gauges, the counts.
    if attention == "unknown":
        s.text(40, 100, "Link unknown", COLORS["amber"], 56, bold=True)
        s.text(40, 175, "No green until the link is back.", COLORS["dim"], 24)
    elif attention == "new" and m is not None:
        s.text(40, 100, f"{m.unseen} new for you", COLORS["text"], 56, bold=True)
    else:
        s.text(40, 100, "All quiet", COLORS["text"], 56, bold=True)
    if m is None:
        return
    if attention != "unknown":
        s.text(40, 168, clip(usage_line(m.usage), 22, COLUMN_X0 - 80), COLORS["dim"], 22)
        near = bool(m.context.near_limit)
        s.text(40, 195, clip(context_line(m.context), 22, COLUMN_X0 - 80), COLORS["amber" if near else "dim"], 22)
    counts = m.counts
    tiles = [
        ("decisions", counts.decisions, "red"),
        ("working", counts.working, "text"),
        ("PRs ready", counts.prs_ready, "blue"),
        ("landed today", counts.landed_today, "green"),
    ]
    for n, (label, value, color) in enumerate(tiles):
        x = 40 + (n % 2) * 330
        y = 240 + (n // 2) * 150
        s.rect(x, y, x + 310, y + 130, COLORS["panel"])
        # Fail visible: nothing green while the link is unknown.
        if not value or (attention == "unknown" and color == "green"):
            fill = COLORS["dim"]
        else:
            fill = COLORS[color]
        s.text(x + 24, y + 14, str(value), fill, 60, bold=True)
        s.text(x + 24, y + 92, label, COLORS["dim"], 22)
    s.text(40, 548, f"herdr   {counts.herdr_working} working   {counts.herdr_blocked} blocked", COLORS["text"], 26)
    s.text(40, 590, f"queued  {counts.queued}", COLORS["dim"], 22)
    # Right column: what needs you in this view, the selection outlined.
    items = deck.visible
    x0, x1 = COLUMN_X0, COLUMN_X1
    title = f"Needs you in {deck.view} ({len(items)})" if deck.view else f"Needs you ({len(items)})"
    s.text(x0, 84, clip(title, 28, x1 - x0 - (110 if len(items) > COLUMN_ROWS else 0)), COLORS["text"], 28, bold=True)
    if not items:
        s.text(x0, 140, "Nothing needs you", COLORS["dim"], 24)
        return
    sel = deck.selected_index() or 0
    first = _first_row(sel, len(items), COLUMN_ROWS)
    for n, item in enumerate(items[first : first + COLUMN_ROWS]):
        _item_row(s, item, x0, x1, 132 + n * 90, 84, first + n == sel, 30)
    if len(items) > COLUMN_ROWS:
        s.text(x1, 90, f"{sel + 1}/{len(items)}", COLORS["dim"], 22, anchor="ne")
    hint = "press for list" if deck.projects() else "turn for list"
    s.text(x0, 610, hint, COLORS["faint"], 20, anchor="w")


def _list(s: _Screen, deck: Deck, now: float) -> None:
    items = deck.visible
    title = f"Needs you in {deck.view} ({len(items)})" if deck.view else f"Needs you ({len(items)})"
    rows = LIST_ROWS
    s.text(40, 80, clip(title, 32, SCREEN_W - 80 - (160 if len(items) > rows else 0)), COLORS["text"], 32, bold=True)
    sel = deck.selected_index() or 0
    first = _first_row(sel, len(items), rows)
    for n, item in enumerate(items[first : first + rows]):
        _item_row(s, item, 24, SCREEN_W - 24, LIST_TOP + n * (LIST_ROW_H + LIST_GAP), LIST_ROW_H, first + n == sel, 34)
    if len(items) > rows:
        s.text(SCREEN_W - 40, 92, f"{sel + 1}/{len(items)}", COLORS["dim"], 22, anchor="ne")
    s.text(40, 690, "turn: move   press: full text   hold a key to act", COLORS["faint"], 20, anchor="w")


def _detail(s: _Screen, deck: Deck, now: float) -> None:
    item = deck.selected_item()
    if item is None:
        return
    _chip(s, 40, 84, item.color, 30)
    s.text(86, 99, clip(item.short_id, 34, 820), COLORS["text"], 34, bold=True, anchor="w")
    s.text(SCREEN_W - 40, 99, KIND_LABELS[item.kind], COLORS["dim"], 22, anchor="e")
    meta = [f"home {item.home}"] + ([f"project {item.project}"] if item.project else []) + [f"age {age(item.age_s)}"]
    if item.checks:
        meta.append(f"checks {item.checks}")
    meta_w = SCREEN_W - 80
    tag = answer_tag(item)
    if tag:
        s.text(SCREEN_W - 40, 136, tag, COLORS[KEY_COLORS[item.pending]], 22, bold=True, anchor="ne")
        meta_w -= len(tag) * 22 * CHAR_W + 30
    s.text(40, 136, clip("   ".join(meta), 22, meta_w), COLORS["dim"], 22)
    body_size, line_h, top, bottom = 26, 38, 186, 620
    lines = wrap(item.detail, body_size, SCREEN_W - 80)
    visible = (bottom - top) // line_h
    deck.detail_scroll = min(deck.detail_scroll, max(0, len(lines) - visible))
    for n, line in enumerate(lines[deck.detail_scroll : deck.detail_scroll + visible]):
        s.text(40, top + n * line_h, line, COLORS["text"], body_size)
    if len(lines) > visible:
        track = bottom - top
        thumb = max(30, track * visible / len(lines))
        y = top + (track - thumb) * deck.detail_scroll / max(1, len(lines) - visible)
        s.rect(SCREEN_W - 20, top, SCREEN_W - 14, bottom, COLORS["panel"])
        s.rect(SCREEN_W - 20, y, SCREEN_W - 14, y + thumb, COLORS["dim"])
    footer = clip(item.pr_url, 20, SCREEN_W - 80) if item.pr_url else "turn: scroll   press: back"
    s.text(40, 680, footer, COLORS["faint"], 20, anchor="w")


def _confirm(s: _Screen, deck: Deck, now: float) -> None:
    hold = deck.hold
    if hold is None:
        return
    color = COLORS[KEY_COLORS[hold.key]]
    mid = SCREEN_W / 2
    s.text(mid, 110, "Hold to confirm", COLORS["dim"], 30, anchor="n")
    s.text(mid, 250, KEY_LABELS[hold.key], color, 110, bold=True, anchor="center")
    s.text(mid, 360, f"on {clip(hold.item.short_id, 40, 1000)}", COLORS["text"], 40, bold=True, anchor="center")
    s.text(mid, 410, KIND_LABELS[hold.item.kind], COLORS["dim"], 24, anchor="center")
    progress = deck.hold_progress(now)
    x0, x1, y0, y1 = 240, SCREEN_W - 240, 480, 536
    s.rect(x0, y0, x1, y1, COLORS["panel"], COLORS["faint"], 2)
    if progress > 0:
        s.rect(x0 + 4, y0 + 4, x0 + 4 + (x1 - x0 - 8) * progress, y1 - 4, color)
    s.text(mid, 600, "release to cancel", COLORS["faint"], 24, anchor="center")


def _result(s: _Screen, deck: Deck, now: float) -> None:
    p = deck.pending
    if p is None:
        return
    s.text(40, 90, f"{KEY_LABELS[p.key]} on {clip(p.item.short_id, 34, 820)}", COLORS["text"], 34, bold=True)
    result = p.result
    if result is None:
        waited = now - p.sent_at
        label, color = ("Sending", "dim") if waited < 10 else ("No answer yet", "amber")
        text = "Waiting for the bridge to confirm." if waited < 10 else "The bridge has not answered. Nothing is known to have happened."
    else:
        label, color = {"queued": ("Queued", "blue"), "replied": ("Replied", "green"), "failed": ("Failed", "red")}[result.state]
        if result.state == "queued" and result.seen:
            label = "Seen"
        elif result.state == "queued" and result.stalled:
            color = "amber"
        text = result.text
    s.rect(40, 160, 300, 220, COLORS[color])
    s.text(170, 190, label, COLORS["screen"], 30, bold=True, anchor="center")
    progress = result_progress(result) if result is not None else None
    if progress is not None:
        line, line_color = progress
        s.text(330, 190, clip(line, 26, SCREEN_W - 370), COLORS[line_color], 26, anchor="w")
    for n, line in enumerate(wrap(text, 28, SCREEN_W - 80)[:9]):
        s.text(40, 260 + n * 42, line, COLORS["text"], 28)
    s.text(40, 690, "turn or press: home", COLORS["faint"], 20, anchor="w")


def _knob(out: list[Shape], deck: Deck, view: View) -> None:
    cx, cy = KNOB_CENTER
    r = KNOB_R
    out.append(Oval(cx - r - 10, cy - r - 10, cx + r + 10, cy + r + 10, COLORS["bezel"]))
    out.append(Oval(cx - r, cy - r, cx + r, cy + r, "#3a3e46" if view.knob_down else "#4a4f58", "#6b717c", 2))
    # The pointer turns with the selection so a scroll is visible on the knob.
    angle = -math.pi / 2 + (deck.selected_index() or 0) * math.pi / 6 + deck.detail_scroll * math.pi / 12
    out.append(Line([cx + math.cos(angle) * r * 0.35, cy + math.sin(angle) * r * 0.35, cx + math.cos(angle) * r * 0.85, cy + math.sin(angle) * r * 0.85], COLORS["text"], 5))
    out.append(Text(cx - r - 22, cy - 24, "KNOB", COLORS["dim"], 18, bold=True, anchor="e"))
    out.append(Text(cx - r - 22, cy + 2, "press: open", COLORS["faint"], 15, anchor="e"))
    out.append(Text(cx - r - 22, cy + 24, "hold: mute", COLORS["faint"], 15, anchor="e"))


def _keys(out: list[Shape], deck: Deck, now: float, view: View) -> None:
    for key, (x0, y0, x1, y1) in KEY_RECTS.items():
        lit = deck.key_lit(key, now)
        pressed = key in view.keys_down
        color = COLORS[KEY_COLORS[key]]
        out.append(Rect(x0 - 6, y0 - 6, x1 + 6, y1 + 6, COLORS["bezel"]))
        inset = 4 if pressed else 0
        face = mix(color, 0.9 if pressed else 0.75) if lit else COLORS["off"]
        out.append(Rect(x0 + inset, y0 + inset, x1 - inset, y1 - inset, face, mix(color, 1.0) if lit else COLORS["faint"], 2))
        label_color = COLORS["screen"] if lit else COLORS["faint"]
        out.append(Text((x0 + x1) / 2, (y0 + y1) / 2 - 8, KEY_LABELS[key], label_color, 20 if key != "focus" else 18, bold=True, anchor="center"))
        hint = f"{KEY_SHORTCUTS[key]}  hold 1s" if key in HOLD_KEYS else f"{KEY_SHORTCUTS[key]}  tap"
        out.append(Text((x0 + x1) / 2, (y0 + y1) / 2 + 22, hint, label_color, 13, anchor="center"))


def hit_test(x: float, y: float) -> str | None:
    """Which control is at window point (x, y): a key name, "knob", or None."""
    for key, (x0, y0, x1, y1) in KEY_RECTS.items():
        if x0 <= x <= x1 and y0 <= y <= y1:
            return key
    cx, cy = KNOB_CENTER
    if (x - cx) ** 2 + (y - cy) ** 2 <= KNOB_R**2:
        return "knob"
    return None
