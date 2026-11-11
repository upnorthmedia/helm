"""Regenerate every Helm case output into case/out/.

    python case/build.py            # everything
    python case/build.py --no-render

Writes the SendCutSend DXF and STEP files, the printable STL files, the
logo engraving files, the preview PNGs, and out/checks.txt (rule checks, logo
clearance, interference, bend tables). Exits non-zero if a rule check, the
logo clearance check or an interference check fails.
"""

import argparse
import math
import sys
from pathlib import Path

import cadquery as cq

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from helm_case import assembly, checks, layout, logo, printed, sheet  # noqa: E402
from helm_case import params as P  # noqa: E402
from helm_case.geom2d import write_dxf  # noqa: E402

OUT = HERE / "out"


def flat_parts():
    return {
        "cover_flat": sheet.cover_flat(),
        "base_flat": sheet.base_flat(),
        "mx_coupon": layout.coupon(),
    }


def to_print_bed(shape):
    """Drop a shape onto z = 0, centred on the origin."""
    bb = shape.BoundingBox()
    return shape.translate(cq.Vector(-(bb.xmin + bb.xmax) / 2, -(bb.ymin + bb.ymax) / 2, -bb.zmin))


def stl_parts():
    return {
        "print_cradle": printed.cradle_for_print(),
        "print_cradle_tab": printed.cradle_tab_for_print(),  # 5 needed
        "print_light_holder": printed.light_holder(),  # open side down, so the diffuser bridges
        "print_speaker_holder": printed.speaker_holder(),
        "print_mx_coupon": printed.coupon(layout.coupon()),
        "print_test_cover": printed.cover_for_print(),
        "print_test_base": printed.printed_base(),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-render", action="store_true")
    args = ap.parse_args()
    for d in ("dxf", "step", "stl", "png", "engrave"):
        (OUT / d).mkdir(parents=True, exist_ok=True)

    report, failed = [], False

    report.append("# SendCutSend rule checks (0.063 inch 5052)\n")
    for name, part in flat_parts().items():
        fn = OUT / "dxf" / f"{name}.dxf"
        write_dxf(part, fn)
        fails, stats = checks.check_flat(part)
        fails += checks.check_dxf(fn)
        b = part.outline.shapely().bounds
        report.append(f"{name}.dxf: {b[2] - b[0]:.2f} x {b[3] - b[1]:.2f} mm, {len(part.cuts)} inner cuts")
        for k, v in stats.items():
            report.append(f"    {k}: {v:.2f} mm" if v != math.inf else f"    {k}: n/a")
        for (p0, p1, angle, _) in part.bend_lines:
            axis = "y" if math.isclose(p0[1], p1[1]) else "x"
            at = p0[1] if axis == "y" else p0[0]
            report.append(f"    bend {angle:.0f} degrees, centreline at {axis} = {at:.2f} mm")
        for f in fails:
            report.append(f"    FAIL {f}")
        failed |= bool(fails)
    fails, stats = checks.check_strips()
    for k, v in stats.items():
        report.append(f"{k}: {v:.2f} mm (minimum {P.MIN_FLANGE:.2f})")
    for f in fails:
        report.append(f"FAIL {f}")
    failed |= bool(fails)

    cq.exporters.export(sheet.cover_solid(), str(OUT / "step" / "cover.step"))
    cq.exporters.export(sheet.base_solid(), str(OUT / "step" / "base.step"))

    report.append("\n# Logo engraving (wheel + helm, out/engrave/)\n")
    logo.write_engraving(OUT / "engrave")
    fails, stats = checks.check_logo()
    for k, v in stats.items():
        report.append(f"{k}: {v:.2f} mm (minimum {P.LOGO_CLEAR:.2f})")
    for k, v in logo.placement().items():
        report.append(f"    {k}: {v:.2f} mm")
    for f in fails:
        report.append(f"FAIL {f}")
    failed |= bool(fails)

    report.append("\n# Printable parts\n")
    for name, shape in stl_parts().items():
        shape = to_print_bed(shape)
        bb = shape.BoundingBox()
        cq.exporters.export(shape, str(OUT / "stl" / f"{name}.stl"), tolerance=0.05, angularTolerance=0.2)
        report.append(f"{name}.stl: {bb.xlen:.1f} x {bb.ylen:.1f} x {bb.zlen:.1f} mm")
        if max(bb.xlen, bb.ylen) > P.PRINT_BED:
            report.append(f"    FAIL {name} does not fit a {P.PRINT_BED:.0f} mm bed")
            failed = True

    report.append("\n# Interference (parts that overlap by more than 0.01 cubic mm)\n")
    items = assembly.metal_items()
    builds = {
        "metal": items,
        f"metal with {P.ALU_KEYCAP_MAX[0]:.1f} x {P.ALU_KEYCAP_MAX[1]:.1f} mm aluminum caps": assembly.metal_items(keycap=P.ALU_KEYCAP_MAX),
        "printed test enclosure": assembly.printed_items(),
    }
    for name, build in builds.items():
        hits = assembly.interference(build)
        report.append(f"{name}: {len(build)} items, {len(hits)} overlaps")
        for a, b, v in hits:
            report.append(f"    FAIL {a} and {b} overlap by {v:.2f} cubic mm")
        failed |= bool(hits)

    vol = P.WIDTH * P.DEPTH * (P.FRONT_HEIGHT + P.BACK_HEIGHT) / 2
    report.append(f"\nCase outside: {P.WIDTH:.1f} wide x {P.DEPTH:.1f} deep x {P.BACK_HEIGHT:.1f} tall at the back, {P.FRONT_HEIGHT:.1f} at the front, face sloped {P.SLOPE_DEG:.0f} degrees")
    report.append(f"Envelope: {vol / 1e6:.3f} litres, footprint {P.WIDTH * P.DEPTH / 100:.1f} cm2")
    (OUT / "checks.txt").write_text("\n".join(report) + "\n")
    print("\n".join(report))

    if not args.no_render:
        from helm_case.render import render

        no_flash = ("flash_plug",)  # the flashing cable is only plugged in to flash
        render(items, OUT / "png" / "helm_case_metal.png", azimuth=-38, elevation=26, zoom=1.35, skip=no_flash)
        render(items, OUT / "png" / "helm_case_back.png", azimuth=200, elevation=16, zoom=1.35, skip=no_flash)
        inside = no_flash + ("cover", "screen", "keycap", "legend", "switchtop", "knob", "logo")
        render(items, OUT / "png" / "helm_case_inside.png", azimuth=-20, elevation=55, zoom=1.45, skip=inside)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
