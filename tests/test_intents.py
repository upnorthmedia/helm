import datetime
import json
import os
import stat
import subprocess
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock

from helm.contract import Item
from helm.bridge.commands import Runner
from helm.bridge.intents import ADOPT_MAX_AGE_S, YES_PREFIX, IntentExecutor, note_text, request_id
from helm.bridge.items import Candidate
from tests.helpers import FakeRunner

NOW = 1_794_270_000.0
HEAD = "fe05bcdcdc4928012781a5f1a2a77cbb5398e106"
NEW_HEAD = "ad782ecdac770fc6eb9a62e44f90873fb97fb26b"
# A firstmate checkout to run the executor against the real fm-inbox.sh. Unset: that test is skipped.
FIRSTMATE_ENV = "HELM_FIRSTMATE_CHECKOUT"


def merge_ask(home="primary", head=None):
    item = Item("decision|%s|alpha-fix|merge-alpha-12" % home, "decision", "red", "alpha-fix/merge-alpha-12", 0, False,
                home, "Alpha PR checks green; merge?", ["yes", "later", "hold", "focus"],
                "https://github.com/example/alpha/pull/12", "green")
    return Candidate(item, "alpha-fix", "merge-alpha-12", None, "wA:p2", head=head)


def pr_ready(head=HEAD):
    item = Item("pr|primary|https://github.com/example/delta/pull/3", "pr_ready", "blue", "delta#3", 0, False,
                "primary", "delta-docs: checks green https://github.com/example/delta/pull/3", ["yes", "later", "hold"],
                "https://github.com/example/delta/pull/3", "green")
    return Candidate(item, "delta-docs", "pr-3", None, None, head=head)


def plain_decision(home_path=None, detail="Pick A or B"):
    item = Item("decision|primary|widget-pricing|widget-pricing", "decision", "red", "widget-pricing", 0, False,
                "primary", detail, ["yes", "later", "hold"], None, None)
    return Candidate(item, "widget-pricing", "widget-pricing", home_path, None)


def local_epoch(*ymd_hms):
    return time.mktime(datetime.datetime(*ymd_hms).timetuple())


def tomorrow(now):
    return (datetime.date.fromtimestamp(now) + datetime.timedelta(days=1)).isoformat()


def utc_stamp(epoch):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


class NoteTextTest(unittest.TestCase):
    def test_yes_text_starts_with_the_exact_prefix_and_covers_merge_and_single_recommendation(self):
        text = note_text("yes", merge_ask(), NOW)
        self.assertTrue(text.startswith(YES_PREFIX + " on "))
        self.assertEqual(YES_PREFIX, "Captain, from the Helm deck, held to confirm: YES")
        self.assertIn("`alpha-fix` / `merge-alpha-12`", text)
        self.assertIn("merge `https://github.com/example/alpha/pull/12` under your normal checks", text)
        self.assertIn("single recommended option, only if you gave exactly one", text)
        self.assertIn("If neither applies, change nothing and reply.", text)

    def test_yes_on_a_pr_names_the_commit_the_deck_showed(self):
        for cand in (pr_ready(), merge_ask(head=HEAD)):
            text = note_text("yes", cand, NOW)
            self.assertTrue(text.startswith(YES_PREFIX + " on "))
            self.assertIn("merge `%s` at commit `%s` under your normal checks" % (cand.item.pr_url, HEAD), text)

    def test_yes_pins_only_a_full_commit_sha(self):
        for head in (None, "a12", HEAD[:12], HEAD.upper(), HEAD + "0", "g" * 40):
            text = note_text("yes", pr_ready(head), NOW)
            self.assertNotIn("at commit", text, head)
            self.assertIn("merge `https://github.com/example/delta/pull/3` under your normal checks", text)

    def test_later_names_the_next_local_date(self):
        self.assertEqual(note_text("later", plain_decision(), NOW),
                         "Captain, from the Helm deck: defer `widget-pricing` / `widget-pricing` until %s." % tomorrow(NOW))
        self.assertTrue(note_text("later", plain_decision(), local_epoch(2026, 11, 11, 23, 59, 30)).endswith(
            "until 2026-11-12."))
        self.assertTrue(note_text("later", plain_decision(), local_epoch(2026, 12, 31, 0, 0, 5)).endswith(
            "until 2027-01-01."))
        self.assertNotIn("tomorrow", note_text("later", pr_ready(), NOW))

    def test_hold_and_second_mate_home(self):
        self.assertEqual(note_text("hold", plain_decision(), NOW),
                         "Captain, from the Helm deck: do not proceed on `widget-pricing` / `widget-pricing`. "
                         "Raise it with me in chat.")
        self.assertIn("(second mate home `mate1`)", note_text("yes", merge_ask("mate1"), NOW))


class RequestIdTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        (self.home / "state").mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def status(self, *lines):
        (self.home / "state" / "widget-pricing.status").write_text("".join(line + "\n" for line in lines))

    def test_request_id_is_stable_per_day_and_valid(self):
        rid = request_id("yes", merge_ask(), NOW)
        self.assertEqual(rid, request_id("yes", merge_ask(), NOW + 60))
        self.assertNotEqual(rid, request_id("later", merge_ask(), NOW))
        self.assertNotEqual(rid, request_id("yes", merge_ask(), NOW + 86400))
        self.assertRegex(rid, r"^helm-yes-primary-alpha-fix-merge-alpha-12-[A-Za-z0-9]+-\d{8}$")
        self.assertLessEqual(len(rid), 128)

    def test_a_new_commit_on_the_same_pr_is_a_new_ask(self):
        rid = request_id("yes", pr_ready(HEAD), NOW)
        self.assertEqual(rid, request_id("yes", pr_ready(HEAD), NOW + 60))
        self.assertNotEqual(rid, request_id("yes", pr_ready(NEW_HEAD), NOW + 60))
        self.assertRegex(rid, r"^helm-yes-primary-delta-docs-pr-3-%s-\d{8}$" % HEAD[:12])
        self.assertNotEqual(request_id("yes", merge_ask(head=HEAD), NOW), request_id("yes", merge_ask(head=NEW_HEAD), NOW))

    def test_a_decision_is_keyed_to_when_it_opened(self):
        self.status("needs-decision [at=1794200000] [key=widget-pricing]: pick A or B",
                    "working [at=1794200100]: other work",
                    "needs-decision [at=1794260000] [key=widget-pricing]: reminder, still pick A or B")
        rid = request_id("yes", plain_decision(self.home), NOW)
        self.assertRegex(rid, r"^helm-yes-primary-widget-pricing-widget-pricing-o1794200000-\d{8}$")

    def test_a_decision_reopened_the_same_day_is_a_new_ask(self):
        self.status("needs-decision [at=1794200000] [key=widget-pricing]: pick A or B")
        first = request_id("yes", plain_decision(self.home), NOW)
        self.status("needs-decision [at=1794200000] [key=widget-pricing]: pick A or B",
                    "resolved [at=1794230000] [key=widget-pricing]: went with A",
                    "needs-decision [at=1794265000] [key=widget-pricing]: A broke, pick again")
        second = request_id("yes", plain_decision(self.home), NOW)
        self.assertNotEqual(first, second)
        self.assertIn("-o1794265000-", second)

    def test_a_decision_without_a_status_record_is_keyed_to_its_text(self):
        rid = request_id("yes", plain_decision(self.home), NOW)
        self.assertEqual(rid, request_id("yes", plain_decision(self.home), NOW + 60))
        self.assertNotEqual(rid, request_id("yes", plain_decision(self.home, "Pick C or D"), NOW + 60))
        self.assertRegex(rid, r"^helm-yes-primary-widget-pricing-widget-pricing-q[0-9a-f]{8}-\d{8}$")

    def test_long_names_keep_the_instance_and_day(self):
        item = Item("pr|primary|x", "pr_ready", "blue", "x", 0, False, "primary", "", ["yes"],
                    "https://github.com/example/x/pull/1", "green")
        rid = request_id("yes", Candidate(item, "t" * 120, "k" * 60, None, None, head=HEAD), NOW)
        self.assertEqual(len(rid), 128)
        self.assertRegex(rid, r"-%s-\d{8}$" % HEAD[:12])

    def test_shortened_ids_keep_items_that_differ_only_in_key_apart(self):
        def decision(key):
            item = Item("decision|primary|t|%s" % key, "decision", "red", "t", 0, False, "primary", "Same question?",
                        ["yes"], None, None)
            return Candidate(item, "t" * 120, key, None, None)

        one, two = request_id("yes", decision("key-one"), NOW), request_id("yes", decision("key-two"), NOW)
        self.assertNotEqual(one, two)
        self.assertEqual((len(one), len(two)), (128, 128))
        self.assertRegex(one, r"^helm-yes-primary-ttt+-h[0-9a-f]{8}-q[0-9a-f]{8}-\d{8}$")
        self.assertNotRegex(request_id("yes", plain_decision(), NOW), r"-h[0-9a-f]{8}-")  # short ids keep no digest


