import json
import tempfile
import time
import unittest
from pathlib import Path

from helm.bridge.items import (
    HomeSnapshot, LedgerState, build_candidates, decision_ref, pr_checks, pr_ref, worker_ref,
)
from helm.bridge.sources import discover_homes
from tests.helpers import herdr_agents, make_homes


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

    def test_items_and_counts_from_fixture_homes(self):
        cands, counts = self.build()
        self.assertEqual(set(cands), {
            decision_ref("primary", "widget-pricing", "widget-pricing"),
            decision_ref("primary", "alpha-fix", "merge-alpha-12"),
            decision_ref("primary", "beta-port", "merge-beta-7"),
            decision_ref("mate1", "gamma-choice", "gamma-choice"),
            pr_ref("primary", "https://github.com/example/delta/pull/3"),
            worker_ref("primary", "beta-port"),
            "herdr|wC:p3",
        })
        self.assertEqual(counts.decisions, 4)
        self.assertEqual(counts.working, 2)
        self.assertEqual(counts.queued, 5)
        self.assertEqual(counts.landed_today, 1)
        self.assertEqual(counts.prs_ready, 3)  # delta pull/3 plus the two merge asks
        self.assertEqual((counts.herdr_working, counts.herdr_blocked), (1, 1))

    def test_projects_come_from_children_meta_and_pr_urls(self):
        (self.primary / "state" / "widget-pricing.meta").write_text("kind=ship\nproject=/work/projects/widget-shop\n")
        (self.primary / "state" / "mate1.meta").write_text("kind=secondmate\nproject=/work/firstmate\n")
        cands, _ = self.build()
        projects = {ref: c.item.project for ref, c in cands.items()}
        self.assertEqual(projects, {
            decision_ref("primary", "widget-pricing", "widget-pricing"): "widget-shop",  # meta project path
            decision_ref("primary", "alpha-fix", "merge-alpha-12"): "alpha",  # the active child's repo
            decision_ref("primary", "beta-port", "merge-beta-7"): "beta",
            decision_ref("mate1", "gamma-choice", "gamma-choice"): None,  # nothing names one
            pr_ref("primary", "https://github.com/example/delta/pull/3"): "delta",
            worker_ref("primary", "beta-port"): "beta",
            "herdr|wC:p3": None,
        })

    def test_project_falls_back_to_the_pr_repo(self):
        summary_path = self.primary / "state" / "home-summary.json"
        summary = json.loads(summary_path.read_text())
        summary["active_children"] = []
        summary["decisions_open"].append({"id": "mate1", "key": "merge-omega-9", "verb": "needs-decision",
                                          "summary": "https://github.com/example/omega/pull/9 green; merge?"})
        summary_path.write_text(json.dumps(summary))
        (self.primary / "state" / "mate1.meta").write_text("kind=secondmate\nproject=/work/firstmate\n")
        cands, _ = self.build()
        self.assertEqual(cands[decision_ref("primary", "alpha-fix", "merge-alpha-12")].item.project, "alpha")
        self.assertEqual(cands[decision_ref("primary", "mate1", "merge-omega-9")].item.project, "omega")

    def test_relayed_second_mate_hold_is_shown_once_from_its_home(self):
        cands, _ = self.build()
        self.assertNotIn(decision_ref("primary", "mate1", "captain-hold-gamma-choice-1"), cands)
        gamma = cands[decision_ref("mate1", "gamma-choice", "gamma-choice")]
        self.assertEqual(gamma.item.home, "mate1")
        self.assertEqual(gamma.item.detail, "Choose the gamma layout.")

    def test_red_pr_keeps_yes_dark(self):
        cands, _ = self.build()
        beta = cands[decision_ref("primary", "beta-port", "merge-beta-7")].item
        self.assertEqual(beta.checks, "red")
        self.assertNotIn("yes", beta.actions)
        self.assertEqual(beta.pr_url, "https://github.com/example/beta/pull/7")
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


class PrChecksTest(unittest.TestCase):
    health = {"prs": {"u": {"checks": [{"head": "h1", "name": "ci"}], "conflicts": ["h2"]}}}

    def test_failures_are_red_only_for_the_known_head(self):
        self.assertEqual(pr_checks("u", self.health), "red")
        self.assertEqual(pr_checks("u", self.health, head="h1"), "red")
        self.assertEqual(pr_checks("u", self.health, head="h2"), "red")
        self.assertEqual(pr_checks("u", self.health, head="h3", reason="checks green; merge approval needed"), "green")
        self.assertEqual(pr_checks("other", self.health), "unknown")


if __name__ == "__main__":
    unittest.main()
