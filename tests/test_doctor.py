"""python -m helm.bridge --doctor: one line per check, exit 1 only on a missing required piece, and never a write."""

import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helm.bridge import __main__ as cli
from helm.bridge import doctor
from helm.bridge.commands import LAVISH_LIST
from helm.bridge.intents import YES_PREFIX
from tests.helpers import FakeRunner

SETUP_GUIDE = Path(__file__).resolve().parent.parent / "docs" / "firstmate-setup.md"
NOW = 1794300000.0
EVERY_TOOL = {"herdr", "quota-axi", "lavish-axi"}


def guide_rule() -> str:
    """The pasteable rule block from docs/firstmate-setup.md, as a user would paste it."""
    text = SETUP_GUIDE.read_text(encoding="utf-8")
    section = text.split("### The rule", 1)[1]
    match = re.search(r"```markdown\n(.*?)```", section, re.S)
    assert match, "no ```markdown block under '### The rule' in docs/firstmate-setup.md"
    return match.group(1)


def summary(valid=True, schema=doctor.SUMMARY_SCHEMA, epoch=NOW - 90, reason=None) -> str:
    return json.dumps({"schema": schema, "valid": valid, "reason": reason, "generated_epoch": epoch,
                       "counts": {}, "active_children": [], "decisions_open": []})


def make_home(path: Path, ledger=True, pr_health=True, rule: str | None = None) -> Path:
    (path / "bin").mkdir(parents=True)
    inbox = path / "bin" / "fm-inbox.sh"
    inbox.write_text("#!/bin/sh\nexit 99\n")  # never run: the fake runner answers for it
    inbox.chmod(0o755)
    (path / "state").mkdir()
    (path / "data").mkdir()
    (path / "config").mkdir()
    (path / "state" / "home-summary.json").write_text(summary())
    if ledger:
        (path / "config" / "fleet-ledger").touch()
        (path / "state" / "fleet-ledger.jsonl").write_text('{"v":1,"ts":1,"event":"task.cleaned_up","task":"x"}\n')
    if pr_health:
        (path / "config" / "pr-health-monitor").touch()
    if rule is not None:
        (path / "data" / "captain.md").write_text("# Captain\n\n" + rule)
    return path


def tree_snapshot(root: Path) -> dict:
    """Every path under root with its type, mode, size, mtime, and content digest."""
    snap = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            p = Path(dirpath) / name
            st = p.lstat()
            digest = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
            snap[str(p.relative_to(root))] = (st.st_mode, st.st_size, st.st_mtime_ns, digest)
    return snap


class DoctorCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="helm-doctor-"))
        self.addCleanup(shutil.rmtree, self.tmp)
        self.home = make_home(self.tmp / "primary", rule=guide_rule())
        self.mate = make_home(self.tmp / "mate1")
        (self.home / "data" / "secondmates.md").write_text(
            "- mate1 - Own the gamma project. (home: %s; scope: gamma; projects: gamma; added 2026-11-09)\n" % self.mate)
        self.runner = FakeRunner(self.home)
        for agent in self.runner.agents:
            agent.setdefault("tokens", {})["context"] = "⛁ 49% (492k)"
        self.tools = set(EVERY_TOOL)

    def which(self, name):
        return "/fake/bin/%s" % name if name in self.tools else None

    def doctor(self):
        out = io.StringIO()
        code = doctor.main(self.home, self.runner, out=out, which=self.which, clock=lambda: NOW)
        return code, out.getvalue().splitlines()

    def line(self, lines, name):
        found = [ln for ln in lines if ln[8:].startswith(name + ":")]
        self.assertEqual(len(found), 1, "expected one %r line in:\n%s" % (name, "\n".join(lines)))
        return found[0]

    def assertStatus(self, lines, name, status):
        line = self.line(lines, name)
        self.assertEqual(line[:8].strip(), status, line)
        return line


