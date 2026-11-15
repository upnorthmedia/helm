#!/usr/bin/env bash
# Draw every deck screen with the firmware's own code and compare it with the
# simulator's (sim/parity.py): fetch LVGL at the version the deck runs, build
# firmware/host, and run the comparison.
#
#   scripts/test-screens.sh [<out dir>]     # images go to build/screens by default
#   LVGL_DIR=<lvgl v9.5.0 tree> scripts/test-screens.sh   # use an LVGL tree already here
#
# Needs git, cmake, a C compiler, Python 3.11 or newer, and Pillow (CI pins
# its version; set PYTHON to pick an interpreter that has it). Exits 1 when a
# screen falls outside the tolerances sim/parity.py states, and leaves the
# firmware's image, the simulator's, and their differences for each screen in
# the out dir.
set -euo pipefail

# The LVGL the board package pins (firmware/idf/dependencies.lock: lvgl/lvgl 9.5.0,
# from this commit). Move both together.
LVGL_TAG=v9.5.0
LVGL_COMMIT=85aa60d18b3d5e5588d7b247abf90198f07c8a63
LVGL_REPO=https://github.com/lvgl/lvgl.git
PYTHON=${PYTHON:-python3}

die() { echo "test-screens: $*" >&2; exit 2; }

[ $# -le 1 ] || die "usage: scripts/test-screens.sh [<out dir>]"
root="$(cd "$(dirname "$0")/.." && pwd)"
out="${1:-$root/build/screens}"
build="$root/build/host"

if [ -z "${LVGL_DIR:-}" ]; then
  LVGL_DIR="$root/build/lvgl-$LVGL_TAG"
  if [ ! -f "$LVGL_DIR/lvgl.h" ]; then
    rm -rf "$LVGL_DIR"
    git clone -q --depth 1 --branch "$LVGL_TAG" "$LVGL_REPO" "$LVGL_DIR"
  fi
fi
got="$(git -C "$LVGL_DIR" rev-parse HEAD 2>/dev/null || true)"
[ -z "$got" ] || [ "$got" = "$LVGL_COMMIT" ] || die "$LVGL_DIR is at $got, not LVGL $LVGL_TAG ($LVGL_COMMIT)"

cmake -S "$root/firmware/host" -B "$build" -DLVGL_DIR="$LVGL_DIR" > /dev/null
cmake --build "$build" -j 4 > /dev/null
cd "$root"
"$PYTHON" -m sim.parity --harness "$build/helm_screens" --out "$out"
