import os
import stat
import tempfile
import textwrap
import unittest
from pathlib import Path

from helm.contract import Item
from helm.bridge.commands import Runner
from helm.bridge.intents import YES_PREFIX, IntentExecutor, note_text, request_id
from helm.bridge.items import Candidate
from tests.helpers import FakeRunner

NOW = 1_794_270_000.0


def merge_ask(home="primary"):
    item = Item("decision|%s|alpha-fix|merge-alpha-12" % home, "decision", "red", "alpha-fix/merge-alpha-12", 0, False,
                home, "Alpha PR checks green; merge?", ["yes", "later", "hold", "focus"],
                "https://github.com/example/alpha/pull/12", "green")
    return Candidate(item, "alpha-fix", "merge-alpha-12", None, "wA:p2")


def plain_decision():
    item = Item("decision|primary|widget-pricing|widget-pricing", "decision", "red", "widget-pricing", 0, False,
                "primary", "Pick A or B", ["yes", "later", "hold"], None, None)
    return Candidate(item, "widget-pricing", "widget-pricing", None, None)


class NoteTextTest(unittest.TestCase):
    def test_yes_text_starts_with_the_exact_prefix_and_covers_merge_and_single_recommendation(self):
        text = note_text("yes", merge_ask())
        self.assertTrue(text.startswith(YES_PREFIX + " on "))
        self.assertEqual(YES_PREFIX, "Captain, from the Helm deck, held to confirm: YES")
        self.assertIn("`alpha-fix` / `merge-alpha-12`", text)
        self.assertIn("merge `https://github.com/example/alpha/pull/12` under your normal checks", text)
        self.assertIn("single recommended option, only if you gave exactly one", text)
        self.assertIn("If neither applies, change nothing and reply.", text)

    def test_later_hold_and_second_mate_home(self):
        self.assertEqual(note_text("later", plain_decision()),
                         "Captain, from the Helm deck: defer `widget-pricing` / `widget-pricing` until tomorrow.")
        self.assertEqual(note_text("hold", plain_decision()),
                         "Captain, from the Helm deck: do not proceed on `widget-pricing` / `widget-pricing`. "
                         "Raise it with me in chat.")
        self.assertIn("(second mate home `mate1`)", note_text("yes", merge_ask("mate1")))

    def test_request_id_is_stable_per_day_and_valid(self):
        rid = request_id("yes", merge_ask(), NOW)
        self.assertEqual(rid, request_id("yes", merge_ask(), NOW + 60))
        self.assertNotEqual(rid, request_id("later", merge_ask(), NOW))
        self.assertRegex(rid, r"^helm-yes-primary-alpha-fix-merge-alpha-12-\d{8}$")
        self.assertLessEqual(len(rid), 128)