class CompleteHome(DoctorCase):
    def test_every_check_is_ok_and_the_exit_is_zero(self):
        code, lines = self.doctor()
        self.assertEqual(code, 0)
        self.assertEqual(lines[0], "helm doctor, read only: %s" % self.home)
        body = lines[1:-1]
        names = [ln[8:].split(":", 1)[0] for ln in body]
        self.assertEqual(names, [
            "home", "ready", "YES rule",
            "summary primary", "fleet ledger primary", "pr health primary",
            "summary mate1", "fleet ledger mate1", "pr health mate1",
            "herdr", "context tokens", "quota-axi", "lavish-axi",
        ])
        for ln in body:
            self.assertTrue(ln.startswith("ok      "), ln)
            self.assertNotIn("Fix:", ln)
        self.assertEqual(lines[-1], "13 ok, 0 warn, 0 missing. Setup guide: docs/firstmate-setup.md")

    def test_details_name_what_was_read(self):
        _, lines = self.doctor()
        self.assertIn("can_receive true, posture present", self.line(lines, "ready"))
        self.assertIn("published 90s ago", self.line(lines, "summary primary"))
        self.assertIn("found in data/captain.md, with the commit pin", self.line(lines, "YES rule"))
        self.assertIn("3 of 3 agent(s) report tokens.context", self.line(lines, "context tokens"))
        self.assertIn("five hour 62% left, week 40% left", self.line(lines, "quota-axi"))

    def test_it_runs_only_reads_and_never_lavish(self):
        self.doctor()
        self.assertFalse(self.runner.allow_writes)
        self.assertEqual(len(self.runner.calls_for("fm-inbox.sh", "ready")), 1)
        self.assertEqual(len(self.runner.calls_for("herdr", "agent", "list")), 1)
        self.assertEqual(len(self.runner.calls_for("quota-axi", "--provider", "claude", "--json")), 1)
        self.assertEqual(self.runner.calls_for(*LAVISH_LIST), [])
        self.assertEqual(len(self.runner.calls), 3, self.runner.calls)
        self.assertEqual(self.runner.envs[0], {"FM_HOME": str(self.home)})

    def test_it_writes_nothing_in_any_home(self):
        before = tree_snapshot(self.tmp)
        self.doctor()
        self.assertEqual(tree_snapshot(self.tmp), before)

    def test_it_writes_nothing_when_everything_is_missing(self):
        bare = self.tmp / "bare"
        (bare / "state").mkdir(parents=True)
        (bare / "bin").mkdir()
        (bare / "bin" / "fm-inbox.sh").write_text("#!/bin/sh\n")
        (bare / "bin" / "fm-inbox.sh").chmod(0o755)
        self.home = bare
        self.runner.ready = None
        before = tree_snapshot(self.tmp)
        code, _ = self.doctor()
        self.assertEqual(code, 1)
        self.assertEqual(tree_snapshot(self.tmp), before)


class Home(DoctorCase):
    def test_a_path_that_is_not_a_directory_is_missing_and_skips_the_home_checks(self):
        self.home = self.tmp / "nowhere"
        code, lines = self.doctor()
        self.assertEqual(code, 1)
        line = self.assertStatus(lines, "home", "missing")
        self.assertIn("is not a directory", line)
        self.assertIn("Fix: pass --home", line)
        self.assertEqual(self.runner.calls_for("fm-inbox.sh", "ready"), [])
        self.assertFalse(any(ln[8:].startswith(("ready", "summary", "YES rule")) for ln in lines))
        self.assertStatus(lines, "herdr", "ok")  # the Mac's own tools are still checked

    def test_no_state_directory_is_missing(self):
        shutil.rmtree(self.home / "state")
        code, lines = self.doctor()
        self.assertEqual(code, 1)
        self.assertIn("has no state/", self.assertStatus(lines, "home", "missing"))

    def test_a_non_executable_inbox_is_missing(self):
        (self.home / "bin" / "fm-inbox.sh").chmod(0o644)
        code, lines = self.doctor()
        self.assertEqual(code, 1)
        self.assertIn("has no executable bin/fm-inbox.sh", self.assertStatus(lines, "home", "missing"))

    def test_no_data_or_config_yet_is_still_ok(self):
        shutil.rmtree(self.home / "data")
        shutil.rmtree(self.home / "config")
        code, lines = self.doctor()
        self.assertEqual(code, 0)
        self.assertIn("(no data/ or config/ yet)", self.assertStatus(lines, "home", "ok"))
        self.assertStatus(lines, "fleet ledger primary", "warn")
        self.assertStatus(lines, "YES rule", "warn")


