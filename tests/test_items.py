import json
import tempfile
import time
import unittest
from pathlib import Path

from helm.bridge.items import (
    HomeSnapshot, LedgerState, build_candidates, decision_ref, more_ref, pr_checks, pr_ref, pr_verdict, summary_invalid, summary_unknown,
    worker_ref,
)
from helm.bridge.sources import discover_homes
from tests.helpers import herdr_agents, make_homes, use_variant


class BuildCandidatesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.primary, self.mate = make_homes(Path(self._tmp.name))
        self.now = time.time()

    def tearDown(self):
        self._tmp.cleanup()

    def snapshots(self):
        snaps = []
        for home in discover_homes(self.primary):
            summary = json.loads((home.path / "state" / "home-summary.json").read_text())
            health_path = home.path / "state" / "pr-health.json"
            health = json.loads(health_path.read_text()) if health_path.exists() else None
            snaps.append(HomeSnapshot(home, summary, health))
        return snaps

    def build(self, ledger=None, agents=None):
        cands, counts = build_candidates(self.snapshots(), ledger or LedgerState(),
                                         herdr_agents(self.primary) if agents is None else agents, self.now)
        return {c.item.ref: c for c in cands}, counts

    def edit_summary(self, change, home=None):
        path = (home or self.primary) / "state" / "home-summary.json"
        summary = json.loads(path.read_text())
        change(summary)
        path.write_text(json.dumps(summary))

    def test_items_and_counts_from_fixture_homes(self):
        cands, counts = self.build()
        self.assertEqual(set(cands), {
            decision_ref("primary", "theta-cut", "theta-cut"),
            decision_ref("primary", "widget-pricing", "widget-pricing"),
            decision_ref("primary", "alpha-fix", "merge-alpha-12"),
            decision_ref("primary", "omega-ci", "merge-omega-7"),
            decision_ref("mate1", "gamma-choice", "gamma-choice"),
            pr_ref("primary", "https://github.com/example/delta/pull/3"),
            worker_ref("primary", "beta-port"),
            "herdr|wC:p3",
        })
        self.assertEqual(counts.decisions, 5)
        self.assertEqual(counts.working, 1)  # delta-docs; the second mate's endpoint is a home, not a worker
        self.assertEqual(counts.queued, 4)
        self.assertEqual(counts.landed_today, 1)
        self.assertEqual(counts.prs_ready, 3)  # delta pull/3 plus the two merge asks
        self.assertEqual((counts.herdr_working, counts.herdr_blocked), (1, 1))

    def test_projects_come_from_children_meta_and_pr_urls(self):
        (self.primary / "state" / "widget-pricing.meta").write_text("kind=ship\nproject=/work/projects/widget-shop\n")
        (self.primary / "state" / "mate1.meta").write_text("kind=secondmate\nproject=/work/firstmate\n")
        (self.primary / "state" / "theta-cut.meta").write_text("kind=ship\n")
        cands, _ = self.build()
        projects = {ref: c.item.project for ref, c in cands.items()}
        self.assertEqual(projects, {
            decision_ref("primary", "theta-cut", "theta-cut"): "theta",  # its captain row's PR repo
            decision_ref("primary", "widget-pricing", "widget-pricing"): "widget-shop",  # meta project path
            decision_ref("primary", "alpha-fix", "merge-alpha-12"): "alpha",
            decision_ref("primary", "omega-ci", "merge-omega-7"): "omega",
            decision_ref("mate1", "gamma-choice", "gamma-choice"): None,  # nothing names one
            pr_ref("primary", "https://github.com/example/delta/pull/3"): "delta",  # the active child's repo
            worker_ref("primary", "beta-port"): "beta",
            "herdr|wC:p3": None,
        })

    def test_project_falls_back_to_the_pr_repo(self):
        def change(summary):
            summary["decisions_open"].append({"id": "mate1", "key": "merge-sigma-9", "verb": "needs-decision",
                                              "summary": "https://github.com/example/sigma/pull/9 green; merge?",
                                              "reason": None, "source": "status"})
        self.edit_summary(change)
        (self.primary / "state" / "alpha-fix.meta").write_text("kind=ship\n")
        (self.primary / "state" / "mate1.meta").write_text("kind=secondmate\nproject=/work/firstmate\n")
        cands, _ = self.build()
        self.assertEqual(cands[decision_ref("primary", "alpha-fix", "merge-alpha-12")].item.project, "alpha")
        self.assertEqual(cands[decision_ref("primary", "mate1", "merge-sigma-9")].item.project, "sigma")

    # Worker problems come from endpoints[], the current state of every task

    def test_blocked_worker_comes_from_endpoints_with_its_hold_text(self):
        # The producer lists only working tasks in active_children; beta-port is blocked in endpoints[].
        summary = json.loads((self.primary / "state" / "home-summary.json").read_text())
        self.assertNotIn("beta-port", [c["id"] for c in summary["active_children"]])
        cands, _ = self.build()
        beta = cands[worker_ref("primary", "beta-port")]
        self.assertEqual((beta.item.kind, beta.item.color), ("worker_problem", "amber"))
        self.assertEqual(beta.item.detail, "beta-port blocked: waiting on credentials")  # the holds[] row
        self.assertEqual(beta.pane, "wB:p1")
        self.assertEqual(beta.origin_epoch, 1700000500)  # its newest status line

    def test_failed_worker_comes_from_endpoints(self):
        use_variant(self.primary, "primary-failed")
        cands, _ = self.build()
        eta = cands[worker_ref("primary", "eta-sync")].item
        self.assertEqual(eta.detail, "eta-sync failed")  # a failed task has no holds[] row
        self.assertEqual((eta.project, eta.actions), ("eta", ["hold", "focus"]))

    def test_failed_worker_takes_the_ledger_text_when_the_summary_has_none(self):
        use_variant(self.primary, "primary-failed")
        ledger = LedgerState()
        ledger.apply("primary", [{"v": 1, "ts": self.now - 5, "event": "task.status", "task": "eta-sync",
                                  "state": "failed", "key": None, "text": " tests failed three times"}], self.now)
        cands, _ = self.build(ledger)
        eta = cands[worker_ref("primary", "eta-sync")]
        self.assertEqual(eta.item.detail, "eta-sync failed: tests failed three times")
        self.assertEqual(eta.origin_epoch, self.now - 5)

    def test_a_second_mate_endpoint_is_never_a_worker_problem(self):
        def change(summary):
            next(e for e in summary["endpoints"] if e["id"] == "mate1")["state"] = "blocked"
        self.edit_summary(change)
        cands, _ = self.build()
        self.assertNotIn(worker_ref("primary", "mate1"), cands)

    def test_working_counts_every_working_endpoint(self):
        # A task with no backlog row is missing from active_children but still working (the summary is
        # then invalid with unowned_current, as firstmate publishes it).
        def change(summary):
            summary["endpoints"].append({"id": "scout-x", "state": "working", "source": "pane",
                                         "endpoint": {"target": "fm-scout-x", "exists": True}})
        self.edit_summary(change)
        _, counts = self.build()
        self.assertEqual(counts.working, 2)

    # Honesty fields

    def test_omitted_decisions_are_counted_and_shown_as_more(self):
        def change(summary):
            summary["omitted"] = [{"surface": "decisions_open", "count": 7}, {"surface": "queued", "count": 2},
                                  {"surface": "endpoints", "count": 3}]
        self.edit_summary(change)
        cands, counts = self.build()
        self.assertEqual(counts.decisions, 5 + 7)
        more = cands[more_ref("primary", "decisions_open")]
        self.assertTrue(more.informational)
        self.assertEqual((more.item.kind, more.item.short_id, more.item.actions), ("decision", "+7 more decisions", []))
        self.assertIn("left out 7 more decisions", more.item.detail)
        tasks = cands[more_ref("primary", "endpoints")]
        self.assertEqual((tasks.item.kind, tasks.item.short_id), ("worker_problem", "+3 more tasks"))
        self.assertNotIn(more_ref("primary", "queued"), cands)  # counts.queued already holds the total

    def test_summary_invalid_reads_the_producer_reason(self):
        self.assertIsNone(summary_invalid(json.loads((self.primary / "state" / "home-summary.json").read_text())))
        use_variant(self.primary, "primary-failed")
        summary = json.loads((self.primary / "state" / "home-summary.json").read_text())
        self.assertEqual(summary_invalid(summary), "in-flight backlog item has terminal child state: eta-sync=failed")

    def test_summary_unknown_follows_firstmates_own_reading(self):
        def load():
            return json.loads((self.primary / "state" / "home-summary.json").read_text())
        self.assertFalse(summary_unknown(load()))
        use_variant(self.primary, "primary-failed")  # terminal_in_flight: an inventory mismatch
        self.assertFalse(summary_unknown(load()))
        use_variant(self.primary, "primary-unknown")  # child_current_unavailable: state "unknown"
        self.assertTrue(summary_unknown(load()))
        mismatch = {"valid": False, "invalidity": {"kind": "unowned_current", "ids": ["x"]}, "state": "unknown"}
        self.assertTrue(summary_unknown(mismatch))  # firstmate's state wins: an unavailable child as well
        self.assertTrue(summary_unknown({"valid": False, "invalidity": {"kind": "missing_backlog", "ids": []}}))
        self.assertFalse(summary_unknown({"valid": False, "invalidity": {"kind": "orphan_in_flight", "ids": []}}))

    # PR verdicts

    def test_a_fresh_captain_row_is_green_whatever_pr_health_reported(self):
        # pr-health reported alpha failing at this very head; a re-run then passed and firstmate's
        # fresh read put the PR on the captain's list. The report is never cleared.
        cands, _ = self.build()
        alpha = cands[decision_ref("primary", "alpha-fix", "merge-alpha-12")].item
        self.assertEqual(alpha.checks, "green")
        self.assertIn("yes", alpha.actions)

    def test_a_stale_captain_row_falls_back_to_pr_health_at_its_commit(self):
        def change(summary):
            for row in summary["contributions"]["captain"]:
                row["checked_at"] = "2026-01-01T00:00:00Z"
        self.edit_summary(change)
        cands, _ = self.build()
        alpha = cands[decision_ref("primary", "alpha-fix", "merge-alpha-12")].item
        self.assertEqual(alpha.checks, "red")  # reported at the captain row's head
        self.assertNotIn("yes", alpha.actions)
        self.assertIn("pr-health reported failing checks at this commit", alpha.detail)
        delta = cands[pr_ref("primary", "https://github.com/example/delta/pull/3")].item
        self.assertEqual(delta.checks, "unknown")  # reported only at an earlier commit
        self.assertIn("yes", delta.actions)

    def test_a_captain_row_with_a_hold_merges_into_its_decision(self):
        cands, counts = self.build()
        self.assertNotIn(pr_ref("primary", "https://github.com/example/theta/pull/5"), cands)
        theta = cands[decision_ref("primary", "theta-cut", "theta-cut")].item
        self.assertEqual(theta.kind, "decision")
        self.assertIn("PR https://github.com/example/theta/pull/5", theta.detail)
        self.assertIsNone(theta.pr_url)  # a YES answers the hold, not "merge this PR"
        self.assertEqual(counts.prs_ready, 3)  # a held PR is not ready

    def test_a_held_captain_row_without_its_decision_row_becomes_the_decision(self):
        self.edit_summary(lambda s: s.update(decisions_open=[d for d in s["decisions_open"] if d["id"] != "theta-cut"]))
        cands, _ = self.build()
        self.assertNotIn(pr_ref("primary", "https://github.com/example/theta/pull/5"), cands)
        theta = cands[decision_ref("primary", "theta-cut", "theta-cut")]
        self.assertEqual((theta.task, theta.note_key, theta.item.pr_url), ("theta-cut", "theta-cut", None))
        self.assertIn("recommend wait", theta.item.detail)

    # herdr panes

    def test_a_waiting_pane_of_a_firstmate_task_raises_no_item(self):
        agents = herdr_agents(self.primary) + [
            {"agent": "claude", "agent_status": "blocked", "cwd": "/work/beta", "pane_id": "wB:p1"},  # beta-port meta
            {"agent": "claude", "agent_status": "blocked", "cwd": "/work/omega", "pane_id": "wX:p9",
             "tokens": {"fm_task": "omega-ci"}},  # firstmate's own pane token
            {"agent": "claude", "agent_status": "blocked", "cwd": "/work/other", "pane_id": "wY:p1",
             "tokens": {"fm_task": "not-a-task"}},
        ]
        cands, counts = self.build(agents=agents)
        self.assertEqual({r for r in cands if r.startswith("herdr|")}, {"herdr|wC:p3", "herdr|wY:p1"})
        self.assertEqual(counts.herdr_blocked, 4)  # still counted: herdr says they wait

    def test_without_herdr_no_item_names_a_pane(self):
        cands, _ = build_candidates(self.snapshots(), LedgerState(), [], self.now, panes=False)
        self.assertTrue(all(c.pane is None for c in cands))
        by_ref = {c.item.ref: c.item for c in cands}
        self.assertIn("focus", by_ref[decision_ref("primary", "alpha-fix", "merge-alpha-12")].actions)  # the PR
        self.assertNotIn("focus", by_ref[worker_ref("primary", "beta-port")].actions)  # nothing to open

    def test_relayed_second_mate_hold_is_shown_once_from_its_home(self):
        cands, _ = self.build()
        self.assertNotIn(decision_ref("primary", "mate1", "captain-hold-gamma-choice-1"), cands)
        gamma = cands[decision_ref("mate1", "gamma-choice", "gamma-choice")]
        self.assertEqual(gamma.item.home, "mate1")
        self.assertEqual(gamma.item.detail, "Gamma choice: choose the gamma layout.")

    def test_red_pr_keeps_yes_dark(self):
        cands, _ = self.build()
        omega = cands[decision_ref("primary", "omega-ci", "merge-omega-7")].item
        self.assertEqual(omega.checks, "red")  # no captain row, and pr-health reported it failing
        self.assertNotIn("yes", omega.actions)
        self.assertEqual(omega.pr_url, "https://github.com/example/omega/pull/7")
        self.assertIn("pr-health reported failing checks at an unknown commit", omega.detail)
        alpha = cands[decision_ref("primary", "alpha-fix", "merge-alpha-12")].item
        self.assertIn("yes", alpha.actions)

    def test_pr_already_asked_as_decision_is_not_listed_twice(self):
        cands, _ = self.build()
        self.assertNotIn(pr_ref("primary", "https://github.com/example/alpha/pull/12"), cands)
        delta = cands[pr_ref("primary", "https://github.com/example/delta/pull/3")]
        self.assertEqual((delta.item.color, delta.item.checks, delta.item.short_id), ("blue", "green", "delta#3"))
        self.assertEqual(delta.pane, "wD:p1")

    def test_focus_targets(self):
        cands, _ = self.build()
        # A decision focuses firstmate's own pane in that home.
        self.assertEqual(cands[decision_ref("primary", "widget-pricing", "widget-pricing")].pane, "w0:p1")
        # A blocked worker focuses its own pane from state/<id>.meta.
        self.assertEqual(cands[worker_ref("primary", "beta-port")].pane, "wB:p1")
        self.assertEqual(cands["herdr|wC:p3"].pane, "wC:p3")
        self.assertEqual(cands["herdr|wC:p3"].item.actions, ["focus"])
        # The second mate's firstmate has no herdr pane here, so no focus.
        self.assertNotIn("focus", cands[decision_ref("mate1", "gamma-choice", "gamma-choice")].item.actions)

    def test_without_firstmate_pane_a_needs_decision_falls_back_to_the_task_pane(self):
        cands, _ = self.build(agents=[])
        self.assertEqual(cands[decision_ref("primary", "alpha-fix", "merge-alpha-12")].pane, "wA:p2")
        self.assertNotIn("focus", cands[decision_ref("primary", "widget-pricing", "widget-pricing")].item.actions)

    def test_show_me_lights_for_a_pane_a_pr_or_a_report(self):
        # No firstmate pane anywhere, so each item has only what the case gives it.
        (self.primary / "state" / "alpha-fix.meta").write_text("kind=ship\n")
        (self.primary / "state" / "delta-docs.meta").write_text("kind=ship\n")
        report = self.primary / "data" / "widget-pricing" / "report.md"
        report.parent.mkdir(parents=True)
        report.write_text("# Widget pricing\n")
        cands, _ = self.build(agents=[])
        actions = lambda ref: cands[ref].item.actions
        # Pane only: the blocked worker has its own pane and no PR or report.
        self.assertIn("focus", actions(worker_ref("primary", "beta-port")))
        # PR only: no pane, but a PR to open.
        self.assertIsNone(cands[decision_ref("primary", "alpha-fix", "merge-alpha-12")].pane)
        self.assertIn("focus", actions(decision_ref("primary", "alpha-fix", "merge-alpha-12")))
        self.assertIn("focus", actions(pr_ref("primary", "https://github.com/example/delta/pull/3")))
        # Report only: no pane or PR, but data/<task>/report.md in its home.
        self.assertIsNone(cands[decision_ref("primary", "widget-pricing", "widget-pricing")].pane)
        self.assertIn("focus", actions(decision_ref("primary", "widget-pricing", "widget-pricing")))
        # Nothing: no pane, PR, or report.
        self.assertNotIn("focus", actions(decision_ref("mate1", "gamma-choice", "gamma-choice")))

    def test_show_me_stays_dark_without_anything_to_open(self):
        (self.primary / "state" / "beta-port.meta").write_text("kind=ship\n")
        # A report outside the task's data dir, or a directory named report.md, does not count.
        (self.primary / "beta-port").mkdir()
        (self.primary / "beta-port" / "report.md").write_text("x")
        (self.primary / "data" / "widget-pricing" / "report.md").mkdir(parents=True)
        cands, _ = self.build(agents=[])
        self.assertNotIn("focus", cands[worker_ref("primary", "beta-port")].item.actions)
        self.assertNotIn("focus", cands[decision_ref("primary", "widget-pricing", "widget-pricing")].item.actions)

    def test_idle_is_never_counted_as_done_or_blocked(self):
        _, counts = self.build(agents=[{"agent_status": "idle", "pane_id": "x"}])
        self.assertEqual((counts.herdr_working, counts.herdr_blocked), (0, 0))

    def test_ages(self):
        cands, _ = self.build()
        self.assertAlmostEqual(cands[decision_ref("primary", "widget-pricing", "widget-pricing")].origin_epoch,
                               self.now - 3 * 86400)
        self.assertEqual(cands[decision_ref("primary", "alpha-fix", "merge-alpha-12")].origin_epoch, 1700000000)


