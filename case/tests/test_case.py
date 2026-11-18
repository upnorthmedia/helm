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

    def test_header_pins_must_be_trimmed(self):
        """Negative control: the NeoKeys' and the knob's extra-long header
        pins left as soldered (6.13 mm above the board, 7.73 mm below the
        plastic) hit the printed face, and the NeoKeys' hit the metal one, so
        the check would notice a step that skips the trim."""
        from unittest import mock

        from helm_case import assembly
        from helm_case import params as P

        as_soldered = (mock.patch.object(P, "PIN_TRIM_TOP", P.HEADER_PIN_SIDE - P.NEOKEY_PCB_THICKNESS), mock.patch.object(P, "PIN_TRIM_TAIL", P.HEADER_PIN_SIDE))
        with as_soldered[0], as_soldered[1]:
            printed = {(a, b) for a, b, _ in assembly.interference(assembly.printed_items())}
            metal = {(a, b) for a, b, _ in assembly.interference(assembly.metal_items())}
        keys = {f"keypins{i}" for i in range(4)}
        self.assertEqual(printed, {("print_cover", p) for p in keys | {"knobpins"}})
        self.assertEqual(metal, {("cover", p) for p in keys})

    def test_a_part_in_a_wire_path_is_caught(self):
        """Negative control: a 3 mm cube dropped on each harness bundle's
        path, on each branch's last stretch, in the power strip and in the
        spare-wire spaces collides with that item and nothing else of the
        wiring."""
        from helm_case import assembly
        from helm_case import params as P

        wiring = assembly.wiring_items(P.SHEET_T) + [it for it in assembly.metal_items() if it.kind == "space"]
        probes = {
            "harness_trunk": [P.TRUNK_PATH[0], P.TRUNK_PATH[1]] + [b[-1] for b in assembly._trunk_branches()],
            "harness_knob": [P.KNOB_PATH[0], P.KNOB_PATH[1]] + [b[-1] for b in assembly._knob_branches()],
            "power_strip": [(sum(P.STRIP_X) / 2, sum(P.STRIP_V) / 2, -P.SHEET_T - 1.0)],
            "ribbon_fold": [tuple(sum(r) / 2 for r in P.RIBBON_FOLD)],
        }
        names = {it.name for it in wiring}
        for target, points in probes.items():
            for x, v, w in points:
                cube = cq.Solid.makeBox(3, 3, 3, cq.Vector(*P.plate_to_case(x, v, w)) - cq.Vector(1.5, 1.5, 1.5))
                hits = assembly.interference(wiring + [assembly.Item("probe", cube, (0, 0, 0), "part")])
                self.assertEqual({a for a, b, _ in hits if b == "probe"} & names, {target}, (target, x, v, w))
        (x0, _), y, z = P.JACK_LOOP[0], *(sum(r) / 2 for r in P.JACK_LOOP[1:])
        cube = cq.Solid.makeBox(3, 3, 3, cq.Vector(x0 + 0.5, y, z - 1.5))  # beside the lead, which runs through the loop's room
        hits = assembly.interference(wiring + [assembly.Item("probe", cube, (0, 0, 0), "part")])
        self.assertEqual({a for a, b, _ in hits if b == "probe"}, {"jack_loop"})

    def test_a_cradle_leg_in_the_trunk_is_caught(self):
        """Negative control: the back right cradle leg moved 25 mm toward the
        middle stands in the harness trunk's path."""
        from unittest import mock

        from helm_case import assembly
        from helm_case import params as P

        legs = list(P.CRADLE_LEGS)
        legs[3] = (legs[3][0] - 25.0, legs[3][1])
        with mock.patch.object(P, "CRADLE_LEGS", tuple(legs)):
            hits = assembly.interference(assembly.printed_items())
        self.assertIn(("cradle", "harness_trunk"), {(a, b) for a, b, _ in hits})

    def test_breakout_receptacle_is_on_a_long_edge_facing_the_left_wall(self):
        """The 4090's receptacle is centred on one of its long edges, so with
        it facing the left wall the board runs front to back, and the
        ribbon's plug meets the middle of that edge."""
        from helm_case import assembly
        from helm_case.printed import PLATE_LOC

        items = {it.name: it for it in assembly.metal_items()}
        board = items["usb_breakout"].shape.moved(PLATE_LOC.inverse).BoundingBox()
        plug = items["ribbon_plug_breakout"].shape.moved(PLATE_LOC.inverse).BoundingBox()
        self.assertGreater(board.ylen, board.xlen)
        self.assertAlmostEqual(plug.xmax, board.xmin, places=6)
        self.assertAlmostEqual((plug.ymin + plug.ymax) / 2, (board.ymin + board.ymax) / 2, places=6)

    def test_the_harness_plug_fits_under_the_socket(self):
        """The homemade 2 x 10 plug's envelope below the socket: socket-side
        pin left showing in the worst case, plastic, trimmed tails and the
        wires' turn."""
        from helm_case import params as P

        self.assertAlmostEqual(P.HEADER_PLUGS, 2.63 + 2.54 + 3.0 + 3.0, places=6)

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

    def test_tabs_stop_the_module_sliding_sideways(self):
        """Negative control: the module moved 1 mm toward any edge (twice the
        tab gap) hits a locating tab, so the tabs reach the glass on all four
        sides."""
        from helm_case import assembly
        from helm_case import params as P
        from helm_case.printed import plate_box, to_case

        t = P.SHEET_T
        tabs = [it for it in assembly.cradle_items() if it.name.startswith("cradle_tab")]
        self.assertEqual(len(tabs), len(P.CRADLE_TABS))
        x0, v0 = P.MODULE_X, P.MODULE_V
        for dx, dv in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            module = to_case(plate_box(x0 + dx, x0 + dx + P.MODULE_SX, v0 + dv, v0 + dv + P.MODULE_SV, -t - P.MODULE_THICKNESS, -t))
            hits = assembly.interference([assembly.Item("module", module, (0, 0, 0), "part")] + tabs)
            self.assertTrue(hits, (dx, dv))

    def test_case_fits_a_220_mm_print_bed(self):
        from helm_case import params as P

        self.assertLessEqual(max(P.WIDTH, P.FACE_LENGTH, P.DEPTH), 220.0)
        self.assertTrue(math.isclose(P.BACK_HEIGHT - P.FRONT_HEIGHT, P.DEPTH * math.tan(P.SLOPE)))


