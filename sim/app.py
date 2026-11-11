"""The simulator window: tkinter painting the shapes from sim/render.py.

tkinter because it ships with Python (stdlib first), a Canvas is all a
1280 x 720 screen of rectangles and text needs, and key press and release
events are enough to model hold-to-confirm. The deck's look is decided in
render.py, so this file only paints, routes input, and runs the link.
"""

from __future__ import annotations

import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from typing import Protocol

from helm import contract as c
from helm.wire import transport
from sim import render
from sim.fake_bridge import FakeBridge
from sim.state import CAPS, FIRMWARE, LINK_TIMEOUT_S, Deck

FRAME_MS = 33
LONG_PRESS_S = 0.6
WHEEL_STEP_S = 0.07  # a trackpad sends a burst of wheel events; one detent per this long
KEY_RELEASE_GRACE_MS = 40  # key autorepeat sends release/press pairs; ignore those
HELLO_EVERY_S = 2.0
CHIME_SOUND = "/System/Library/Sounds/Tink.aiff"

KEYMAP = {"y": "yes", "1": "yes", "l": "later", "2": "later", "h": "hold", "3": "hold", "s": "focus", "4": "focus"}
KNOB_TURN = {"Up": -1, "Left": -1, "Down": 1, "Right": 1}


class Source(Protocol):
    def poll(self, now: float) -> list[c.Model]: ...
    def send(self, events: list[c.Event], now: float) -> None: ...
    def close(self) -> None: ...


class FakeSource:
    """Fixture models from an in-process fake bridge (--fake)."""

    def __init__(self, now: float) -> None:
        self.bridge = FakeBridge(now)
        self._out: list[c.Model] = []

    def poll(self, now: float) -> list[c.Model]:
        model = self.bridge.step(now)
        out, self._out = self._out + ([model] if model else []), []
        return out

    def send(self, events: list[c.Event], now: float) -> None:
        for event in events:
            model = self.bridge.handle(event, now)
            if model is not None:
                self._out.append(model)

    def close(self) -> None:
        pass