class ExecutorTest(unittest.TestCase):
    def setUp(self):
        self.home = Path("/fixture/primary")
        self._tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self._tmp.name) / "cache"

    def tearDown(self):
        self._tmp.cleanup()

    def executor(self, runner, dry_run=False, clock=lambda: NOW):
        return IntentExecutor(self.home, runner, dry_run=dry_run, clock=clock, cache_dir=self.cache)

    def test_dry_run_logs_the_exact_command_and_runs_nothing(self):
        runner = FakeRunner(self.home, allow_writes=False)
        ex = self.executor(runner, dry_run=True)
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
        self.assertEqual(ex.adopt(), [])  # a dry run sent nothing, so it takes nothing back
        self.assertEqual(runner.calls, [])
        self.assertFalse(self.cache.exists())

    def test_live_note_then_reply_from_receipts(self):
        runner = FakeRunner(self.home, allow_writes=True)
        ex = self.executor(runner)
        result = ex.note("later", plain_decision())
        self.assertEqual(result.state, "queued")
        [call] = runner.calls_for("fm-inbox.sh", "note")
        self.assertEqual(call[:2], ["/fixture/primary/bin/fm-inbox.sh", "note"])
        self.assertEqual(call[4:6], ["--json", "--"])
        self.assertTrue(call[6].endswith("until %s." % tomorrow(NOW)))
        self.assertEqual(runner.envs[0], {"FM_HOME": "/fixture/primary"})

        self.assertEqual(ex.check_receipts(), [])  # no reply yet
        runner.receipts["pending"] = [{"id": "note-1", "reply": {"body": "Deferred to tomorrow."}}]
        [reply] = ex.check_receipts()
        self.assertEqual((reply.request_id, reply.state, reply.text), (result.request_id, "replied", "Deferred to tomorrow."))
        self.assertEqual(ex.pending, {})

    def test_reply_is_found_in_the_replies_list_and_the_cursor_is_kept(self):
        runner = FakeRunner(self.home, allow_writes=True)
        ex = self.executor(runner)
        result = ex.note("hold", plain_decision())
        runner.receipts.update(replies=[{"id": "other", "body": "not ours", "cursor": "000000000004"},
                                        {"id": "note-1", "body": "Holding.", "cursor": "000000000005"}],
                               reply_cursor="000000000005")
        [reply] = ex.check_receipts()
        self.assertEqual((reply.request_id, reply.text), (result.request_id, "Holding."))
        self.assertEqual(runner.calls_for("fm-inbox.sh", "receipts")[-1], ["/fixture/primary/bin/fm-inbox.sh", "receipts"])
        saved = json.loads((self.cache / "inbox-reply-cursor.json").read_text())
        self.assertEqual(saved, {"home": "/fixture/primary", "cursor": "000000000005"})

        ex.note("yes", merge_ask())
        runner.receipts.update(replies=[], reply_cursor="000000000005")
        self.assertEqual(ex.check_receipts(), [])
        self.assertEqual(runner.calls_for("fm-inbox.sh", "receipts")[-1],
                         ["/fixture/primary/bin/fm-inbox.sh", "receipts", "--after", "000000000005"])

    def test_exit_3_repairs_the_wake_and_never_resends(self):
        runner = FakeRunner(self.home, allow_writes=True)
        runner.note_rc = 3
        ex = self.executor(runner)
        result = ex.note("hold", plain_decision())
        self.assertEqual(result.state, "queued")
        self.assertEqual(len(runner.calls_for("fm-inbox.sh", "note")), 1)
        self.assertEqual(runner.calls_for("fm-inbox.sh", "announce"), [["/fixture/primary/bin/fm-inbox.sh", "announce", "--json", "note-1"]])

    def test_replay_is_reported_as_already_queued(self):
        runner = FakeRunner(self.home, allow_writes=True)
        runner.note_outcome = "replay"
        runner.receipts["pending"] = [{"id": "note-1", "acknowledged": False, "reply": None}]
        ex = self.executor(runner)
        self.assertIn("already queued", ex.note("yes", merge_ask()).text)

    def test_replay_of_an_answered_note_shows_the_earlier_reply(self):
        runner = FakeRunner(self.home, allow_writes=True)
        runner.note_outcome = "replay"
        # fm-inbox.sh reports a replayed, already announced note as acknowledged false; receipts is the truth.
        runner.receipts["handled"] = [{"id": "note-1", "acknowledged": True, "reply": {"body": "Merged at fe05bcd."}}]
        ex = self.executor(runner)
        result = ex.note("yes", pr_ready())
        self.assertEqual((result.state, result.text),
                         ("replied", "answered earlier: YES on delta#3. Earlier reply: Merged at fe05bcd."))
        self.assertEqual(ex.pending, {})

    def test_replay_of_an_acknowledged_note_labels_its_reply_as_earlier(self):
        runner = FakeRunner(self.home, allow_writes=True)
        runner.note_outcome = "replay"
        runner.receipts["handled"] = [{"id": "note-1", "acknowledged": True, "reply": None}]
        ex = self.executor(runner)
        result = ex.note("later", plain_decision())
        self.assertEqual((result.state, result.text), ("queued", "answered earlier: LATER on widget-pricing, no reply yet"))
        runner.receipts["handled"] = [{"id": "note-1", "acknowledged": True, "reply": {"body": "Deferred."}}]
        [reply] = ex.check_receipts()
        self.assertEqual((reply.request_id, reply.state, reply.text), (result.request_id, "replied", "earlier reply: Deferred."))

    def test_replay_falls_back_to_the_note_path_when_receipts_do_not_list_it(self):
        runner = FakeRunner(self.home, allow_writes=True)
        runner.note_outcome = "replay"
        runner.note_path = "/fixture/primary/state/inbox/handled/note-1.note"
        ex = self.executor(runner)
        self.assertEqual(ex.note("hold", plain_decision()).text, "answered earlier: HOLD on widget-pricing, no reply yet")

    def test_note_failure_is_a_failed_result(self):
        runner = FakeRunner(self.home, allow_writes=True)
        runner.note_rc = 1
        ex = self.executor(runner)
        with self.assertLogs("helm.bridge.intents", "WARNING") as logs:
            result = ex.note("yes", merge_ask())
        self.assertEqual(result.state, "failed")
        self.assertIn("note failed (1): wake failed", logs.output[0])
        self.assertEqual(runner.calls_for("fm-inbox.sh", "announce"), [])