@unittest.skipUnless(HAVE_CAD, "CadQuery is not installed (see case/README.md)")
class PrintedEnclosureTest(unittest.TestCase):
    def test_printed_build_has_no_overlaps(self):
        """The printed cover and base take the same printed and bought parts
        as the metal case."""
        from helm_case import assembly

        self.assertEqual(assembly.interference(assembly.printed_items()), [])

    def test_printed_parts_keep_the_metal_outside(self):
        from helm_case import printed, sheet
        from helm_case import params as P

        for metal, prints in ((sheet.cover_solid(), printed.printed_cover()), (sheet.base_solid(), printed.printed_base())):
            a, b = metal.BoundingBox(), prints.BoundingBox()
            for k in ("xmin", "xmax", "ymin", "ymax"):
                self.assertAlmostEqual(getattr(a, k), getattr(b, k), places=2, msg=k)
            self.assertLess(abs(a.zmax - b.zmax), 0.5)  # the printed cover's outside corners are rounder
        self.assertAlmostEqual(printed.printed_base().BoundingBox().zmin, P.SHEET_T - P.PRINT_FLOOR, places=3)

    def test_printed_cover_has_every_metal_hole(self):
        """Every face cut and the jack hole are open through the printed
        cover."""
        import cadquery as cq

        from helm_case import layout, printed, sheet
        from helm_case import params as P

        cover = printed.printed_cover()
        cutters = sheet.plate_cutters(layout.face_cuts(), -P.PRINT_WALL - 1, 1)
        cutters.append(cq.Solid.makeCylinder(P.BACK_JACK_HOLE / 2 - 0.01, 20, cq.Vector(P.BACK_JACK_X, P.DEPTH - 10, P.BACK_JACK_Z), cq.Vector(0, 1, 0)))
        for c in cutters:
            self.assertLess(cover.intersect(c).Volume(), 0.01)

    def test_screws_reach_their_inserts_through_the_printed_base(self):
        """An M3 x 6 screw up through each base hole meets nothing until its
        insert: the flange holes of the printed cover and the cradle's legs."""
        import cadquery as cq

        from helm_case import printed
        from helm_case import params as P

        z0 = P.SHEET_T - P.PRINT_FLOOR
        flange, legs = printed.base_screw_xy()
        parts = [printed.printed_base(), printed.printed_cover(), printed.cradle()]
        for x, y in flange + legs:
            screw = cq.Solid.makeCylinder(1.5, 6.0, cq.Vector(x, y, z0))
            for part in parts:
                self.assertLess(part.intersect(screw).Volume(), 0.01, (x, y))

    def test_every_printed_part_fits_the_bed(self):
        from build import stl_parts, to_print_bed
        from helm_case import params as P

        for name, shape in stl_parts().items():
            bb = to_print_bed(shape).BoundingBox()
            self.assertLessEqual(max(bb.xlen, bb.ylen), P.PRINT_BED, name)
            self.assertEqual(len(shape.Solids()), 1, name)

    def test_cradle_tab_prints_on_its_glass_side(self):
        from build import to_print_bed
        from helm_case import printed
        from helm_case import params as P

        bb = to_print_bed(printed.cradle_tab_for_print()).BoundingBox()
        self.assertAlmostEqual(bb.zlen, P.CRADLE_TAB_T, places=3)


if __name__ == "__main__":
    unittest.main()