class ExecutorTest(unittest.TestCase):
    def setUp(self):
        self.home = Path("/fixture/primary")

    def test_dry_run_logs_the_exact_command_and_runs_nothing(self):
        runner = FakeRunner(self.home, allow_writes=False)
        ex = IntentExecutor(self.home, runner, dry_run=True, clock=lambda: NOW)
        with self.assertLogs("helm.bridge.intents", "INFO") as logs:
            result = ex.note("yes", merge_ask())
            self.assertTrue(ex.focus("wA:p2"))
        self.assertEqual(runner.calls, [])
        self.assertEqual(result.state, "queued")
        self.assertIn("dry run", result.text)
        self.assertIn("/fixture/primary/bin/fm-inbox.sh note --request-id helm-yes-primary-alpha-fix", ex.dry_log[0])
        self.assertIn("--json -- 'Captain, from the Helm deck, held to confirm: YES", ex.dry_log[0])
        self.assertEqual(ex.dry_log[1], "herdr agent focus wA:p2")
        self.assertTrue(any("FM_HOME=/fixture/primary" in line for line in logs.output))
        self.assertEqual(ex.check_receipts(), [])  # nothing pending in a dry run

    def test_live_note_then_reply_from_receipts(self):
        runner = FakeRunner(self.home, allow_writes=True)
        ex = IntentExecutor(self.home, runner, dry_run=False, clock=lambda: NOW)
        result = ex.note("later", plain_decision())
        self.assertEqual(result.state, "queued")
        [call] = runner.calls_for("fm-inbox.sh", "note")
        self.assertEqual(call[:2], ["/fixture/primary/bin/fm-inbox.sh", "note"])
        self.assertEqual(call[4:6], ["--json", "--"])
        self.assertEqual(runner.envs[0], {"FM_HOME": "/fixture/primary"})

        self.assertEqual(ex.check_receipts(), [])  # no reply yet
        runner.receipts["pending"] = [{"id": "note-1", "reply": {"body": "Deferred to tomorrow."}}]
        [reply] = ex.check_receipts()
        self.assertEqual((reply.request_id, reply.state, reply.text), (result.request_id, "replied", "Deferred to tomorrow."))
        self.assertEqual(ex.pending, {})

    def test_exit_3_repairs_the_wake_and_never_resends(self):
        runner = FakeRunner(self.home, allow_writes=True)
        runner.note_rc = 3
        ex = IntentExecutor(self.home, runner, dry_run=False, clock=lambda: NOW)
        result = ex.note("hold", plain_decision())
        self.assertEqual(result.state, "queued")
        self.assertEqual(len(runner.calls_for("fm-inbox.sh", "note")), 1)
        self.assertEqual(runner.calls_for("fm-inbox.sh", "announce"), [["/fixture/primary/bin/fm-inbox.sh", "announce", "--json", "note-1"]])

    def test_replay_is_reported_as_already_queued(self):
        runner = FakeRunner(self.home, allow_writes=True)
        runner.note_outcome = "replay"
        ex = IntentExecutor(self.home, runner, dry_run=False, clock=lambda: NOW)
        self.assertIn("already queued", ex.note("yes", merge_ask()).text)

    def test_note_failure_is_a_failed_result(self):
        runner = FakeRunner(self.home, allow_writes=True)
        runner.note_rc = 1
        ex = IntentExecutor(self.home, runner, dry_run=False, clock=lambda: NOW)
        with self.assertLogs("helm.bridge.intents", "WARNING") as logs:
            result = ex.note("yes", merge_ask())
        self.assertEqual(result.state, "failed")
        self.assertIn("note failed (1): wake failed", logs.output[0])
        self.assertEqual(runner.calls_for("fm-inbox.sh", "announce"), [])


class LiveSubprocessTest(unittest.TestCase):
    """The real Runner against a fake fm-inbox.sh in a throwaway home: proves argv, env, and exit 3 wiring."""

    def test_real_subprocess_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / "bin").mkdir()
            log = home / "calls.log"
            script = home / "bin" / "fm-inbox.sh"
            script.write_text(textwrap.dedent("""\
                #!/bin/sh
                printf '%%s|%%s\\n' "$FM_HOME" "$*" >> '%s'
                case "$1" in
                  note) printf '{"outcome":"created","id":"n-9","saved":true}\\n'; exit 3 ;;
                  announce) printf '{}\\n'; exit 0 ;;
                esac
                exit 2
                """ % log))
            script.chmod(script.stat().st_mode | stat.S_IXUSR)
            ex = IntentExecutor(home, Runner(allow_writes=True), dry_run=False, clock=lambda: NOW)
            result = ex.note("yes", merge_ask())
            self.assertEqual(result.state, "queued")
            self.assertIn("wake repaired", result.text)
            lines = log.read_text().splitlines()
            self.assertEqual(len(lines), 2)
            self.assertTrue(lines[0].startswith("%s|note --request-id helm-yes-primary-alpha-fix-merge-alpha-12-" % home))
            self.assertIn("--json -- %s on" % YES_PREFIX, lines[0])
            self.assertEqual(lines[1], "%s|announce --json n-9" % home)


if __name__ == "__main__":
    unittest.main()