class AdoptTest(unittest.TestCase):
    """After a restart the bridge takes back its own notes and shows replies that came while it was down."""

    def setUp(self):
        self.home = Path("/fixture/primary")
        self._tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self._tmp.name) / "cache"
        self.runner = FakeRunner(self.home, allow_writes=True)

    def tearDown(self):
        self._tmp.cleanup()

    def executor(self):
        return IntentExecutor(self.home, self.runner, dry_run=False, clock=lambda: NOW, cache_dir=self.cache)

    def save_cursor(self, cursor, home="/fixture/primary"):
        self.cache.mkdir(parents=True, exist_ok=True)
        (self.cache / "inbox-reply-cursor.json").write_text(json.dumps({"home": home, "cursor": cursor}))

    def note(self, note_id, rid, age_s=60, reply=None):
        return {"id": note_id, "at": utc_stamp(NOW - age_s), "source": "text", "request_id": rid, "body": "...",
                "acknowledged": False, "announced": True, "reply": reply}

    def test_first_start_adopts_waiting_notes_and_shows_no_old_replies(self):
        self.runner.receipts.update(
            pending=[self.note("n1", "helm-yes-primary-a-b-20261111"), self.note("n2", None),
                     self.note("n3", "voice-17")],
            handled=[self.note("n4", "helm-later-primary-c-d-20261111"),
                     self.note("n5", "helm-hold-primary-e-f-20261110", age_s=ADOPT_MAX_AGE_S + 60),
                     self.note("n6", "helm-hold-primary-g-h-20261111", reply={"body": "old", "cursor": "000000000002"})],
            replies=[{"id": "n6", "body": "old", "cursor": "000000000002"}], reply_cursor="000000000002")
        ex = self.executor()
        self.assertEqual(ex.adopt(), [])
        self.assertEqual(self.runner.calls_for("fm-inbox.sh", "receipts"), [["/fixture/primary/bin/fm-inbox.sh", "receipts"]])
        self.assertEqual({rid: p.note_id for rid, p in ex.pending.items()},
                         {"helm-yes-primary-a-b-20261111": "n1", "helm-later-primary-c-d-20261111": "n4"})
        self.assertEqual(json.loads((self.cache / "inbox-reply-cursor.json").read_text())["cursor"], "000000000002")

        self.runner.receipts["handled"][0]["reply"] = {"body": "Deferred.", "cursor": "000000000003"}
        [reply] = ex.check_receipts()
        self.assertEqual((reply.request_id, reply.text), ("helm-later-primary-c-d-20261111", "Deferred."))

    def test_replies_since_the_saved_cursor_are_shown(self):
        self.save_cursor("000000000007")
        reply = {"id": "n1", "body": "Merged.", "cursor": "000000000008"}
        self.runner.receipts.update(handled=[self.note("n1", "helm-yes-primary-a-b-20261111", reply=reply),
                                             self.note("n2", "voice-3", reply={"body": "x", "cursor": "000000000009"})],
                                    replies=[reply, {"id": "n2", "body": "x", "cursor": "000000000009"}],
                                    reply_cursor="000000000009")
        ex = self.executor()
        [result] = ex.adopt()
        self.assertEqual((result.request_id, result.state, result.text), ("helm-yes-primary-a-b-20261111", "replied", "Merged."))
        self.assertEqual(self.runner.calls_for("fm-inbox.sh", "receipts"),
                         [["/fixture/primary/bin/fm-inbox.sh", "receipts", "--after", "000000000007", "--all-replies"]])
        self.assertEqual(ex.pending, {})
        self.assertEqual(json.loads((self.cache / "inbox-reply-cursor.json").read_text())["cursor"], "000000000009")

    def test_a_cursor_saved_for_another_home_is_ignored(self):
        self.save_cursor("000000000007", home="/fixture/other")
        self.executor().adopt()
        self.assertEqual(self.runner.calls_for("fm-inbox.sh", "receipts"), [["/fixture/primary/bin/fm-inbox.sh", "receipts"]])

    def test_unreadable_receipts_adopt_nothing(self):
        self.runner.receipts = None
        ex = self.executor()
        self.assertEqual(ex.adopt(), [])
        self.assertEqual(ex.pending, {})


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
            ex = IntentExecutor(home, Runner(allow_writes=True), dry_run=False, clock=lambda: NOW,
                                cache_dir=home / "cache")
            result = ex.note("yes", merge_ask())
            self.assertEqual(result.state, "queued")
            self.assertIn("wake repaired", result.text)
            lines = log.read_text().splitlines()
            self.assertEqual(len(lines), 2)
            self.assertTrue(lines[0].startswith("%s|note --request-id helm-yes-primary-alpha-fix-merge-alpha-12-" % home))
            self.assertIn("--json -- %s on" % YES_PREFIX, lines[0])
            self.assertEqual(lines[1], "%s|announce --json n-9" % home)


