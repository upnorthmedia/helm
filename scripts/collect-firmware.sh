#!/usr/bin/env bash
# Gather the flashable binaries of an ESP-IDF build of firmware/idf into one
# directory, for CI artifacts and release assets:
#
#   scripts/collect-firmware.sh <build dir> <out dir>
#
# Writes helm-deck.bin (the whole flash image, written at 0x0), the parts
# idf.py flashes (bootloader, partition table, app) beside the flash_args that
# places them, VERSION (the app version ESP-IDF took from git describe),
# README.txt with the flash commands, and SHA256SUMS. Run it inside an ESP-IDF
# environment (after export.sh): it uses that environment's esptool.
set -euo pipefail

die() { echo "collect-firmware: $*" >&2; exit 2; }

[ $# -eq 2 ] || die "usage: scripts/collect-firmware.sh <build dir> <out dir>"
build="$(cd "$1" && pwd)" || die "no build directory: $1"
[ -f "$build/flash_args" ] || die "$build has no flash_args; build first"
mkdir -p "$2"
out="$(cd "$2" && pwd)"

version="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["project_version"])' \
  "$build/project_description.json")"
[ -n "$version" ] || die "the build names no project version"

# flash_args lists each part by its path under the build directory; keep those paths
# (and read a last line that has no newline).
while read -r offset part || [ -n "$offset" ]; do
  case "$offset" in 0x*) ;; *) continue ;; esac
  mkdir -p "$out/$(dirname "$part")"
  cp "$build/$part" "$out/$part"
done < "$build/flash_args"
cp "$build/flash_args" "$out/flash_args"
(cd "$build" && python3 -m esptool --chip esp32p4 merge_bin -o "$out/helm-deck.bin" @flash_args > /dev/null)
echo "$version" > "$out/VERSION"

cat > "$out/README.txt" <<EOF
Helm deck firmware $version (hello reports fw=helm-idf-$version)
for the Waveshare ESP32-P4-WIFI6-Touch-LCD-5, ESP32-P4 chip revision v3.1 or
newer (esptool.py --chip esp32p4 chip_id prints it). Older chips need their own
build: see firmware/idf/README.md.

Flash through the board's "USB TO UART" port, the whole image:

  esptool.py --chip esp32p4 -p PORT write_flash 0x0 helm-deck.bin

or the parts, from this directory:

  esptool.py --chip esp32p4 -p PORT write_flash @flash_args

SHA256SUMS holds each file's checksum.
EOF

if command -v sha256sum > /dev/null; then
  sum() { sha256sum "$@"; }
else
  sum() { shasum -a 256 "$@"; }
fi
files="$(cd "$out" && find . -type f ! -name SHA256SUMS | sed 's|^\./||' | LC_ALL=C sort)"
sums="$(cd "$out" && echo "$files" | while read -r f; do sum "$f"; done)"
echo "$sums" > "$out/SHA256SUMS"
echo "collected helm-idf-$version into $out"
