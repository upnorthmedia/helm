import json
import tempfile
import time
import unittest
from pathlib import Path

from helm.contract import Context, Hello, Key, Knob, Resync, Seen, Select, Usage
from helm.bridge.bridge import Bridge
from helm.bridge.intents import IntentExecutor
from helm.bridge.usage import UsagePoller
from helm.bridge.transports import MemoryTransport
from sim.state import HOLD_S, Deck
from tests.helpers import QUOTA_OK, FakeRunner, ioreg_root, lavish_listing, make_homes


class BridgeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.primary, self.mate = make_homes(Path(self._tmp.name))
        self.now = time.time()
        self.transport = MemoryTransport()
        self.runner = FakeRunner(self.primary, allow_writes=False)
        self.cache = Path(self._tmp.name) / "cache"
        self.executor = IntentExecutor(self.primary, self.runner, dry_run=True, clock=lambda: self.now,
                                       cache_dir=self.cache)
        self.bridge = Bridge(self.transport, self.primary, self.runner, self.executor, clock=lambda: self.now,
                             usage=UsagePoller(self.runner, background=False))

    def tearDown(self):
        self._tmp.cleanup()

    def advance(self, seconds):
        self.now += seconds
        return self.bridge.tick(self.now)

    def add_decision(self, home, row, epoch=None):
        path = home / "state" / "home-summary.json"
        summary = json.loads(path.read_text())
        summary["decisions_open"].append(row)
        summary["generated_epoch"] = epoch or int(self.now)
        path.write_text(json.dumps(summary))

    def test_first_model_is_calm_with_counts(self):
        model = self.bridge.tick(self.now)
        self.assertEqual(model.seq, 1)
        self.assertEqual(model.attention, "calm")
        self.assertEqual(model.unseen, 0)
        self.assertFalse(model.chime)
        self.assertEqual(model.counts.decisions, 4)
        self.assertEqual(model.link.firstmate_can_receive, True)
        self.assertEqual(model.link.posture, "present")
        self.assertIsNone(model.link.stale_reason)
        self.assertEqual({i.home for i in model.items}, {"primary", "mate1", "herdr"})
        # Reads only, and only the allowlisted ones.
        self.assertEqual({tuple(c[1:2]) if "fm-inbox" in c[0] else tuple(c[:3]) for c in self.runner.calls},
                         {("ready",), ("herdr", "agent", "list"), ("quota-axi", "--provider", "claude"),
                          ("/usr/sbin/ioreg", "-n", "Root")})

    def test_resends_every_two_seconds_and_on_change_only(self):
        self.bridge.tick(self.now)
        self.assertIsNone(self.advance(1))
        self.assertEqual(self.advance(1).seq, 2)
        self.assertEqual(len(self.transport.sent), 2)

    def test_new_decision_lights_new_and_chimes_once_then_touch_clears(self):
        self.bridge.tick(self.now)
        self.add_decision(self.mate, {"id": "omega", "key": "omega", "verb": "captain-hold", "question": "Q?",
                                      "hold_age_days": 0})
        model = self.advance(2)
        self.assertEqual(model.attention, "new")
        self.assertEqual(model.unseen, 1)
        self.assertTrue(model.chime)
        self.assertEqual(model.items[0].ref, "decision|mate1|omega|omega")  # unseen sorts first
        self.assertTrue(model.items[0].unseen)
        self.assertFalse(self.advance(2).chime)  # the periodic resend does not chime again

        self.bridge.handle(Knob(1), self.now)  # any touch
        model = self.advance(0.1)
        self.assertEqual((model.attention, model.unseen), ("calm", 0))

    def test_ledger_edge_shows_the_item_before_the_summary_catches_up(self):
        ledger = self.primary / "state" / "fleet-ledger.jsonl"
        ledger.write_text(json.dumps({"v": 1, "ts": 1, "event": "task.status", "task": "old"}) + "\n")
        self.bridge.tick(self.now)
        with ledger.open("a") as fh:
            fh.write(json.dumps({"v": 1, "ts": int(self.now), "event": "task.status", "task": "kappa",
                                 "state": "needs-decision", "key": "merge-kappa-4",
                                 "text": " PR https://github.com/example/kappa/pull/4 green"}) + "\n")
        model = self.advance(0.5)  # ledger is checked every step, the summary every 2 s
        self.assertEqual(model.items[0].ref, "decision|primary|kappa|merge-kappa-4")
        self.assertTrue(model.chime)
        self.assertEqual(model.counts.decisions, 5)

    def test_unknown_when_firstmate_cannot_receive(self):
        self.runner.ready["can_receive"] = False
        model = self.bridge.tick(self.now)
        self.assertEqual(model.attention, "unknown")
        self.assertEqual(model.link.stale_reason, "firstmate cannot receive")
        self.runner.ready = None
        self.now += 15
        model = self.bridge.tick(self.now)
        self.assertEqual(model.attention, "unknown")
        self.assertIsNone(model.link.firstmate_can_receive)
        self.assertIn("readiness unreadable", model.link.stale_reason)

    def test_herdr_failure_is_reported_not_fatal(self):
        self.runner.agents = None
        model = self.bridge.tick(self.now)
        self.assertEqual(model.link.stale_reason, "herdr unavailable")
        self.assertEqual(model.attention, "calm")

    def test_held_yes_on_selected_item_is_one_dry_run_note(self):
        self.bridge.tick(self.now)
        ref = "decision|primary|alpha-fix|merge-alpha-12"
        for event in (Hello("0.1", ["keys", "knob"]), Select(ref), Key("yes", "down", ref), Key("yes", "held", ref),
                      Key("yes", "up", ref)):
            self.bridge.handle(event, self.now)
        model = self.advance(0.1)
        self.assertEqual(model.result.state, "queued")
        self.assertTrue(model.result.request_id.startswith("helm-yes-primary-alpha-fix-merge-alpha-12-"))
        self.assertEqual(len(self.executor.dry_log), 1)
        self.assertIn("held to confirm: YES on `alpha-fix` / `merge-alpha-12`", self.executor.dry_log[0])
        self.assertEqual(self.runner.calls_for("fm-inbox.sh", "note"), [])

    def set_head(self, url, head):
        path = self.primary / "state" / "home-summary.json"
        summary = json.loads(path.read_text())
        [row] = [c for c in summary["contributions"]["captain"] if c["url"] == url]
        row["head"] = head
        path.write_text(json.dumps(summary))

    def test_held_yes_on_a_pr_pins_the_commit_and_a_new_commit_is_a_new_ask(self):
        url = "https://github.com/example/delta/pull/3"
        ref = "pr|primary|" + url
        heads = ("fe05bcdcdc4928012781a5f1a2a77cbb5398e106", "ad782ecdac770fc6eb9a62e44f90873fb97fb26b")
        self.set_head(url, heads[0])
        self.bridge.tick(self.now)
        self.bridge.handle(Key("yes", "held", ref), self.now)
        first = self.advance(0.1).result
        self.assertIn("merge `%s` at commit `%s` under your normal checks" % (url, heads[0]), self.executor.dry_log[-1])
        self.assertTrue(first.request_id.endswith("-%s-%s" % (heads[0][:12], time.strftime("%Y%m%d", time.localtime(self.now)))))

        self.set_head(url, heads[1])  # a push lands after the deck showed the PR
        self.advance(2.5)
        self.bridge.handle(Key("yes", "held", ref), self.now)
        second = self.advance(0.1).result
        self.assertNotEqual(first.request_id, second.request_id)
        self.assertIn("at commit `%s`" % heads[1], self.executor.dry_log[-1])

    def test_yes_refuses_when_the_pr_head_changed_during_the_hold(self):
        url = "https://github.com/example/delta/pull/3"
        ref = "pr|primary|" + url
        heads = ("fe05bcdcdc4928012781a5f1a2a77cbb5398e106", "ad782ecdac770fc6eb9a62e44f90873fb97fb26b")
        self.set_head(url, heads[0])
        self.bridge.tick(self.now)
        self.bridge.handle(Key("yes", "down", ref), self.now)
        self.set_head(url, heads[1])  # the summary refreshes while the key is held
        self.advance(2.5)
        self.bridge.handle(Key("yes", "held", ref), self.now)
        result = self.advance(0.1).result
        self.assertEqual((result.state, result.text), ("failed", "PR changed, look again: delta#3"))
        self.assertEqual(self.executor.dry_log, [])

        # A fresh hold on what the deck now shows goes through, pinned to that commit.
        self.bridge.handle(Key("yes", "down", ref), self.now)
        self.bridge.handle(Key("yes", "held", ref), self.now)
        self.assertEqual(self.advance(0.1).result.state, "queued")
        self.assertIn("at commit `%s`" % heads[1], self.executor.dry_log[-1])

    def test_yes_with_no_down_is_bound_to_the_head_last_sent_to_the_deck(self):
        url = "https://github.com/example/delta/pull/3"
        ref = "pr|primary|" + url
        self.set_head(url, "fe05bcdcdc4928012781a5f1a2a77cbb5398e106")
        self.bridge.tick(self.now)
        self.set_head(url, "ad782ecdac770fc6eb9a62e44f90873fb97fb26b")
        self.now += 2.5
        self.bridge.poll_sources(self.now)  # the bridge reads the new head but has not sent a model since
        self.bridge.handle(Key("yes", "held", ref), self.now)
        self.assertEqual(self.bridge.result.text, "PR changed, look again: delta#3")
        self.assertEqual(self.executor.dry_log, [])

    def test_start_keeps_every_recovered_reply_newest_first(self):
        self.runner.allow_writes = True
        self.executor.dry_run = False
        self.cache.mkdir()
        (self.cache / "inbox-reply-cursor.json").write_text(json.dumps({"home": str(self.primary), "cursor": "000000000003"}))
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.now - 30))
        replies = [{"id": "n%d" % i, "body": "reply %d" % i, "cursor": "%012d" % (3 + i)} for i in (1, 2, 3)]
        self.runner.receipts.update(
            handled=[{"id": r["id"], "at": stamp, "request_id": "helm-yes-primary-t%s-k-20261111" % r["id"], "reply": r}
                     for r in replies],
            replies=replies, reply_cursor="000000000006")
        self.bridge.start()
        shown = [self.bridge.tick(self.now).result]
        for _ in range(3):
            shown.append(self.advance(121).result)  # each reply lingers 120 s, then the next one shows
        self.assertEqual([r.text if r else None for r in shown], ["reply 3", "reply 2", "reply 1", None])

    def test_start_takes_back_notes_and_shows_a_reply_from_while_it_was_down(self):
        self.runner.allow_writes = True
        self.executor.dry_run = False
        self.cache.mkdir()
        (self.cache / "inbox-reply-cursor.json").write_text(json.dumps({"home": str(self.primary), "cursor": "000000000003"}))
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.now - 30))
        reply = {"id": "n1", "body": "Merged.", "cursor": "000000000004"}
        self.runner.receipts.update(
            pending=[{"id": "n2", "at": stamp, "request_id": "helm-hold-primary-x-y-20261111", "reply": None}],
            handled=[{"id": "n1", "at": stamp, "request_id": "helm-yes-primary-a-b-20261111", "reply": reply}],
            replies=[reply], reply_cursor="000000000004")
        self.bridge.start()
        model = self.bridge.tick(self.now)
        self.assertEqual((model.result.request_id, model.result.state, model.result.text),
                         ("helm-yes-primary-a-b-20261111", "replied", "Merged."))
        self.assertEqual(list(self.executor.pending), ["helm-hold-primary-x-y-20261111"])

    def test_lost_select_does_not_turn_yes_onto_the_previous_item(self):
        # A real deck (the simulator's) in front of the bridge, with one select frame lost on the way.
        deck = Deck()
        deck.on_model(self.bridge.tick(self.now), self.now)
        deck.knob_press(False, self.now)  # open the list
        deck.knob(1, self.now)  # gamma-choice: this select arrives
        for event in deck.take_outbox():
            self.bridge.handle(event, self.now)
        deck.knob(1, self.now)  # widget-pricing: this select is lost
        self.assertEqual(deck.selected_ref, "decision|primary|widget-pricing|widget-pricing")
        dropped = deck.take_outbox()
        self.assertIn(Select("decision|primary|widget-pricing|widget-pricing"), dropped)
        deck.key_down("yes", self.now)
        deck.tick(self.now + HOLD_S)
        for event in deck.take_outbox():
            self.bridge.handle(event, self.now)
        self.assertEqual(len(self.executor.dry_log), 1)
        self.assertIn("YES on `widget-pricing`", self.executor.dry_log[0])
        self.assertNotIn("gamma-choice", self.executor.dry_log[0])

    def test_yes_is_refused_when_dark(self):
        self.bridge.tick(self.now)
        self.bridge.handle(Select("decision|primary|beta-port|merge-beta-7"), self.now)  # PR known red
        self.bridge.handle(Key("yes", "held", "decision|primary|beta-port|merge-beta-7"), self.now)
        model = self.advance(0.1)
        self.assertEqual(model.result.state, "failed")
        self.assertEqual(self.executor.dry_log, [])

    def test_key_naming_no_item_is_refused_whatever_was_selected(self):
        # A deck from before Key.ref sends keys with no ref: the last select is never used instead.
        self.bridge.tick(self.now)
        self.bridge.handle(Select("decision|primary|alpha-fix|merge-alpha-12"), self.now)
        self.bridge.handle(Key("hold", "held"), self.now)
        self.assertEqual(self.advance(0.1).result.text, "key named no item: update the deck")
        self.bridge.handle(Select("worker|primary|beta-port"), self.now)
        self.bridge.handle(Key("focus", "up"), self.now)
        self.assertEqual(self.advance(0.1).result.text, "key named no item: update the deck")
        self.assertEqual(self.executor.dry_log, [])

    def test_key_naming_a_gone_item_is_refused(self):
        self.bridge.tick(self.now)
        self.bridge.handle(Select("decision|primary|alpha-fix|merge-alpha-12"), self.now)
        self.bridge.handle(Key("yes", "held", "decision|primary|omega|omega"), self.now)
        result = self.advance(0.1).result
        self.assertEqual((result.state, result.text), ("failed", "that item is gone"))
        self.bridge.handle(Key("focus", "up", "decision|primary|omega|omega"), self.now)
        self.assertEqual(self.advance(0.1).result.text, "that item is gone")
        self.assertEqual(self.executor.dry_log, [])

    def test_show_me_focuses_the_pane_on_tap(self):
        self.bridge.tick(self.now)
        self.bridge.handle(Select("worker|primary|beta-port"), self.now)
        self.bridge.handle(Key("focus", "down", "worker|primary|beta-port"), self.now)
        self.assertEqual(self.executor.dry_log, [])
        self.bridge.handle(Key("focus", "up", "worker|primary|beta-port"), self.now)
        self.assertEqual(self.executor.dry_log, ["herdr agent focus wB:p1"])
        self.assertEqual(self.runner.calls_for("herdr", "agent", "focus"), [])

    def test_show_me_focuses_first_then_opens_the_report(self):
        report = self.primary / "data" / "widget-pricing" / "report.md"
        report.parent.mkdir(parents=True)
        report.write_text("# Widget pricing\n")
        self.bridge.tick(self.now)
        self.bridge.handle(Select("decision|primary|widget-pricing|widget-pricing"), self.now)
        self.bridge.handle(Key("focus", "up", "decision|primary|widget-pricing|widget-pricing"), self.now)
        page = self.cache / "reports" / "primary-widget-pricing-report.html"
        self.assertEqual(self.executor.dry_log, ["herdr agent focus w0:p1", "lavish-axi %s --reopen --no-gate" % page])
        self.assertEqual(self.advance(0.1).result.text, "dry run: report for widget-pricing logged")
        self.assertFalse(self.cache.exists())

    def test_show_me_opens_a_live_board_named_in_the_hold(self):
        self.runner.allow_writes = True
        self.executor.dry_run = False
        sid = "124243bf9534df5d"
        self.runner.lavish = lavish_listing(("/elsewhere/review/index.html", "open",
                                             "http://deck-mac.example.ts.net:4387/session/%s" % sid))
        self.add_decision(self.primary, {"id": "case-pick", "key": "case-pick", "verb": "needs-decision",
                                         "summary": "Pick a case, live board http://deck-mac.example.ts.net:4387/session/%s" % sid})
        self.bridge.tick(self.now)
        self.bridge.handle(Select("decision|primary|case-pick|case-pick"), self.now)
        self.bridge.handle(Key("focus", "up", "decision|primary|case-pick|case-pick"), self.now)
        self.assertEqual(self.runner.calls_for("herdr", "agent", "focus"), [["herdr", "agent", "focus", "w0:p1"]])
        self.assertEqual(self.runner.calls_for("open", "<url>"), [["open", "http://127.0.0.1:4387/session/%s" % sid]])
        self.assertEqual(self.advance(0.1).result.text, "opening board for case-pick")

    def test_show_me_opens_the_pr_when_there_is_nothing_else(self):
        self.bridge.tick(self.now)
        self.bridge.handle(Select("decision|primary|alpha-fix|merge-alpha-12"), self.now)
        self.bridge.handle(Key("focus", "up", "decision|primary|alpha-fix|merge-alpha-12"), self.now)
        self.assertEqual(self.executor.dry_log, ["herdr agent focus w0:p1", "open https://github.com/example/alpha/pull/12"])
        self.assertEqual(self.advance(0.1).result.text, "dry run: PR for alpha-fix/merge-alpha-12 logged")

    def test_show_me_without_a_pane_still_opens_the_pr(self):
        self.runner.agents = []
        (self.primary / "state" / "alpha-fix.meta").write_text("kind=ship\n")
        model = self.bridge.tick(self.now)
        ref = "decision|primary|alpha-fix|merge-alpha-12"
        self.assertIn("focus", next(i for i in model.items if i.ref == ref).actions)
        self.bridge.handle(Select(ref), self.now)
        self.bridge.handle(Key("focus", "up", ref), self.now)
        self.assertEqual(self.executor.dry_log, ["open https://github.com/example/alpha/pull/12"])
        self.assertEqual(self.advance(0.1).result.text, "dry run: PR for alpha-fix/merge-alpha-12 logged")

    def test_show_me_reports_an_open_that_failed(self):
        self.runner.allow_writes = True
        self.executor.dry_run = False
        self.runner.open_rc = 1
        self.bridge.tick(self.now)
        self.bridge.handle(Select("decision|primary|alpha-fix|merge-alpha-12"), self.now)
        with self.assertLogs("helm.bridge.intents", "WARNING"):
            self.bridge.handle(Key("focus", "up", "decision|primary|alpha-fix|merge-alpha-12"), self.now)
        result = self.advance(0.1).result
        self.assertEqual((result.state, result.text), ("failed", "PR for alpha-fix/merge-alpha-12 did not open; pane focused"))

    def test_live_note_reply_flows_back_into_the_model(self):
        self.runner.allow_writes = True
        self.executor.dry_run = False
        self.bridge.tick(self.now)
        self.bridge.handle(Select("decision|primary|widget-pricing|widget-pricing"), self.now)
        self.bridge.handle(Key("later", "held", "decision|primary|widget-pricing|widget-pricing"), self.now)
        self.assertEqual(self.advance(0.1).result.state, "queued")
        self.runner.receipts["handled"] = [{"id": "note-1", "reply": {"body": "Re-held until tomorrow."}}]
        model = self.advance(5)
        self.assertEqual((model.result.state, model.result.text), ("replied", "Re-held until tomorrow."))
        receipts_calls = len(self.runner.calls_for("fm-inbox.sh", "receipts"))
        self.advance(10)
        self.assertEqual(len(self.runner.calls_for("fm-inbox.sh", "receipts")), receipts_calls)  # nothing pending

    def test_seen_event(self):
        self.bridge.tick(self.now)
        self.add_decision(self.primary, {"id": "nu", "key": "nu", "verb": "captain-hold", "hold_age_days": 0})
        self.assertEqual(self.advance(2).unseen, 1)
        self.bridge.handle(Seen(), self.now)
        self.assertEqual(self.advance(0.1).unseen, 0)

    def test_resync_resends_now_and_is_not_a_touch(self):
        self.bridge.tick(self.now)
        self.add_decision(self.primary, {"id": "xi", "key": "xi", "verb": "captain-hold", "hold_age_days": 0})
        self.assertEqual(self.advance(2).unseen, 1)
        self.bridge.handle(Resync(), self.now)
        model = self.advance(0.1)  # well inside the 2 s resend window
        self.assertIsNotNone(model)
        self.assertEqual((model.attention, model.unseen), ("new", 1))

    # Usage gauge

    def set_quota_resets(self, five_hour_in: float, week_in: float):
        from datetime import datetime, timezone

        def iso(t):
            return datetime.fromtimestamp(t, timezone.utc).isoformat().replace("+00:00", "Z")

        windows = self.runner.quota["providers"][0]["windows"]
        windows[0]["resetsAt"] = iso(self.now + five_hour_in)
        windows[1]["resetsAt"] = iso(self.now + week_in)

    def test_usage_gauge_reads_quota_axi(self):
        self.now = float(int(self.now))  # whole seconds, so the ISO round trip is exact
        self.set_quota_resets(3600, 86400 * 2)
        model = self.bridge.tick(self.now)
        self.assertEqual((model.usage.five_hour_left, model.usage.week_left), (62, 40))  # 62.7 rounds down
        self.assertEqual((model.usage.five_hour_resets_s, model.usage.week_resets_s), (3600, 172800))
        self.assertEqual(len(self.runner.calls_for("quota-axi", "--provider", "claude", "--json")), 1)
        # The reset counts down without forcing a send, and quota-axi is not asked again for 5 minutes.
        self.assertIsNone(self.advance(1))
        self.assertEqual(self.advance(1).usage.five_hour_resets_s, 3598)
        self.advance(240)
        self.assertEqual(len(self.runner.calls_for("quota-axi", "--provider", "claude", "--json")), 1)
        self.advance(60)
        self.assertEqual(len(self.runner.calls_for("quota-axi", "--provider", "claude", "--json")), 2)

    def test_usage_is_unknown_when_quota_axi_fails_never_full(self):
        self.assertEqual(self.bridge.tick(self.now).usage.five_hour_left, 62)
        self.runner.quota = None  # quota-axi missing
        self.assertEqual(self.advance(300).usage, Usage())
        self.runner.quota = json.loads(json.dumps(QUOTA_OK))
        self.runner.quota["providers"][0]["state"] = {"status": "auth_required", "stale": False,
                                                       "error": "keychain_prompt_required"}
        self.runner.quota["providers"][0]["windows"] = []
        self.assertEqual(self.advance(300).usage, Usage())
        self.runner.quota["providers"][0]["state"] = {"status": "stale", "stale": True}
        self.runner.quota["providers"][0]["windows"] = QUOTA_OK["providers"][0]["windows"]
        self.assertEqual(self.advance(300).usage, Usage())  # a cached reading is not a reading

    # Follow away mode

    def test_away_mutes_chimes_and_locks_acting_keys(self):
        self.runner.ready["posture"] = {"state": "away"}
        model = self.bridge.tick(self.now)
        self.assertTrue(model.link.away)
        self.assertEqual(model.attention, "calm")  # still listening
        self.assertTrue(all(set(i.actions) <= {"focus"} for i in model.items))
        self.assertIn("focus", next(i for i in model.items if i.ref == "worker|primary|beta-port").actions)

        self.add_decision(self.primary, {"id": "rho", "key": "rho", "verb": "captain-hold", "hold_age_days": 0})
        model = self.advance(2)
        self.assertEqual((model.attention, model.unseen, model.chime), ("new", 1, False))

        self.bridge.handle(Select("decision|primary|alpha-fix|merge-alpha-12"), self.now)
        self.bridge.handle(Key("yes", "held", "decision|primary|alpha-fix|merge-alpha-12"), self.now)
        model = self.advance(0.1)
        self.assertEqual((model.result.state, model.result.text), ("failed", "keys locked: firstmate is away"))
        self.assertEqual(self.executor.dry_log, [])
        self.bridge.handle(Select("worker|primary|beta-port"), self.now)
        self.bridge.handle(Key("focus", "up", "worker|primary|beta-port"), self.now)
        self.assertEqual(self.executor.dry_log, ["herdr agent focus wB:p1"])  # SHOW ME still works

    def test_quiet_counts_as_away_and_return_does_not_ring_late(self):
        self.runner.ready["posture"] = {"state": "quiet"}
        self.bridge.tick(self.now)
        self.add_decision(self.primary, {"id": "sigma", "key": "sigma", "verb": "captain-hold", "hold_age_days": 0})
        model = self.advance(2)
        self.assertTrue(model.link.away)
        self.assertFalse(model.chime)
        self.runner.ready["posture"] = {"state": "present"}
        model = self.advance(15)  # the next readiness poll
        self.assertFalse(model.link.away)
        self.assertFalse(model.chime)
        self.assertIn("yes", next(i for i in model.items if i.ref == "decision|primary|sigma|sigma").actions)

    def test_unknown_posture_is_not_away(self):
        self.runner.ready["posture"] = {"state": "unknown"}
        model = self.bridge.tick(self.now)
        self.assertFalse(model.link.away)
        self.assertIn("yes", next(i for i in model.items if i.ref == "decision|primary|alpha-fix|merge-alpha-12").actions)


    # Lock keys when the Mac is locked

    def test_locked_mac_drops_every_action_and_refuses_keys(self):
        self.runner.ioreg = ioreg_root(locked=True)
        model = self.bridge.tick(self.now)
        self.assertTrue(model.link.mac_locked)
        self.assertFalse(model.link.away)
        self.assertEqual(model.attention, "calm")  # not a link problem
        self.assertTrue(all(i.actions == [] for i in model.items))  # SHOW ME too

        self.bridge.handle(Select("decision|primary|alpha-fix|merge-alpha-12"), self.now)
        self.bridge.handle(Key("yes", "held", "decision|primary|alpha-fix|merge-alpha-12"), self.now)
        model = self.advance(0.1)
        self.assertEqual((model.result.state, model.result.text), ("failed", "keys locked: the Mac is locked"))
        self.bridge.handle(Select("worker|primary|beta-port"), self.now)
        self.bridge.handle(Key("focus", "up", "worker|primary|beta-port"), self.now)
        self.bridge.handle(Select("decision|primary|alpha-fix|merge-alpha-12"), self.now)
        # Has a PR to open, but nothing opens either.
        self.bridge.handle(Key("focus", "up", "decision|primary|alpha-fix|merge-alpha-12"), self.now)
        self.assertEqual(self.executor.dry_log, [])
        self.assertEqual(self.runner.calls_for("lavish-axi"), [])

        self.runner.ioreg = ioreg_root(locked=False)
        model = self.advance(3)  # the next lock poll
        self.assertFalse(model.link.mac_locked)
        self.assertIn("yes", next(i for i in model.items if i.ref == "decision|primary|alpha-fix|merge-alpha-12").actions)

    def test_lock_is_read_again_right_before_acting(self):
        self.bridge.tick(self.now)
        self.bridge.handle(Select("decision|primary|alpha-fix|merge-alpha-12"), self.now)
        self.runner.ioreg = ioreg_root(locked=True)  # locked since the last poll
        self.bridge.handle(Key("yes", "held", "decision|primary|alpha-fix|merge-alpha-12"), self.now + 0.5)
        self.bridge.handle(Key("focus", "up", "decision|primary|alpha-fix|merge-alpha-12"), self.now + 0.6)
        self.assertEqual(self.executor.dry_log, [])
        self.assertEqual(self.bridge.result.text, "keys locked: the Mac is locked")
        self.assertTrue(self.advance(0.7).link.mac_locked)

    def test_locked_mac_still_chimes(self):
        self.runner.ioreg = ioreg_root(locked=True)
        self.bridge.tick(self.now)
        self.add_decision(self.primary, {"id": "tau", "key": "tau", "verb": "captain-hold", "hold_age_days": 0})
        model = self.advance(2)
        self.assertEqual((model.attention, model.chime), ("new", True))

    def test_lock_unknown_leaves_keys_unlocked(self):
        self.runner.ioreg = None  # ioreg missing, as off macOS
        model = self.bridge.tick(self.now)
        self.assertFalse(model.link.mac_locked)
        self.assertIn("yes", next(i for i in model.items if i.ref == "decision|primary|alpha-fix|merge-alpha-12").actions)

    # Context gauge

    def test_context_gauge_from_herdr_tokens(self):
        self.runner.agents[0]["tokens"]["context"] = "\u26c1 49% (492k)"
        self.runner.agents[2]["tokens"]["context"] = "\u26a0\ufe0f 88% (880k)"
        model = self.bridge.tick(self.now)
        self.assertEqual(model.context, Context(top_used=88, top_agent="scratch-agent", near_limit=1))

    def test_context_is_unknown_without_readings_or_herdr(self):
        self.assertEqual(self.bridge.tick(self.now).context, Context())  # no agent reports a percent
        self.runner.agents[0]["tokens"]["context"] = "\u26c1 49% (492k)"
        self.assertEqual(self.advance(3).context.top_used, 49)
        self.runner.agents = None  # herdr unavailable: the last list is stale, so unknown
        self.assertEqual(self.advance(3).context, Context())


if __name__ == "__main__":
    unittest.main()