class LinkSource:
    """The real wire. A thread owns the port so a slow write never stalls the window.

    It also drains the port continuously: a macOS pty holds about 1 KB, less
    than one model frame, so the bridge's writes need a reader waiting.
    """

    def __init__(self, link: transport.DeviceLink) -> None:
        self.link = link
        self._models: queue.Queue[c.Model] = queue.Queue()
        self._events: queue.Queue[c.Event] = queue.Queue()
        self._stop = threading.Event()
        self.models_received = 0
        self._thread = threading.Thread(target=self._run, name="helm-link", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        last_model = -LINK_TIMEOUT_S
        last_hello = -HELLO_EVERY_S
        last_seq: int | None = None
        while not self._stop.is_set():
            now = time.monotonic()
            # Say hello first, then until a bridge answers, and again whenever it goes quiet.
            if now - last_model > LINK_TIMEOUT_S and now - last_hello >= HELLO_EVERY_S:
                last_hello = now
                self._hello()
            for model in self.link.poll_models(0.02):
                now = time.monotonic()
                # A bridge that opened the port after our hello flushed it; one
                # whose seq went backwards has restarted. Either way it is a new
                # session and has not heard from us yet.
                if now - last_model > LINK_TIMEOUT_S or (last_seq is not None and model.seq < last_seq):
                    last_hello = now
                    self._hello()
                last_model, last_seq = now, model.seq
                self.models_received += 1
                self._models.put(model)
            while True:
                try:
                    self.link.send_event(self._events.get_nowait())
                except queue.Empty:
                    break

    def _hello(self) -> None:
        self.link.send_event(c.Hello(fw=FIRMWARE, caps=list(CAPS)))

    def poll(self, now: float) -> list[c.Model]:
        out = []
        while True:
            try:
                out.append(self._models.get_nowait())
            except queue.Empty:
                return out

    def send(self, events: list[c.Event], now: float) -> None:
        for event in events:
            self._events.put(event)

    def close(self) -> None:
        self._stop.set()
        self._thread.join(1)
        self.link.close()
        link = self.link
        print(
            f"helm sim link: models={self.models_received} seq_gaps={link.seq_gaps} "
            f"corrupt_frames={link.decoder.corrupt_frames} discarded_bytes={link.decoder.discarded_bytes} "
            f"bad_messages={link.bad_messages} dropped_writes={link.dropped_writes}",
            file=sys.stderr,
        )


def play_chime(root: tk.Misc) -> None:
    if shutil.which("afplay") and os.path.exists(CHIME_SOUND):
        subprocess.Popen(["afplay", CHIME_SOUND], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        root.bell()


class SimApp:
    def __init__(self, root: tk.Tk, source: Source, mode: str, *, chime=play_chime) -> None:
        self.root = root
        self.source = source
        self.deck = Deck()
        self.view = render.View(mode=mode)
        self.chime = chime
        self._fonts: dict[tuple[int, bool], tkfont.Font] = {}
        self._release_jobs: dict[str, str] = {}
        self._knob_job: str | None = None
        self._knob_long_fired = False
        self._last_wheel = 0.0
        self._closed = False

        root.title("Helm simulator")
        root.resizable(False, False)
        self.canvas = tk.Canvas(root, width=render.WINDOW_W, height=render.WINDOW_H, highlightthickness=0, bg=render.COLORS["body"])
        self.canvas.pack()
        root.bind("<KeyPress>", self._on_key_press)
        root.bind("<KeyRelease>", self._on_key_release)
        self.canvas.bind("<ButtonPress-1>", self._on_mouse_down)
        self.canvas.bind("<ButtonRelease-1>", self._on_mouse_up)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Button-4>", lambda e: self._wheel_step(-1))
        self.canvas.bind("<Button-5>", lambda e: self._wheel_step(1))
        root.protocol("WM_DELETE_WINDOW", self.close)
        self._frame()

    # Loop

    def _frame(self) -> None:
        if self._closed:
            return
        self.step(time.monotonic())
        self.root.after(FRAME_MS, self._frame)

    def step(self, now: float) -> None:
        for model in self.source.poll(now):
            self.deck.on_model(model, now)
        self.deck.tick(now)
        self._flush(now)
        while self.deck.chimes:
            self.deck.chimes -= 1
            self.chime(self.root)
        self.paint(now)

    def _flush(self, now: float) -> None:
        events = self.deck.take_outbox()
        if events:
            self.source.send(events, now)

    def paint(self, now: float) -> None:
        cv = self.canvas
        cv.delete("all")
        for sh in render.render(self.deck, now, self.view):
            if isinstance(sh, render.Rect):
                cv.create_rectangle(sh.x0, sh.y0, sh.x1, sh.y1, fill=sh.fill or "", outline=sh.outline or "", width=sh.width if sh.outline else 0)
            elif isinstance(sh, render.Oval):
                cv.create_oval(sh.x0, sh.y0, sh.x1, sh.y1, fill=sh.fill or "", outline=sh.outline or "", width=sh.width if sh.outline else 0)
            elif isinstance(sh, render.Text):
                cv.create_text(sh.x, sh.y, text=sh.text, fill=sh.fill, font=self._font(sh.size, sh.bold), anchor=sh.anchor)
            elif isinstance(sh, render.Line):
                cv.create_line(*sh.points, fill=sh.fill, width=sh.width, capstyle=tk.ROUND)

    def _font(self, size: int, bold: bool) -> tkfont.Font:
        key = (size, bold)
        if key not in self._fonts:
            # A negative size is in pixels, matching the PNG painter.
            self._fonts[key] = tkfont.Font(root=self.root, family=render.FONT, size=-size, weight="bold" if bold else "normal")
        return self._fonts[key]

    # Controls

    def key_down(self, key: str) -> None:
        if key in self.view.keys_down:
            return
        self.view.keys_down.add(key)
        self.deck.key_down(key, time.monotonic())
        self._flush(time.monotonic())

    def key_up(self, key: str) -> None:
        if key not in self.view.keys_down:
            return
        self.view.keys_down.discard(key)
        self.deck.key_up(key, time.monotonic())
        self._flush(time.monotonic())

    def knob(self, delta: int) -> None:
        self.deck.knob(delta, time.monotonic())
        self._flush(time.monotonic())

    def knob_press(self, long: bool) -> None:
        self.deck.knob_press(long, time.monotonic())
        self._flush(time.monotonic())

    def _on_key_press(self, event: tk.Event) -> None:
        sym = event.keysym
        name = KEYMAP.get(sym.lower())
        if name is not None:
            job = self._release_jobs.pop(name, None)
            if job is not None:
                self.root.after_cancel(job)  # autorepeat: the key never really went up
                return
            self.key_down(name)
        elif sym in KNOB_TURN:
            self.knob(KNOB_TURN[sym])
        elif sym in ("Return", "KP_Enter", "space"):
            self.knob_press(False)
        elif sym.lower() == "m":
            self.knob_press(True)

    def _on_key_release(self, event: tk.Event) -> None:
        name = KEYMAP.get(event.keysym.lower())
        if name is None or name in self._release_jobs:
            return

        def release() -> None:
            self._release_jobs.pop(name, None)
            self.key_up(name)

        self._release_jobs[name] = self.root.after(KEY_RELEASE_GRACE_MS, release)

    def _on_mouse_down(self, event: tk.Event) -> None:
        target = render.hit_test(event.x, event.y)
        if target == "knob":
            self.view.knob_down = True
            self._knob_long_fired = False

            def long_press() -> None:
                self._knob_job = None
                self._knob_long_fired = True
                self.knob_press(True)

            self._knob_job = self.root.after(int(LONG_PRESS_S * 1000), long_press)
        elif target is not None:
            self.key_down(target)

    def _on_mouse_up(self, event: tk.Event) -> None:
        if self.view.knob_down:
            self.view.knob_down = False
            if self._knob_job is not None:
                self.root.after_cancel(self._knob_job)
                self._knob_job = None
            if not self._knob_long_fired:
                self.knob_press(False)
        for key in list(self.view.keys_down):
            self.key_up(key)

    def _on_wheel(self, event: tk.Event) -> None:
        if event.delta:
            self._wheel_step(-1 if event.delta > 0 else 1)

    def _wheel_step(self, delta: int) -> None:
        now = time.monotonic()
        if now - self._last_wheel >= WHEEL_STEP_S:
            self._last_wheel = now
            self.knob(delta)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.source.close()
        self.root.destroy()