class Ready(DoctorCase):
    def test_a_failing_ready_is_missing(self):
        self.runner.ready = None
        code, lines = self.doctor()
        self.assertEqual(code, 1)
        line = self.assertStatus(lines, "ready", "missing")
        self.assertIn("fm-inbox.sh ready failed: boom", line)
        self.assertIn("Fix: update firstmate", line)

    def test_another_schema_is_missing(self):
        self.runner.ready = dict(self.runner.ready, schema="fm-primary-ready.v9")
        code, lines = self.doctor()
        self.assertEqual(code, 1)
        self.assertIn("'fm-primary-ready.v9'", self.assertStatus(lines, "ready", "missing"))

    def test_cannot_receive_is_a_warning_with_the_lock_and_consumer(self):
        self.runner.ready = dict(self.runner.ready, can_receive=False, lock={"state": "free"},
                                 wake_consumer={"state": "absent"})
        code, lines = self.doctor()
        self.assertEqual(code, 0)
        line = self.assertStatus(lines, "ready", "warn")
        self.assertIn("can_receive false (lock free, wake consumer absent)", line)
        self.assertIn("Fix: start firstmate in this home", line)


class YesRule(DoctorCase):
    def test_the_guides_rule_carries_the_decks_exact_opening_words_and_the_pin(self):
        rule = guide_rule()
        self.assertIn('"%s"' % YES_PREFIX, rule)
        self.assertIn("--expected-head", rule)
        self.assertIn("bin/fm-pr-merge.sh", rule)
        self.assertIn("bin/fm-inbox.sh reply", rule)

    def test_no_rule_is_a_warning_that_points_at_the_guide(self):
        (self.home / "data" / "captain.md").write_text("# Captain\n\nNo deck rules here.\n")
        code, lines = self.doctor()
        self.assertEqual(code, 0)
        line = self.assertStatus(lines, "YES rule", "warn")
        self.assertIn("a held YES is a plain note", line)
        self.assertIn("docs/firstmate-setup.md", line)

    def test_no_captain_file_is_a_warning(self):
        (self.home / "data" / "captain.md").unlink()
        code, lines = self.doctor()
        self.assertEqual(code, 0)
        self.assertStatus(lines, "YES rule", "warn")

    def test_an_older_rule_without_the_commit_pin_is_a_warning(self):
        (self.home / "data" / "captain.md").write_text(
            "- A note that begins \"%s\" is my word: merge that PR through bin/fm-pr-merge.sh.\n" % YES_PREFIX)
        line = self.assertStatus(self.doctor()[1], "YES rule", "warn")
        self.assertIn("never mentions --expected-head", line)

    def test_the_opening_words_may_wrap_across_lines(self):
        wrapped = guide_rule().replace("from the Helm deck, held", "from the Helm\n  deck, held", 1)
        (self.home / "data" / "captain.md").write_text(wrapped)
        self.assertStatus(self.doctor()[1], "YES rule", "ok")

    def test_the_primarys_shared_captain_file_counts(self):
        (self.home / "data" / "captain.md").unlink()
        (self.home / "data" / "captain-shared.md").write_text(guide_rule())
        self.assertIn("found in data/captain-shared.md", self.assertStatus(self.doctor()[1], "YES rule", "ok"))


