"""scripts/run-sim.sh hands its extra arguments to the bridge's real argument parser.

PYTHON points at a stub that stands in for the simulator and records each
bridge run. The stub hands the bridge's arguments to the real
`python -m helm.bridge` with --help appended, so argparse still rejects a bad
command line (exit 2) but a good one only prints help instead of starting a
bridge.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "run-sim.sh"

STUB = """#!/usr/bin/env bash
log="$(dirname "$0")/bridge.log"
case "$1" in
  -c) exit 0 ;;  # the tkinter and helm.bridge import probes
esac
if [ "$1 $2" = "-m sim" ]; then
  # Report a port, then stay up until the bridge run is recorded.
  echo /dev/null-sim-pty > "$4"
  for _ in $(seq 100); do [ -s "$log" ] && exit 0; sleep 0.1; done
  exit 1
fi
if [ "$1 $2" = "-m helm.bridge" ]; then
  shift 2
  "$REAL_PYTHON" -m helm.bridge "$@" --help > /dev/null 2> "$(dirname "$0")/bridge.err"
  echo "exit=$? args=$*" > "$log"
  exit 0
fi
exit 3
"""


@unittest.skipIf(shutil.which("bash") is None, "needs bash")
class RunSimBridgeArgs(unittest.TestCase):
    def run_sim(self, *args: str) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            stub = Path(tmp) / "python"
            stub.write_text(STUB)
            stub.chmod(0o755)
            env = dict(os.environ, PYTHON=str(stub), REAL_PYTHON=sys.executable)
            done = subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(done.returncode, 0, done.stderr)
            log = Path(tmp) / "bridge.log"
            self.assertTrue(log.exists(), "the bridge never started: " + done.stderr)
            return log.read_text().strip() + "\n" + (Path(tmp) / "bridge.err").read_text()

    def test_default_is_accepted(self):
        out = self.run_sim()
        self.assertTrue(out.startswith("exit=0 args=--port /dev/null-sim-pty"), out)
        self.assertNotIn("--dry-run", out.splitlines()[0])

    def test_live_reaches_the_bridge(self):
        out = self.run_sim("--live")
        self.assertTrue(out.startswith("exit=0 args=--port /dev/null-sim-pty --live"), out)


if __name__ == "__main__":
    unittest.main()
