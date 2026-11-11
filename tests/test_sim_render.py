import colorsys
import math
import unittest

from helm import contract as c
from sim import fixtures, render
from sim.state import Deck

T = 100.0


def bar(deck: Deck) -> list[str]:
    shapes = render.render(deck, T, render.View())
    return [sh.fill for sh in shapes if isinstance(sh, render.Oval) and sh.y0 == render.LIGHT_Y0]


class CalmBarIsTheUsageGauge(unittest.TestCase):
    def test_gauge_lights(self):
        self.assertEqual(render.gauge_lights(c.Usage(five_hour_left=62, week_left=40)), 4)
        self.assertEqual(render.gauge_lights(c.Usage(five_hour_left=100, week_left=100)), 8)
        self.assertEqual(render.gauge_lights(c.Usage(five_hour_left=1, week_left=90)), 1)
        self.assertEqual(render.gauge_lights(c.Usage(five_hour_left=0, week_left=90)), 0)
        self.assertIsNone(render.gauge_lights(c.Usage(five_hour_left=80)))  # one window unknown
        self.assertIsNone(render.gauge_lights(c.Usage()))

    def test_calm_bar_fills_and_unknown_never_looks_full(self):
        lit, track = render.mix(render.COLORS["white"], 0.12), render.mix(render.COLORS["white"], 0.03)
        deck = Deck()
        deck.on_model(fixtures.calm(), T)  # usage 62 % / 40 %
        self.assertEqual(bar(deck), [lit] * 4 + [track] * 4)
        deck.on_model(fixtures.model(2, [], usage=c.Usage()), T)
        self.assertEqual(bar(deck), [track] * 8)

    def test_context_hint_turns_the_last_calm_light_amber(self):
        lit, hint = render.mix(render.COLORS["white"], 0.12), render.mix(render.COLORS["amber"], render.CONTEXT_HINT)
        deck = Deck()
        deck.on_model(fixtures.model(1, [], usage=c.Usage(five_hour_left=100, week_left=100), context=fixtures.CONTEXT_NEAR), T)
        self.assertEqual(bar(deck), [lit] * 7 + [hint])
        deck.on_model(fixtures.model(2, [], usage=c.Usage(five_hour_left=100, week_left=100)), T)  # none near
        self.assertEqual(bar(deck), [lit] * 8)
        deck.on_model(fixtures.model(3, [], usage=c.Usage(five_hour_left=100, week_left=100), context=c.Context()), T)
        self.assertEqual(bar(deck), [lit] * 8)  # unknown shows no hint


class ContextLine(unittest.TestCase):
    def test_lines(self):
        self.assertEqual(render.context_line(c.Context()), "Agent context unknown")
        self.assertEqual(render.context_line(fixtures.CONTEXT), "Context  gizmo-retry 64% used")
        self.assertEqual(render.context_line(fixtures.CONTEXT_NEAR), "Context  widget-cache 91% used  2 near limit")


class ProjectTints(unittest.TestCase):
    def test_stable_hash_matches_the_firmware_vectors(self):
        # firmware/test/test_core.c checks the same values in C; tests/test_firmware_core.py checks random names.
        self.assertEqual([render.project_tint(p) for p in (None, "", "widget-api", "gizmo", "a")], [0, 0, 1, 3, 2])

    def test_a_tint_keeps_the_kind_hue_and_stays_colored(self):
        """The readability rule: a tint never changes which kind a light reads as."""
        def hsv(color):
            return colorsys.rgb_to_hsv(*(int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)))

        def hue_gap(a, b):
            d = abs(a - b) % 1.0
            return min(d, 1 - d) * 360

        kinds = {k: render.COLORS[k] for k in ("red", "amber", "blue", "green")}
        for kind, color in kinds.items():
            for tint in range(len(render.TINT_WHITE_PERMILLE)):
                h, s, _ = hsv(render.tinted(color, tint))
                with self.subTest(kind=kind, tint=tint):
                    self.assertLess(hue_gap(h, hsv(color)[0]), 2.0)  # integer rounding only
                    self.assertGreater(s, 0.25)  # still a color, not white
                    others = [hue_gap(h, hsv(c)[0]) for k, c in kinds.items() if k != kind]
                    self.assertLess(hue_gap(h, hsv(color)[0]) + 30, min(others))

    def test_unseen_lights_are_tinted_by_project(self):
        deck = Deck()
        deck.on_model(fixtures.projects(1), T)
        pulse = 0.55 + 0.45 * (0.5 + 0.5 * math.sin(T * 2 * math.pi / 1.4))
        self.assertEqual(bar(deck)[:2], [render.mix(render.tinted(render.COLORS["red"], 1), pulse),
                                         render.mix(render.tinted(render.COLORS["blue"], 3), pulse)])


class LandscapeLayout(unittest.TestCase):
    """The LCD-5 turned landscape: everything drawn on the screen stays on its 1280 x 720."""

    def test_every_screen_fits_the_panel(self):
        from sim import snapshot

        x0, y0 = render.SCREEN_X, render.SCREEN_Y
        x1, y1 = x0 + render.SCREEN_W, y0 + render.SCREEN_H
        for name, (deck, now) in snapshot.screens().items():
            on_screen = False
            for sh in render.render(deck, now, render.View()):
                if isinstance(sh, render.Text):
                    if not (x0 <= sh.x <= x1 and y0 <= sh.y <= y1):
                        continue  # the window's own labels
                    on_screen = True
                    w = len(sh.text) * sh.size * render.CHAR_W
                    left = {"w": sh.x, "nw": sh.x, "sw": sh.x, "e": sh.x - w, "ne": sh.x - w, "se": sh.x - w}.get(sh.anchor, sh.x - w / 2)
                    with self.subTest(screen=name, text=sh.text):
                        self.assertGreaterEqual(left, x0)
                        self.assertLessEqual(left + w, x1 + 1)
                elif isinstance(sh, (render.Rect, render.Oval)) and x0 <= sh.x0 < x1 and y0 <= sh.y0 < y1:
                    with self.subTest(screen=name, shape=sh):
                        self.assertLessEqual(sh.x1, x1)
                        self.assertLessEqual(sh.y1, y1)
            self.assertTrue(on_screen, name)

    def test_hit_test_finds_the_keys_and_knob_below_the_screen(self):
        for key, (kx0, ky0, kx1, ky1) in render.KEY_RECTS.items():
            self.assertGreater(ky0, render.SCREEN_Y + render.SCREEN_H)
            self.assertEqual(render.hit_test((kx0 + kx1) / 2, (ky0 + ky1) / 2), key)
        self.assertEqual(render.hit_test(*render.KNOB_CENTER), "knob")
        self.assertIsNone(render.hit_test(render.SCREEN_X + 10, render.SCREEN_Y + 10))


if __name__ == "__main__":
    unittest.main()