class Summary(DoctorCase):
    def test_no_primary_summary_is_missing(self):
        (self.home / "state" / "home-summary.json").unlink()
        code, lines = self.doctor()
        self.assertEqual(code, 1)
        line = self.assertStatus(lines, "summary primary", "missing")
        self.assertIn("state/home-summary.json not found", line)
        self.assertIn("bin/fm-home-summary-refresh.sh", line)

    def test_an_unreadable_primary_summary_is_missing(self):
        (self.home / "state" / "home-summary.json").write_text("{torn")
        code, lines = self.doctor()
        self.assertEqual(code, 1)
        self.assertIn("unreadable", self.assertStatus(lines, "summary primary", "missing"))

    def test_another_summary_schema_is_missing(self):
        (self.home / "state" / "home-summary.json").write_text(summary(schema="fm-secondmate-home-summary.v2"))
        self.assertEqual(self.doctor()[0], 1)

    def test_an_invalid_summary_is_a_warning_with_its_reason(self):
        (self.home / "state" / "home-summary.json").write_text(summary(valid=False, reason="live child has no backlog item"))
        code, lines = self.doctor()
        self.assertEqual(code, 0)
        self.assertIn("valid false: live child has no backlog item", self.assertStatus(lines, "summary primary", "warn"))

    def test_a_second_mates_missing_summary_is_only_a_warning(self):
        (self.mate / "state" / "home-summary.json").unlink()
        code, lines = self.doctor()
        self.assertEqual(code, 0)
        self.assertStatus(lines, "summary mate1", "warn")

    def test_a_listed_second_mate_home_that_does_not_exist_is_a_warning(self):
        shutil.rmtree(self.mate)
        code, lines = self.doctor()
        self.assertEqual(code, 0)
        self.assertIn("has no state/", self.assertStatus(lines, "summary mate1", "warn"))
        self.assertStatus(lines, "fleet ledger mate1", "warn")


class Flags(DoctorCase):
    def test_ledger_off_is_a_warning_per_home(self):
        (self.mate / "config" / "fleet-ledger").unlink()
        code, lines = self.doctor()
        self.assertEqual(code, 0)
        self.assertStatus(lines, "fleet ledger primary", "ok")
        line = self.assertStatus(lines, "fleet ledger mate1", "warn")
        self.assertIn("Fix: create config/fleet-ledger in that home", line)

    def test_a_large_ledger_suggests_truncating(self):
        with mock.patch.object(doctor, "LEDGER_LARGE_BYTES", 10):
            line = self.assertStatus(self.doctor()[1], "fleet ledger primary", "warn")
        self.assertIn(": > state/fleet-ledger.jsonl", line)

    def test_ledger_on_with_no_file_yet_is_ok(self):
        (self.home / "state" / "fleet-ledger.jsonl").unlink()
        self.assertIn("no state/fleet-ledger.jsonl yet", self.assertStatus(self.doctor()[1], "fleet ledger primary", "ok"))

    def test_pr_health_off_is_a_warning(self):
        (self.home / "config" / "pr-health-monitor").unlink()
        code, lines = self.doctor()
        self.assertEqual(code, 0)
        line = self.assertStatus(lines, "pr health primary", "warn")
        self.assertIn("YES is not dimmed", line)
        self.assertIn("Fix: create config/pr-health-monitor", line)


