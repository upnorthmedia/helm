"""Checks on the Helm case model.

Run from the repo root with the case environment (see case/README.md):

    case/.venv/bin/python -m unittest discover -s case/tests
"""

import math
import sys
import tempfile
import unittest
from pathlib import Path

CASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CASE))

try:
    import cadquery as cq  # noqa: F401

    HAVE_CAD = True
except ImportError:  # the case tools are optional for the rest of the repo
    HAVE_CAD = False


@unittest.skipUnless(HAVE_CAD, "CadQuery is not installed (see case/README.md)")
class SheetRulesTest(unittest.TestCase):
    def test_every_flat_part_passes_the_sendcutsend_rules(self):
        from build import flat_parts
        from helm_case import checks
        from helm_case.geom2d import write_dxf

        with tempfile.TemporaryDirectory() as tmp:
            for name, part in flat_parts().items():
                fails, _ = checks.check_flat(part)
                fn = Path(tmp) / f"{name}.dxf"
                write_dxf(part, fn)
                fails += checks.check_dxf(fn)
                self.assertEqual(fails, [], name)

    def test_bend_angles_and_flanges(self):
        from helm_case import checks

        fails, _ = checks.check_strips()
        self.assertEqual(fails, [])

    def test_the_checker_catches_a_hole_too_close_to_a_bend(self):
        from helm_case import checks, sheet
        from helm_case.geom2d import Circle

        part = sheet.cover_flat()
        centre = part.bend_lines[0][0][1]
        part.cuts.append(Circle(80.0, centre + 2.0, 1.0))
        fails, _ = checks.check_flat(part)
        self.assertTrue(any("from a bend" in f for f in fails), fails)

    def test_flat_patterns_match_the_bent_solids(self):
        """Flat area times thickness equals the bent volume within 1 percent
        (the K-factor puts the neutral axis off centre, so not exactly)."""
        from helm_case import params as P
        from helm_case import sheet

        for flat, solid in ((sheet.cover_flat(), sheet.cover_solid()), (sheet.base_flat(), sheet.base_solid())):
            expected = flat.shapely().area * P.SHEET_T
            self.assertLess(abs(solid.Volume() - expected) / expected, 0.01, flat.name)

    def test_key_holes_are_cherry_size_on_mx_pitch(self):
        """Standard MX plate holes on the standard 19.05 mm pitch: any cap with
        an MX cross stem fits, so aluminum caps are a cap swap."""
        from helm_case import layout
        from helm_case import params as P

        squares = sorted((c for c in layout.face_cuts() if hasattr(c, "verts") and len(c.verts) == 4), key=lambda c: c.verts[0][0])
        self.assertEqual(len(squares), 4)
        for sq in squares:
            xs = [v[0] for v in sq.verts]
            self.assertAlmostEqual(max(xs) - min(xs), P.KEY_HOLE, places=6)
        lefts = [min(v[0] for v in sq.verts) for sq in squares]
        for a, b in zip(lefts, lefts[1:]):
            self.assertAlmostEqual(b - a, 19.05, places=6)
        coupon = sorted(round(max(v[0] for v in c.verts) - min(v[0] for v in c.verts), 3) for c in layout.coupon().cuts if hasattr(c, "verts"))
        self.assertEqual(coupon, [13.95, 14.0, 14.05, 14.1])


@unittest.skipUnless(HAVE_CAD, "CadQuery is not installed (see case/README.md)")
class LogoTest(unittest.TestCase):
    def test_logo_has_room_on_the_face(self):
        from helm_case import checks

        fails, stats = checks.check_logo()
        self.assertEqual(fails, [])
        self.assertEqual(set(stats), {"logo to cut", "logo to side edge", "logo to bend"})

    def test_the_logo_check_catches_a_mark_near_the_window(self):
        """Negative control: the first-round position (2.25 mm from the
        window) fails."""
        from unittest import mock

        from helm_case import checks
        from helm_case import params as P

        with mock.patch.object(P, "LOGO_V", 118.25 + 2.25 + 4.5):
            fails, _ = checks.check_logo()
        self.assertTrue(any("cut clearance 2.25" in f for f in fails), fails)

    def test_logo_is_wheel_and_helm_at_its_drawn_size(self):
        from helm_case import logo

        w, h = logo.mark_size()
        self.assertAlmostEqual(w, 24.66, places=2)
        self.assertAlmostEqual(h, 9.00, places=2)
        self.assertGreater(logo.mark().area, 10)

    def test_engraving_files_place_the_mark_where_the_check_measured(self):
        import ezdxf

        from helm_case import logo

        with tempfile.TemporaryDirectory() as tmp:
            logo.write_engraving(tmp)
            names = sorted(p.name for p in Path(tmp).iterdir())
            self.assertEqual(names, ["README.md", "face_logo_placement.dxf", "face_logo_placement.svg", "logo-h1-wheel-helm.dxf", "logo-h1-wheel-helm.svg"])
            readme = (Path(tmp) / "README.md").read_text()
            doc = ezdxf.readfile(Path(tmp) / "face_logo_placement.dxf")
            pts = [p for e in doc.modelspace().query('LWPOLYLINE[layer=="ENGRAVE"]') for p in e.get_points("xy")]
        b = logo.placed().bounds
        x0 = logo.face_x()[0]
        self.assertAlmostEqual(min(p[0] for p in pts), b[0] - x0, places=3)
        self.assertAlmostEqual(min(p[1] for p in pts), b[1], places=3)
        pos = logo.placement()
        self.assertIn(f"| Screen window's back edge to the mark's bottom edge | **{pos['window_to_mark']:.2f}** |", readme)


