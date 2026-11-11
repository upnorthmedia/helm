#!/usr/bin/env bash
# Build the device core (firmware/core) for this machine and run its tests:
# the C unit tests under AddressSanitizer and UBSan, then the Python
# cross-tests that compare the C code with helm/wire byte for byte.
#
#   scripts/test-firmware.sh
#
# Needs cmake, a C and C++ compiler, and Python 3.11+. Set PYTHON to pick the
# interpreter and HELM_SANITIZE=OFF to build without sanitizers.
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
py="${PYTHON:-python3}"
build="$repo/firmware/build"

cmake -S "$repo/firmware" -B "$build" -DHELM_SANITIZE="${HELM_SANITIZE:-ON}"
cmake --build "$build" --parallel
(cd "$build" && ctest --output-on-failure)
(cd "$repo" && "$py" -m unittest -v tests.test_firmware_core)
