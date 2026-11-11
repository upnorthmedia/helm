import threading
import time
import tkinter as tk
import unittest

from helm import contract as c
from helm.wire import transport
from sim import fixtures
from sim.app import FakeSource, LinkSource, SimApp
from sim.fake_bridge import ARRIVE_AFTER_S, REPLY_AFTER_S, FakeBridge
from sim.state import HOLD_S


def _tk_root():
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # no display
        raise unittest.SkipTest(f"no Tk display: {exc}")
    root.withdraw()  # drive the app without showing a window
    return root


class FakeBridgeOverPty(threading.Thread):
    """The fake bridge on the far side of a real pty, as run-sim.sh's fallback does."""

    def __init__(self, path: str, start_at: float):
        super().__init__(daemon=True)
        self.link = transport.open_transport(path)
        self.bridge = FakeBridge(start_at)
        self.events: list[c.Event] = []
        self.stop = threading.Event()

    def run(self):
        while not self.stop.is_set():
            model = self.bridge.step(time.monotonic())
            if model is not None:
                self.link.send_model(model)
            for event in self.link.poll_events(0.02):
                self.events.append(event)
                model = self.bridge.handle(event, time.monotonic())
                if model is not None:
                    self.link.send_model(model)
        self.link.close()


class SimOverWire(unittest.TestCase):
    def setUp(self):
        self.root = _tk_root()
        master, path = transport.open_pty()
        # Start the fixture batch at once instead of after the usual delay.
        self.far = FakeBridgeOverPty(path, time.monotonic() - ARRIVE_AFTER_S)
        self.far.start()
        self.chimes = 0
        self.app = SimApp(self.root, LinkSource(transport.DeviceLink(master)), "test", chime=self._chime)

    def tearDown(self):
        self.far.stop.set()
        self.far.join(2)
        self.app.close()

    def _chime(self, root):
        self.chimes += 1

    def _run_until(self, cond, timeout_s=3.0):
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            self.app.step(time.monotonic())
            if cond():
                return True
            time.sleep(0.02)
        return False

    def test_hello_models_and_a_held_yes_round_trip(self):
        deck = self.app.deck
        self.assertTrue(self._run_until(lambda: deck.model is not None and deck.items))
        self.assertTrue(any(isinstance(e, c.Hello) and e.product == "helm" for e in self.far.events))
        self.assertEqual(deck.attention(time.monotonic()), "new")
        self.assertEqual(self.chimes, 1)

        # Select the PR and hold YES for the full second.
        self.app.knob(1)
        self.app.knob(1)
        self.assertEqual(deck.selected_ref, fixtures.PR_READY.ref)
        self.app.key_down("yes")
        self.assertTrue(self._run_until(lambda: deck.screen == "result", HOLD_S + 1))
        self.app.key_up("yes")
        self.assertTrue(self._run_until(lambda: deck.pending and deck.pending.result and deck.pending.result.state == "replied", REPLY_AFTER_S + 2))

        sent = self.far.events
        self.assertIn(c.Seen(), sent)
        self.assertIn(c.Select(ref=fixtures.PR_READY.ref), sent)
        self.assertIn(c.Key(key="yes", phase="held"), sent)
        # The fake landed the PR: it left the list and the count went up.
        self.assertNotIn(fixtures.PR_READY.ref, [i.ref for i in deck.items])
        self.assertEqual(deck.model.counts.landed_today, 4)
        self.assertEqual(self.app.source.link.seq_gaps, 0)

    def test_paints_every_screen_without_error(self):
        deck = self.app.deck
        self.assertTrue(self._run_until(lambda: bool(deck.items)))
        for action in (lambda: self.app.knob(1), lambda: self.app.knob_press(False), lambda: self.app.knob(3)):
            action()
            self.app.step(time.monotonic())
        self.assertEqual(deck.screen, "detail")
        self.assertGreater(len(self.app.canvas.find_all()), 20)


class LateBridge(unittest.TestCase):
    """run-sim.sh starts the bridge after the simulator, and opening the port flushes the first hello."""

    def test_bridge_started_late_still_gets_hello(self):
        root = _tk_root()
        master, path = transport.open_pty()
        app = SimApp(root, LinkSource(transport.DeviceLink(master)), "test", chime=lambda r: None)
        far = None
        try:
            for _ in range(10):  # the startup hello goes out to nobody
                app.step(time.monotonic())
                time.sleep(0.02)
            far = FakeBridgeOverPty(path, time.monotonic() - ARRIVE_AFTER_S)
            far.start()
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and not any(isinstance(e, c.Hello) for e in far.events):
                app.step(time.monotonic())
                time.sleep(0.02)
            self.assertTrue(any(isinstance(e, c.Hello) for e in far.events))
        finally:
            if far is not None:
                far.stop.set()
                far.join(2)
            app.close()


class AutorepeatKeys(unittest.TestCase):
    """macOS key autorepeat must not cancel a hold."""

    def setUp(self):
        self.root = _tk_root()
        self.app = SimApp(self.root, FakeSource(time.monotonic() - ARRIVE_AFTER_S), "test", chime=lambda r: None)
        self.app.step(time.monotonic())

    def tearDown(self):
        self.app.close()

    def _event(self, keysym):
        ev = tk.Event()
        ev.keysym = keysym
        return ev

    def test_repeat_pairs_keep_the_hold(self):
        self.app._on_key_press(self._event("y"))
        self.assertEqual(self.app.deck.screen, "confirm")
        for _ in range(5):  # autorepeat: release then press within a few ms
            self.app._on_key_release(self._event("y"))
            self.app._on_key_press(self._event("y"))
        self.root.update()
        self.assertEqual(self.app.deck.screen, "confirm")
        self.app._on_key_release(self._event("y"))
        time.sleep(0.08)
        self.root.update()
        self.assertEqual(self.app.deck.screen, "home")


if __name__ == "__main__":
    unittest.main()