class MacTools(DoctorCase):
    def test_no_herdr_is_a_warning_not_a_failure(self):
        self.tools.discard("herdr")
        code, lines = self.doctor()
        self.assertEqual(code, 0)
        self.assertIn("not on PATH", self.assertStatus(lines, "herdr", "warn"))
        self.assertIn("not checked", self.assertStatus(lines, "context tokens", "warn"))
        self.assertEqual(self.runner.calls_for("herdr", "agent", "list"), [])

    def test_a_failing_herdr_is_a_warning(self):
        self.runner.agents = None
        code, lines = self.doctor()
        self.assertEqual(code, 0)
        self.assertIn("`herdr agent list` failed: no herdr", self.assertStatus(lines, "herdr", "warn"))

    def test_no_context_tokens_points_at_usagebar(self):
        for agent in self.runner.agents:
            agent["tokens"].pop("context", None)
        line = self.assertStatus(self.doctor()[1], "context tokens", "warn")
        self.assertIn("senna-lang/herdr-agent-usage", line)

    def test_no_agents_running_is_a_warning(self):
        self.runner.agents = []
        self.assertStatus(self.doctor()[1], "context tokens", "warn")

    def test_no_quota_axi_is_a_warning_and_not_run(self):
        self.tools.discard("quota-axi")
        code, lines = self.doctor()
        self.assertEqual(code, 0)
        self.assertStatus(lines, "quota-axi", "warn")
        self.assertEqual(self.runner.calls_for("quota-axi", "--provider", "claude", "--json"), [])

    def test_the_keychain_step_names_its_fix(self):
        self.runner.quota["providers"][0]["state"] = {"status": "auth_required", "reason": "keychain_prompt_required"}
        code, lines = self.doctor()
        self.assertEqual(code, 0)
        line = self.assertStatus(lines, "quota-axi", "warn")
        self.assertIn("claude quota auth_required (keychain_prompt_required)", line)
        self.assertIn("Fix: run `quota-axi --allow-keychain-prompt` once by hand", line)

    def test_a_failing_quota_axi_is_a_warning(self):
        self.runner.quota = None
        self.assertIn("quota-axi failed", self.assertStatus(self.doctor()[1], "quota-axi", "warn"))

    def test_no_lavish_axi_is_a_warning(self):
        self.tools.discard("lavish-axi")
        code, lines = self.doctor()
        self.assertEqual(code, 0)
        self.assertIn("no review board or report", self.assertStatus(lines, "lavish-axi", "warn"))

    def test_nothing_optional_installed_still_exits_zero(self):
        self.tools.clear()
        (self.home / "data" / "captain.md").unlink()
        for name in ("fleet-ledger", "pr-health-monitor"):
            (self.home / "config" / name).unlink()
            (self.mate / "config" / name).unlink()
        code, lines = self.doctor()
        self.assertEqual(code, 0)
        self.assertFalse([ln for ln in lines if ln.startswith("missing")])
        self.assertTrue(lines[-1].endswith("0 missing. Setup guide: docs/firstmate-setup.md"), lines[-1])


class CommandLine(unittest.TestCase):
    """--doctor through python -m helm.bridge, with the real read-only Runner and no tools on PATH."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="helm-doctor-cli-"))
        self.addCleanup(shutil.rmtree, self.tmp)

    def run_main(self, argv, env):
        # The caller's PATH stays, so herdr or quota-axi installed on this machine would run if `which` leaked.
        env = dict(env, PATH=os.environ.get("PATH", "/usr/bin:/bin"))
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(doctor.shutil, "which", return_value=None), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_a_home_with_no_state_is_reported_not_refused(self):
        code, out, _ = self.run_main(["--doctor"], env={"FM_HOME": str(self.tmp / "nowhere")})
        self.assertEqual(code, 1)
        self.assertIn("missing home: %s is not a directory" % (self.tmp / "nowhere"), out)
        self.assertTrue(out.rstrip().endswith("1 missing. Setup guide: docs/firstmate-setup.md"))

    def test_it_runs_the_real_inbox_ready_read_only(self):
        home = make_home(self.tmp / "home", rule=guide_rule())
        ready = json.dumps({"schema": "fm-primary-ready.v1", "posture": {"state": "present"}, "can_receive": True})
        (home / "bin" / "fm-inbox.sh").write_text(
            "#!/bin/sh\n[ \"$1\" = ready ] && [ -n \"$FM_HOME\" ] || exit 2\nprintf '%%s\\n' '%s'\n" % ready)
        before = tree_snapshot(self.tmp)
        code, out, _ = self.run_main(["--doctor", "--home", str(home)], env={})
        self.assertEqual(tree_snapshot(self.tmp), before)
        self.assertEqual(code, 0, out)
        self.assertIn("ok      ready: fm-primary-ready.v1, can_receive true, posture present", out)
        self.assertIn("warn    herdr: not on PATH", out)


if __name__ == "__main__":
    unittest.main()