class LedgerStateTest(unittest.TestCase):
    def test_status_events_make_stand_ins_and_edges(self):
        ledger = LedgerState()
        now = 10_000
        edges = ledger.apply("primary", [
            {"v": 1, "ts": now - 1, "event": "task.status", "task": "zeta", "state": "needs-decision",
             "key": "merge-zeta-1", "text": " PR https://github.com/example/zeta/pull/1 green"},
            {"v": 1, "ts": now - 1, "event": "task.status", "task": "eta", "state": "failed", "key": None, "text": " boom"},
            {"v": 1, "ts": now - 1, "event": "task.pr_ready", "task": "theta", "pr": "https://github.com/example/theta/pull/2"},
            {"v": 1, "ts": now - 5000, "event": "task.status", "task": "old", "state": "blocked", "key": None, "text": "x"},
            {"v": 1, "ts": now - 1, "event": "task.status", "task": "../evil", "state": "blocked", "key": None, "text": "x"},
        ], now)
        self.assertEqual(edges, {
            decision_ref("primary", "zeta", "merge-zeta-1"),
            worker_ref("primary", "eta"),
            pr_ref("primary", "https://github.com/example/theta/pull/2"),
        })
        cands, counts = build_candidates([], ledger, [], now)
        by_ref = {c.item.ref: c.item for c in cands}
        self.assertEqual(by_ref[decision_ref("primary", "zeta", "merge-zeta-1")].pr_url,
                         "https://github.com/example/zeta/pull/1")
        self.assertEqual(counts.decisions, 1)
        self.assertEqual(counts.prs_ready, 2)

    def test_stand_ins_light_show_me_for_a_board_or_pr_in_their_text(self):
        ledger = LedgerState()
        now = 10_000
        ledger.apply("primary", [
            {"v": 1, "ts": now - 1, "event": "task.status", "task": "zeta", "state": "blocked", "key": None,
             "text": "review http://127.0.0.1:4387/session/0123456789abcdef"},
            {"v": 1, "ts": now - 1, "event": "task.status", "task": "eta", "state": "failed", "key": None, "text": "boom"},
            {"v": 1, "ts": now - 1, "event": "task.pr_ready", "task": "theta", "pr": "https://github.com/example/theta/pull/2"},
        ], now)
        cands, _ = build_candidates([], ledger, [], now)
        by_ref = {c.item.ref: c.item for c in cands}
        self.assertIn("focus", by_ref[worker_ref("primary", "zeta")].actions)
        self.assertNotIn("focus", by_ref[worker_ref("primary", "eta")].actions)
        self.assertIn("focus", by_ref[pr_ref("primary", "https://github.com/example/theta/pull/2")].actions)

    def test_resolution_merge_and_expiry(self):
        ledger = LedgerState()
        now = time.time()
        ledger.apply("primary", [
            {"v": 1, "ts": now, "event": "task.status", "task": "zeta", "state": "needs-decision", "key": "k", "text": "q"},
            {"v": 1, "ts": now, "event": "task.status", "task": "eta", "state": "blocked", "key": None, "text": "b"},
            {"v": 1, "ts": now, "event": "task.pr_ready", "task": "theta", "pr": "https://github.com/e/t/pull/2"},
        ], now)
        ledger.apply("primary", [
            {"v": 1, "ts": now, "event": "task.status", "task": "zeta", "state": "resolved", "key": "k", "text": ""},
            {"v": 1, "ts": now, "event": "task.status", "task": "eta", "state": "working", "key": None, "text": ""},
            {"v": 1, "ts": now, "event": "task.merged", "task": "theta", "via": "pr", "pr": "https://github.com/e/t/pull/2"},
        ], now)
        self.assertEqual(ledger.provisional, {})
        _, counts = build_candidates([], ledger, [], now)
        self.assertEqual(counts.landed_today, 0)  # no summary snapshot for the home, so nothing is counted

        ledger.apply("primary", [
            {"v": 1, "ts": now, "event": "task.status", "task": "iota", "state": "blocked", "key": None, "text": "b"},
        ], now)
        ledger.expire(now + 1, {"primary": now - 10})  # summary older than the event: keep
        self.assertIn(worker_ref("primary", "iota"), ledger.provisional)
        ledger.expire(now + 1, {"primary": now + 1})  # summary published after: it is the record now
        self.assertEqual(ledger.provisional, {})


    def test_a_stand_in_the_summary_still_shows_as_a_problem_is_kept(self):
        ledger = LedgerState()
        now = 10_000
        ledger.apply("primary", [
            {"v": 1, "ts": now - 1, "event": "task.status", "task": "iota", "state": "blocked", "key": None, "text": "b"},
            {"v": 1, "ts": now - 1, "event": "task.status", "task": "kappa", "state": "failed", "key": None, "text": "f"},
        ], now)
        keep = frozenset({worker_ref("primary", "iota")})
        ledger.expire(now + 1, {"primary": now + 1}, keep)  # a newer summary: kappa is the summary's now
        self.assertEqual(set(ledger.provisional), {worker_ref("primary", "iota")})
        ledger.expire(now + 2000, {"primary": now + 1}, keep)  # nor does the stand-in time out
        self.assertEqual(set(ledger.provisional), {worker_ref("primary", "iota")})
        ledger.expire(now + 2001, {"primary": now + 1})  # once the summary stops showing it, it goes
        self.assertEqual(ledger.provisional, {})


