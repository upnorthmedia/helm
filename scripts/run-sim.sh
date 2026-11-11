#!/usr/bin/env bash
# Start the Helm deck simulator and the bridge, connected through a pty.
#
#   scripts/run-sim.sh [bridge args...]   simulator + python -m helm.bridge (dry run by default)
#   scripts/run-sim.sh --fake-bridge      simulator + the fixture bridge, over the real wire
#   scripts/run-sim.sh --fake             simulator alone with fixture models
#
# Extra arguments go to the bridge (for example --home PATH, or --live to send
# real notes). Without helm.bridge in this checkout it falls back to --fake.
# Closing the simulator window stops everything.
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo"
py="${PYTHON:-python3}"

if ! "$py" -c 'import tkinter' 2>/dev/null; then
  echo "run-sim: $py has no tkinter; set PYTHON to a Python 3.11+ with Tk" >&2
  exit 1
fi

# No --dry-run here: the bridge defaults to it, and --live must stay passable.
far=(-m helm.bridge)
case "${1:-}" in
  --fake)
    exec "$py" -m sim --fake
    ;;
  --fake-bridge)
    shift
    far=(-m sim.fake_bridge)
    ;;
  *)
    if ! "$py" -c 'import helm.bridge' 2>/dev/null; then
      echo "run-sim: helm.bridge is not in this checkout yet; running the simulator alone with --fake (fixture data)" >&2
      exec "$py" -m sim --fake
    fi
    ;;
esac

tmp="$(mktemp -d)"
port_file="$tmp/port"
sim_pid=""
far_pid=""
cleanup() {
  [ -n "$far_pid" ] && kill "$far_pid" 2>/dev/null || true
  [ -n "$sim_pid" ] && kill "$sim_pid" 2>/dev/null || true
  rm -rf "$tmp"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

"$py" -m sim --port-file "$port_file" &
sim_pid=$!

for _ in $(seq 100); do
  [ -s "$port_file" ] && break
  if ! kill -0 "$sim_pid" 2>/dev/null; then
    echo "run-sim: the simulator exited before opening its pty" >&2
    exit 1
  fi
  sleep 0.1
done
if [ ! -s "$port_file" ]; then
  echo "run-sim: the simulator did not report a pty within 10 s" >&2
  exit 1
fi
port="$(cat "$port_file")"

echo "run-sim: simulator on pty $port; starting: $py ${far[*]} --port $port $*" >&2
"$py" "${far[@]}" --port "$port" "$@" &
far_pid=$!

# The simulator window is the session: when it closes, stop the bridge. If the
# bridge dies first, the deck shows the link as unknown, which is the point.
wait "$sim_pid" || true
sim_pid=""