@unittest.skipUnless(os.environ.get(FIRSTMATE_ENV), "set %s to a firstmate checkout to run this" % FIRSTMATE_ENV)
class RealInboxTest(unittest.TestCase):
    """The executor against firstmate's own fm-inbox.sh, in a throwaway home linked to that checkout's bin/."""

    def setUp(self):
        checkout = Path(os.environ[FIRSTMATE_ENV]).expanduser()
        if not (checkout / "bin" / "fm-inbox.sh").is_file():
            self.fail("%s has no bin/fm-inbox.sh" % checkout)
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.home = root / "home"
        for part in ("state", "data", "config", "projects"):
            (self.home / part).mkdir(parents=True)
        (self.home / "bin").symlink_to(checkout / "bin")
        self.cache = root / "cache"
        # Only FM_HOME, set by the executor, may point the script anywhere.
        env = {k: v for k, v in os.environ.items() if not k.startswith("FM_")}
        self._env = mock.patch.dict(os.environ, env, clear=True)
        self._env.start()
        self.now = time.time()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def executor(self):
        return IntentExecutor(self.home, Runner(allow_writes=True), dry_run=False, clock=lambda: self.now,
                              cache_dir=self.cache)

    def firstmate(self, *args):
        done = subprocess.run([str(self.home / "bin" / "fm-inbox.sh"), *args], capture_output=True, text=True,
                              env=dict(os.environ, FM_HOME=str(self.home)), timeout=20)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def test_note_replay_restart_reply_and_answered_earlier(self):
        cand = pr_ready()
        ex = self.executor()
        first = ex.note("yes", cand)
        self.assertEqual((first.state, first.text), ("queued", "queued YES on delta#3"))
        self.assertEqual(ex.note("yes", cand).text, "already queued YES on delta#3")
        [note] = json.loads(self.firstmate("receipts"))["pending"]
        self.assertEqual(note["request_id"], first.request_id)
        self.assertIn("at commit `%s`" % HEAD, note["body"])
        self.assertTrue(note["body"].startswith(YES_PREFIX + " on "))

        # The bridge restarts, firstmate reads the note and replies while it is down.
        restarted = self.executor()
        self.assertEqual(restarted.adopt(), [])
        self.assertIn(first.request_id, restarted.pending)
        self.firstmate("drain", "--ack", note["id"])
        self.firstmate("reply", note["id"], "Merged at the named commit.")
        [reply] = restarted.check_receipts()
        self.assertEqual((reply.request_id, reply.state, reply.text),
                         (first.request_id, "replied", "Merged at the named commit."))

        # The same ask again is answered from the record, not sent as new.
        again = restarted.note("yes", cand)
        self.assertEqual((again.state, again.text),
                         ("replied", "answered earlier: YES on delta#3. Earlier reply: Merged at the named commit."))
        # A new commit on the same PR is a new ask.
        self.assertEqual(restarted.note("yes", pr_ready(NEW_HEAD)).text, "queued YES on delta#3")
        self.assertEqual(len(json.loads(self.firstmate("receipts"))["pending"]), 1)


if __name__ == "__main__":
    unittest.main()