class PrChecksTest(unittest.TestCase):
    health = {"prs": {"u": {"checks": [{"head": "h1", "name": "ci"}], "conflicts": ["h2"]}}}
    now = 1794355200  # 2026-11-11T00:00:00Z

    def row(self, head, checked_at="2026-11-10T23:55:00Z", hold=None):
        return {"url": "u", "kind": "pr", "head": head, "reason": "checks green; merge approval needed",
                "hold": hold, "checked_at": checked_at}

    def test_a_fresh_captain_row_without_a_hold_is_green(self):
        self.assertEqual(pr_checks("u", self.health, self.row("h1"), self.now), "green")
        self.assertEqual(pr_checks("other", None, self.row("h9"), self.now), "green")

    def test_pr_health_counts_only_for_the_commit_it_names(self):
        stale = "2026-11-10T23:40:00Z"  # 20 minutes old: past firstmate's 15 minute bound
        self.assertEqual(pr_checks("u", self.health, self.row("h1", stale), self.now), "red")
        self.assertEqual(pr_checks("u", self.health, self.row("h2", stale), self.now), "red")  # a conflict
        self.assertEqual(pr_checks("u", self.health, self.row("h3", stale), self.now), "unknown")
        self.assertEqual(pr_verdict("u", self.health, self.row("h1", stale), self.now),
                         ("red", "pr-health reported failing checks at this commit"))

    def test_a_held_row_is_no_verdict(self):
        held = self.row("h3", hold="some-task")
        self.assertEqual(pr_checks("u", self.health, held, self.now), "unknown")
        self.assertEqual(pr_checks("u", self.health, self.row("h1", hold="some-task"), self.now), "red")

    def test_without_a_captain_row_any_report_counts(self):
        self.assertEqual(pr_verdict("u", self.health, None, self.now),
                         ("red", "pr-health reported conflicts at an unknown commit"))
        self.assertEqual(pr_checks("other", self.health, None, self.now), "unknown")

    def test_a_row_checked_in_the_future_or_unparsable_is_not_fresh(self):
        self.assertEqual(pr_checks("x", None, self.row("h1", "2026-11-11T00:10:00Z"), self.now), "unknown")
        self.assertEqual(pr_checks("x", None, self.row("h1", "yesterday"), self.now), "unknown")


if __name__ == "__main__":
    unittest.main()
