"""The parts of sim/parity.py that need neither Pillow nor the LVGL harness.

The comparison itself runs in CI's `screens` job (scripts/test-screens.sh).
"""

import unittest
from pathlib import Path

from helm.wire import codec
from sim import fixtures, parity, render, snapshot
from sim.state import Deck


def label(text, x0, y0, x1, y1):
    return {"text": text, "x0": x0, "y0": y0, "x1": x1, "y1": y1, "ix0": x0, "iy0": y0, "ix1": x1, "iy1": y1}


class SameText(unittest.TestCase):
    def test_equal_after_whitespace(self):
        self.assertTrue(parity.same_text("herdr   3 working", "herdr 3 working"))
        self.assertFalse(parity.same_text("YES", "LATER"))

    def test_cut_on_either_side(self):
        self.assertTrue(parity.same_text("firstmate pres...", "firstmate present"))
        self.assertTrue(parity.same_text("firstmate present", "firstmate pre..."))
        self.assertTrue(parity.same_text("a long ti...", "a long title th..."))
        self.assertFalse(parity.same_text("firstmate away...", "firstmate present"))

    def test_a_line_of_a_wrapped_paragraph(self):
        paragraph = "sample-org/gizmo PR 42: add retry with backoff to the gizmo uploader. Merge ask from the worker."
        self.assertTrue(parity.same_text("worker.", paragraph))
        self.assertTrue(parity.line_of("worker.", paragraph))
        self.assertFalse(parity.line_of(paragraph, paragraph))
        self.assertFalse(parity.same_text("not in it", paragraph))


class Placement(unittest.TestCase):
    def test_anchor_must_sit_in_the_label(self):
        lab = label("firstmate present", 52, 18, 952, 42)
        self.assertTrue(parity.placed(parity.TextBox("firstmate present", 52, 30, (0, 0, 0, 0)), lab))
        self.assertFalse(parity.placed(parity.TextBox("firstmate present", 52 - parity.POSITION_PAD - 2, 30,
                                                      (0, 0, 0, 0)), lab))
        self.assertFalse(parity.placed(parity.TextBox("firstmate present", 52, 80, (0, 0, 0, 0)), lab))

    def test_a_paragraph_line_may_run_lower(self):
        paragraph = label("one two three four five six", 40, 186, 1240, 253)
        third_line = parity.TextBox("six", 40, 262, (0, 0, 0, 0))
        self.assertTrue(parity.placed(third_line, paragraph))
        self.assertFalse(parity.placed(parity.TextBox("six", 40, 400, (0, 0, 0, 0)), paragraph))

    def test_problems_name_both_directions(self):
        sim = [parity.TextBox("Seen", 170, 190, (0, 0, 0, 0))]
        problems = parity.text_problems(sim, [label("Read", 45, 174, 295, 207), label("", 0, 0, 10, 10)])
        self.assertEqual(len(problems), 2)
        self.assertIn("'Seen'", problems[0])
        self.assertIn("'Read'", problems[1])
        self.assertEqual(parity.text_problems(sim, [label("Seen", 45, 174, 295, 207)]), [])


class SimulatorSide(unittest.TestCase):
    def test_text_boxes_follow_the_anchor(self):
        shapes = [
            render.Text(render.SCREEN_X + 100, render.SCREEN_Y + 50, "abcd", "#fff", 20, anchor="nw"),
            render.Text(render.SCREEN_X + 100, render.SCREEN_Y + 50, "abcd", "#fff", 20, anchor="e"),
            render.Text(render.SCREEN_X + 100, render.SCREEN_Y + 50, "   ", "#fff", 20),  # blank: nothing to match
            render.Text(10, 10, "KNOB", "#fff", 18),  # outside the screen
        ]
        nw, e = parity.sim_texts(shapes)
        w, h = 4 * 20 * render.CHAR_W, 20 * parity.LINE_HEIGHT
        self.assertEqual((nw.x, nw.y), (100, 50))
        self.assertEqual(nw.box, (100, 50, 100 + w, 50 + h))
        self.assertEqual(e.box, (100 - w, 50 - h / 2, 100, 50 + h / 2))


class Replay(unittest.TestCase):
    def test_every_snapshot_screen_records_its_steps(self):
        screens = snapshot.screens(parity.RecordingDeck)
        self.assertEqual(set(screens), set(snapshot.screens()))
        for name, (deck, now) in screens.items():
            with self.subTest(screen=name):
                self.assertEqual(deck.steps[0][0], "model")
                script = parity.harness_script(deck, now, Path("/out/a.ppm"), Path("/out/a.json"))
                self.assertTrue(script.endswith("render %d /out/a.ppm /out/a.json\n" % parity.ms(now)))

    def test_recording_does_not_change_the_deck(self):
        plain, recorded = Deck(), parity.RecordingDeck()
        for deck in (plain, recorded):
            deck.on_model(fixtures.busy(seq=2), 1000.0)
            deck.knob(1, 1000.0)
            deck.key_down("hold", 1000.0)
            deck.tick(1001.0)
        self.assertEqual((plain.screen, plain.selected_ref, plain.pending.key),
                         (recorded.screen, recorded.selected_ref, recorded.pending.key))
        self.assertEqual(recorded.steps[0], ("model", 1000.0, codec.encode_model(fixtures.busy(seq=2)).hex()))
        self.assertEqual([s[0] for s in recorded.steps], ["model", "knob", "key", "tick"])
        self.assertEqual(parity.harness_script(recorded, 1001.5, Path("i"), Path("l")).splitlines()[1:],
                         ["knob 1000000 1", "key 1000000 hold down", "tick 1001000", "render 1001500 i l"])


if __name__ == "__main__":
    unittest.main()
