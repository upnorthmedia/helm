"""scripts/install-agent.sh and uninstall-agent.sh, against a temporary HOME.

launchctl is always a recording stub passed by absolute path through
LAUNCHCTL, so these tests never load anything into the real launchd.
"""

import os
import plistlib
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
INSTALL = REPO / "scripts" / "install-agent.sh"
UNINSTALL = REPO / "scripts" / "uninstall-agent.sh"
LABEL = "local.helm.bridge"

STUB = """#!/bin/sh
echo "$*" >> "$STUB_LOG"
if [ "$1" = print ]; then
  [ -f "$STUB_LOADED" ] || exit 113
  exit 0
fi
[ "$1" = bootstrap ] && touch "$STUB_LOADED"
[ "$1" = bootout ] && rm -f "$STUB_LOADED"
exit 0
"""


@unittest.skipIf(shutil.which("bash") is None, "needs bash")
class LaunchAgentScripts(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="helm-agent-"))
        self.addCleanup(shutil.rmtree, self.tmp)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.fm_home = self.tmp / "firstmate"
        (self.fm_home / "state").mkdir(parents=True)
        self.port = self.tmp / "ttys-fake"
        self.port.touch()
        self.stub = self.tmp / "launchctl"
        self.stub.write_text(STUB)
        self.stub.chmod(self.stub.stat().st_mode | stat.S_IXUSR)
        self.stub_log = self.tmp / "launchctl.log"
        self.plist = self.home / "Library" / "LaunchAgents" / f"{LABEL}.plist"
        self.log_dir = self.home / "Library" / "Logs" / "helm"

    def run_script(self, script, *args, check=True):
        env = dict(os.environ)
        env.update(
            HOME=str(self.home),
            LAUNCHCTL=str(self.stub),
            STUB_LOG=str(self.stub_log),
            STUB_LOADED=str(self.tmp / "loaded"),
        )
        proc = subprocess.run(
            ["bash", str(script), *args], env=env, capture_output=True, text=True, timeout=60
        )
        if check and proc.returncode != 0:
            self.fail(f"{script.name} {args} exited {proc.returncode}: {proc.stderr}")
        return proc

    def install(self, *extra, check=True):
        base = ["--port", str(self.port), "--home", str(self.fm_home), "--python", sys.executable]
        return self.run_script(INSTALL, *base, *extra, check=check)

    def launchctl_calls(self):
        return self.stub_log.read_text().splitlines() if self.stub_log.exists() else []

    def files_under_home(self):
        return sorted(str(p.relative_to(self.home)) for p in self.home.rglob("*"))

    def test_writes_a_dry_run_plist_and_nothing_else(self):
        self.install("--no-launchctl")
        with self.plist.open("rb") as f:
            agent = plistlib.load(f)
        self.assertEqual(agent["Label"], LABEL)
        self.assertEqual(
            agent["ProgramArguments"],
            [sys.executable, "-m", "helm.bridge", "--dry-run", "--port", str(self.port), "--home", str(self.fm_home)],
        )
        self.assertEqual(agent["WorkingDirectory"], str(REPO))
        self.assertTrue(agent["RunAtLoad"])
        self.assertEqual(agent["KeepAlive"], {"SuccessfulExit": False})
        self.assertEqual(agent["StandardErrorPath"], str(self.log_dir / "bridge.log"))
        self.assertIn("/usr/bin", agent["EnvironmentVariables"]["PATH"].split(":"))
        self.assertEqual(
            self.files_under_home(),
            ["Library", "Library/LaunchAgents", f"Library/LaunchAgents/{LABEL}.plist", "Library/Logs", "Library/Logs/helm"],
        )
        self.assertEqual(self.launchctl_calls(), [])

    def test_install_is_idempotent(self):
        self.install("--no-launchctl")
        first = self.plist.read_bytes()
        proc = self.install("--no-launchctl")
        self.assertIn("already up to date", proc.stdout)
        self.assertEqual(self.plist.read_bytes(), first)

    def test_live_only_with_the_flag_and_back_to_dry_run_without_it(self):
        proc = self.install("--live", "--no-launchctl")
        self.assertIn("LIVE", proc.stderr)
        with self.plist.open("rb") as f:
            self.assertIn("--live", plistlib.load(f)["ProgramArguments"])
        self.install("--no-launchctl")
        with self.plist.open("rb") as f:
            args = plistlib.load(f)["ProgramArguments"]
        self.assertIn("--dry-run", args)
        self.assertNotIn("--live", args)

    def test_values_are_xml_escaped(self):
        odd_port = self.tmp / "a&b <deck>"
        proc = self.run_script(
            INSTALL, "--port", str(odd_port), "--home", str(self.fm_home), "--python", sys.executable, "--no-launchctl"
        )
        self.assertIn("does not exist yet", proc.stderr)
        with self.plist.open("rb") as f:
            self.assertIn(str(odd_port), plistlib.load(f)["ProgramArguments"])

    def test_refuses_without_port_or_with_a_bad_home(self):
        proc = self.run_script(INSTALL, "--home", str(self.fm_home), "--no-launchctl", check=False)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("--port is required", proc.stderr)
        proc = self.run_script(
            INSTALL, "--port", str(self.port), "--home", str(self.tmp), "--python", sys.executable, "--no-launchctl",
            check=False,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("not a firstmate home", proc.stderr)
        self.assertFalse(self.plist.exists())

    def test_home_comes_from_fm_home_or_must_be_passed(self):
        args = ["--port", str(self.port), "--python", sys.executable, "--no-launchctl"]
        with mock.patch.dict(os.environ):
            os.environ.pop("FM_HOME", None)
            proc = self.run_script(INSTALL, *args, check=False)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("pass --home or set FM_HOME", proc.stderr)
            self.assertFalse(self.plist.exists())
            os.environ["FM_HOME"] = str(self.fm_home)
            self.run_script(INSTALL, *args)
        with self.plist.open("rb") as f:
            self.assertIn(str(self.fm_home), plistlib.load(f)["ProgramArguments"])

    def test_loads_once_and_reloads_only_on_change(self):
        domain = f"gui/{os.getuid()}"
        self.install()
        self.assertIn(f"bootstrap {domain} {self.plist}", self.launchctl_calls())
        self.stub_log.unlink()
        proc = self.install()
        self.assertIn("already loaded", proc.stdout)
        self.assertEqual(self.launchctl_calls(), [f"print {domain}/{LABEL}"])
        self.stub_log.unlink()
        self.install("--live")
        self.assertEqual(
            self.launchctl_calls(),
            [f"print {domain}/{LABEL}", f"bootout {domain}/{LABEL}", f"bootstrap {domain} {self.plist}"],
        )

    def test_uninstall_is_idempotent_and_keeps_logs_unless_asked(self):
        self.install()
        (self.log_dir / "bridge.log").write_text("hello\n")
        proc = self.run_script(UNINSTALL)
        self.assertIn("unloaded", proc.stdout)
        self.assertFalse(self.plist.exists())
        self.assertTrue((self.log_dir / "bridge.log").exists())
        proc = self.run_script(UNINSTALL)
        self.assertIn("is not loaded", proc.stdout)
        self.assertIn("no plist", proc.stdout)
        self.run_script(UNINSTALL, "--logs", "--no-launchctl")
        self.assertFalse(self.log_dir.exists())
        self.assertEqual(self.files_under_home(), ["Library", "Library/LaunchAgents", "Library/Logs"])


if __name__ == "__main__":
    unittest.main()