@unittest.skipUnless(HAVE_CAD, "CadQuery is not installed (see case/README.md)")
class FitTest(unittest.TestCase):
    def test_metal_build_has_no_overlaps(self):
        from helm_case import assembly

        self.assertEqual(assembly.interference(assembly.metal_items()), [])

    def test_largest_aluminum_caps_fit_without_a_case_change(self):
        from helm_case import assembly
        from helm_case import params as P

        self.assertEqual(assembly.interference(assembly.metal_items(keycap=P.ALU_KEYCAP_MAX)), [])

    def test_cradle_is_one_printable_piece(self):
        """Its legs must reach into the sloped plate, or the print comes off
        the bed as a plate and four loose pegs."""
        from helm_case import printed

        self.assertEqual(len(printed.cradle().Solids()), 1)

    def test_cradle_leaves_room_for_the_header_plugs(self):
        """Negative control: a cradle running to the module's back edge (the
        design study's) hits the jumper plugs in the board's 40-pin header."""
        from unittest import mock

        from helm_case import assembly, printed
        from helm_case import params as P

        full = (P.MODULE_X + 4, P.MODULE_X + P.MODULE_SX - 4, P.MODULE_V + P.CRADLE_INSET, P.MODULE_V + P.MODULE_SV - 2)
        with mock.patch.object(printed, "cradle_plate_rect", lambda: full):
            hits = assembly.interference(assembly.metal_items())
        self.assertIn(("cradle", "header_plugs"), {(a, b) for a, b, _ in hits})

    def test_flashing_plug_needs_the_service_slot(self):
        """Negative control: without the slot, the flashing plug hits the left
        wall, so the interference check would notice a missing or misplaced
        slot."""
        from helm_case import assembly, sheet
        from helm_case import params as P

        u = sheet.base_strip().solid(sheet.XZ_PLANE, P.DEPTH)
        u = u.translate(cq.Vector(0, -u.BoundingBox().ymin, 0))
        wall = u.intersect(sheet.yz_prism(sheet.side_silhouette(0.0), -1, P.WIDTH + 1))
        plugs = [it for it in assembly.metal_items() if it.name == "flash_plug"]
        items = [assembly.Item("base_without_slot", wall, (0, 0, 0), "case")] + plugs
        hits = assembly.interference(items)
        self.assertEqual({b for _, b, _ in hits}, {"flash_plug"})

    def test_back_jack_needs_its_hole(self):
        """Negative control: without its hole, the panel jack hits the
        cover's back wall."""
        from helm_case import assembly, sheet

        cover = sheet.cover_strip().solid(sheet.YZ_PLANE, sheet.METAL_PIECE_WIDTH)
        jack = [it for it in assembly.metal_items() if it.name == "back_jack"]
        hits = assembly.interference([assembly.Item("cover_without_hole", cover, (0, 0, 0), "case")] + jack)
        self.assertEqual({b for _, b, _ in hits}, {"back_jack"})

    def test_everyday_usb_jack_is_low_on_the_back_wall(self):
        """The power and link cable plugs in near the desk, not at the top of
        the back wall: in the bottom third of it."""
        from helm_case import params as P

        self.assertLess(P.BACK_JACK_Z, P.BACK_HEIGHT / 3)

    def test_window_shows_the_whole_viewing_area_and_hides_the_border(self):
        from helm_case import params as P

        self.assertGreater(P.SCREEN_WINDOW_X, P.TOUCH_X)
        self.assertGreater(P.SCREEN_WINDOW_V, P.TOUCH_V)
        self.assertLess(P.SCREEN_WINDOW_X, P.MODULE_SX - 2 * 3.0)
        self.assertLess(P.SCREEN_WINDOW_V, P.MODULE_SV - 2 * 3.0)

    def test_case_fits_a_220_mm_print_bed(self):
        from helm_case import params as P

        self.assertLessEqual(max(P.WIDTH, P.FACE_LENGTH, P.DEPTH), 220.0)
        self.assertTrue(math.isclose(P.BACK_HEIGHT - P.FRONT_HEIGHT, P.DEPTH * math.tan(P.SLOPE)))


if __name__ == "__main__":
    unittest.main()
