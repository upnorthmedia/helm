"""Contract tests: the bridge against real firstmate scripts, not fixtures.

The rest of the suite reads invented or hand-copied firstmate output. These tests
run a real firstmate checkout in a temporary home instead: its summary producer
(`bin/fm-home-summary-refresh.sh`) over a seeded fleet, and its inbox
(`bin/fm-inbox.sh`) under Helm's own executor with writes on. They check the keys
and types Helm reads from each document, then drive the bridge end to end: the
items it builds from the producer's summary, and a held YES through note, replay,
firstmate's read, firstmate's reply, and a bridge restart.

They run only when HELM_FIRSTMATE names a firstmate checkout.
`scripts/test-firstmate-contract.sh` fetches the pinned commit and runs them;
CI runs that script on every pull request, and weekly against firstmate's main.
Nothing here touches a real firstmate home, herdr, or the network: firstmate's
tmux probe sees a stub, and the bridge's other commands answer "not installed".
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from typing import Optional, Sequence

from helm.bridge.bridge import RECEIPTS_POLL_S, Bridge
from helm.bridge.commands import Completed, Runner, check_allowed, command_signature
from helm.bridge.intents import YES_PREFIX, IntentExecutor
from helm.bridge.transports import MemoryTransport
from helm.bridge.usage import UsagePoller
from helm.contract import Key

FIRSTMATE = os.environ.get("HELM_FIRSTMATE", "")
TOOLS = ("bash", "git", "jq")

# Every key Helm reads from a home summary (helm/bridge/items.py, bridge.py, doctor.py), with the
# JSON types it accepts. A missing key or another type is drift: Helm would read nothing there.
SUMMARY_KEYS = {
    "schema": (str,),
    "generated_epoch": (int,),
    "valid": (bool,),
    "reason": (str, type(None)),
    "state": (str,),
    "invalidity": (dict,),
    "counts": (dict,),
    "endpoints": (list,),
    "decisions_open": (list,),
    "holds": (list,),
    "active_children": (list,),
    "queued": (list,),
    "omitted": (list,),
    "landed": (list,),
    "contributions": (dict,),
}
SUMMARY_SCHEMA = "fm-secondmate-home-summary.v1"
ENDPOINT_STATES = {"working", "parked", "done", "blocked", "paused", "failed", "unknown"}
ROW_KEYS = {
    "endpoints": {"id": (str,), "state": (str,)},
    "decisions_open": {"id": (str,), "key": (str,), "verb": (str,), "summary": (str, type(None)),
                       "reason": (str, type(None))},
    "holds": {"id": (str,), "reason": (str, type(None))},
    "active_children": {"id": (str,), "repo": (str, type(None))},
}
READY_SCHEMA = "fm-primary-ready.v1"
RECEIPTS_SCHEMA = "fm-inbox-receipts.v1"
NOTE_KEYS = {"id": (str,), "at": (str,), "request_id": (str, type(None)), "acknowledged": (bool, type(None)),
             "reply": (dict, type(None))}

# What firstmate's tmux probe sees: every recorded window exists and runs claude.
TMUX_STUB = """#!/usr/bin/env bash
case "${1:-}" in
  list-windows) printf '%s\\n' fm-alpha-fix fm-beta-port fm-delta-docs ;;
  display-message)
    case "$*" in
      *pane_current_command*) printf 'claude\\n' ;;
      *pane_tty*) ;;
      *) printf '%%1\\n' ;;
    esac ;;
esac
exit 0
"""

BACKLOG = """## In flight
- [ ] alpha-fix - Fix alpha (repo: alpha) (kind: ship) (since 2026-11-10)
- [ ] beta-port - Port beta (repo: beta) (kind: ship) (since 2026-11-10)
- [ ] delta-docs - Delta docs (repo: delta) (kind: ship) (since 2026-11-10)

## Queued
- [ ] zeta-later - Later work (repo: zeta) (kind: ship)

## Done
"""


class ContractRunner(Runner):
    """The real runner for fm-inbox.sh; everything else answers as not installed.

    Every argv still passes the bridge's allowlist first, so the test fails if the bridge
    reaches for anything it may not run.
    """

    def run(self, argv: Sequence[str], env: Optional[dict] = None, timeout: float = 10.0) -> Completed:
        signature = command_signature(argv)
        if signature is not None and signature[0] == "fm-inbox.sh":
            return super().run(argv, env=env, timeout=timeout)
        check_allowed(argv, self.allow_writes)
        return Completed(127, "", "%s: not installed in the contract test" % argv[0])


def check_keys(test: unittest.TestCase, where: str, obj: dict, keys: dict) -> None:
    for key, types in keys.items():
        test.assertIn(key, obj, "%s has no %r" % (where, key))
        # bool is an int in Python; a key Helm reads as an int must not be a bool.
        ok = isinstance(obj[key], types) and not (int in types and bool not in types and isinstance(obj[key], bool))
        test.assertTrue(ok, "%s[%r] is %r, Helm reads %s" % (where, key, obj[key], [t.__name__ for t in types]))


@unittest.skipUnless(FIRSTMATE, "set HELM_FIRSTMATE to a firstmate checkout (scripts/test-firstmate-contract.sh)")
class FirstmateContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.checkout = Path(FIRSTMATE).resolve()
        # Asked for, so a missing piece fails rather than skips.
        if not (cls.checkout / "bin" / "fm-inbox.sh").is_file():
            raise AssertionError("HELM_FIRSTMATE=%s is not a firstmate checkout" % FIRSTMATE)
        missing = [tool for tool in TOOLS if shutil.which(tool) is None]
        if missing:
            raise AssertionError("the contract tests need %s on PATH" % ", ".join(missing))
        # A firstmate worker exports FM_HOME and friends; none may reach the lab home's scripts.
        cls._saved_env = {k: v for k, v in os.environ.items() if k.startswith("FM_")}
        for key in cls._saved_env:
            del os.environ[key]

    @classmethod
    def tearDownClass(cls) -> None:
        os.environ.update(cls._saved_env)

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name).resolve()
        self.home = self.tmp / "home"
        for sub in ("state", "data", "config", "projects"):
            (self.home / sub).mkdir(parents=True)
        (self.home / "bin").symlink_to(self.checkout / "bin")
        self.now = time.time()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # The real firstmate, run directly (as firstmate itself would).

    def firstmate(self, *argv: str, env: Optional[dict] = None) -> subprocess.CompletedProcess:
        full = dict(os.environ, FM_HOME=str(self.home), **(env or {}))
        done = subprocess.run([str(self.home / "bin" / argv[0]), *argv[1:]], capture_output=True, text=True,
                              env=full, timeout=120, stdin=subprocess.DEVNULL)
        self.assertEqual(done.returncode, 0, "%s failed (%d):\n%s%s" % (" ".join(argv), done.returncode,
                                                                       done.stdout, done.stderr))
        return done

    def seed_fleet(self) -> dict:
        """A primary home with a merge ask (alpha-fix), a blocked worker (beta-port), a busy one
        (delta-docs), and queued work, then the summary firstmate's own producer publishes for it."""
        stubs = self.tmp / "stubs"
        stubs.mkdir()
        (stubs / "tmux").write_text(TMUX_STUB)
        (stubs / "tmux").chmod(0o755)
        (self.home / "data" / "backlog.md").write_text(BACKLOG)
        state = self.home / "state"
        now = int(self.now)
        for task in ("alpha-fix", "beta-port", "delta-docs"):
            tree = self.home / "projects" / task
            tree.mkdir()
            git = ["git", "-C", str(tree), "-c", "user.name=helm", "-c", "user.email=helm@localhost"]
            for args in (["init", "-q"], ["commit", "-q", "--allow-empty", "-m", "init"], ["checkout", "-q", "-b", "fm/" + task]):
                subprocess.run(git + args, check=True, capture_output=True)
            (state / ("%s.meta" % task)).write_text(
                "window=fmtest:fm-%s\nworktree=%s\nproject=%s\nkind=ship\nharness=claude\nmode=direct-PR\n"
                "spawn_gen=fm.%s0001\n" % (task, tree, task.split("-")[0], task.split("-")[0]))
            gen = self.firstmate("fm-busy-event.sh", "arm", str(state), task).stdout.strip()
            self.firstmate("fm-busy-event.sh", "apply", str(state), task, "busy" if task == "delta-docs" else "idle",
                           "--gen", gen, "--source", "claude-hook", "--event", "stop")
        (state / "alpha-fix.status").write_text(
            "working [at=%d]: setup done\n"
            "needs-decision [at=%d] [key=merge-alpha-12]: PR https://github.com/example/alpha/pull/12 checks green\n"
            % (now - 600, now - 300))
        (state / "beta-port.status").write_text("blocked [at=%d]: waiting on credentials\n" % (now - 200))
        (state / "delta-docs.status").write_text("working [at=%d]: on it\n" % (now - 100))
        self.firstmate("fm-home-summary-refresh.sh",
                       env={"PATH": "%s%s%s" % (stubs, os.pathsep, os.environ.get("PATH", "")),
                            "FM_CREW_STATE_NO_FORGE": "1"})
        return json.loads((state / "home-summary.json").read_text())

    def bridge(self, live: bool = True) -> Bridge:
        runner = ContractRunner(allow_writes=live)
        executor = IntentExecutor(self.home, runner, dry_run=not live, clock=lambda: self.now,
                                  cache_dir=self.tmp / "cache")
        bridge = Bridge(MemoryTransport(), self.home, runner, executor, clock=lambda: self.now,
                        usage=UsagePoller(runner, background=False))
        if live:
            bridge.start()  # takes back this bridge's notes from before a restart
        return bridge

    def tick(self, bridge: Bridge, seconds: float = 0.0):
        self.now += seconds
        bridge.tick(self.now)
        return bridge.build_model(self.now)

    def press(self, bridge: Bridge, key: str, ref: str) -> None:
        for phase in ("down", "held", "up"):
            bridge.handle(Key(key, phase, ref), self.now)

    def notes(self) -> list[dict]:
        receipts = json.loads(self.firstmate("fm-inbox.sh", "receipts", "--all-pending", "--all-handled").stdout)
        return (receipts.get("pending") or []) + (receipts.get("handled") or [])

    # Schemas.

    def test_summary_carries_every_key_helm_reads(self):
        summary = self.seed_fleet()
        check_keys(self, "summary", summary, SUMMARY_KEYS)
        self.assertEqual(summary["schema"], SUMMARY_SCHEMA)
        self.assertIsInstance(summary["counts"].get("queued"), int)
        self.assertIn("kind", summary["invalidity"])
        self.assertIsInstance(summary["contributions"].get("captain"), list)
        for section, keys in ROW_KEYS.items():
            self.assertTrue(summary[section], "the seeded fleet should fill %s" % section)
            for i, row in enumerate(summary[section]):
                check_keys(self, "%s[%d]" % (section, i), row, keys)
        self.assertLessEqual({row["state"] for row in summary["endpoints"]}, ENDPOINT_STATES)
        for row in summary["omitted"]:
            check_keys(self, "omitted row", row, {"surface": (str,), "count": (int,)})

    def test_summary_is_what_the_seeded_fleet_says(self):
        """The producer's own reading of the fleet, which the bridge's items depend on."""
        summary = self.seed_fleet()
        self.assertIs(summary["valid"], True, summary.get("reason"))
        states = {row["id"]: row["state"] for row in summary["endpoints"]}
        self.assertEqual(states, {"alpha-fix": "parked", "beta-port": "blocked", "delta-docs": "working"})
        self.assertEqual([row["id"] for row in summary["active_children"]], ["delta-docs"])
        self.assertIn(("alpha-fix", "merge-alpha-12"), {(r["id"], r["key"]) for r in summary["decisions_open"]})
        self.assertEqual(summary["counts"]["queued"], 1)

    def test_ready_and_receipts_carry_what_helm_reads(self):
        ready = json.loads(self.firstmate("fm-inbox.sh", "ready").stdout)
        self.assertEqual(ready.get("schema"), READY_SCHEMA)
        self.assertIn(ready.get("can_receive"), (True, False))
        self.assertIsInstance((ready.get("posture") or {}).get("state"), str)
        for section in ("lock", "wake_consumer"):
            self.assertIsInstance((ready.get(section) or {}).get("state"), str)
        self.firstmate("fm-inbox.sh", "note", "--request-id", "helm-yes-contract", "--json", "--", "a note")
        receipts = json.loads(self.firstmate("fm-inbox.sh", "receipts").stdout)
        self.assertEqual(receipts.get("schema"), RECEIPTS_SCHEMA)
        check_keys(self, "receipts", receipts, {"pending": (list,), "handled": (list,), "replies": (list,),
                                                "reply_cursor": (str,)})
        [note] = receipts["pending"]
        check_keys(self, "receipts note", note, NOTE_KEYS)
        self.assertEqual(note["request_id"], "helm-yes-contract")

    # The bridge, end to end.

    def test_bridge_items_from_the_real_summary(self):
        self.seed_fleet()
        model = self.tick(self.bridge(live=False))
        refs = {item.ref: item for item in model.items}
        decision = refs.get("decision|primary|alpha-fix|merge-alpha-12")
        self.assertIsNotNone(decision, sorted(refs))
        self.assertIn("yes", decision.actions)
        worker = refs.get("worker|primary|beta-port")
        self.assertIsNotNone(worker, sorted(refs))
        self.assertEqual(worker.kind, "worker_problem")
        self.assertIn("waiting on credentials", worker.detail)
        self.assertEqual(model.counts.working, 1)
        self.assertEqual(model.counts.queued, 1)
        # The lab home has no firstmate session holding its lock, and `ready` says so.
        self.assertIs(model.link.firstmate_can_receive, False)
        self.assertEqual(model.link.stale_reason, "firstmate cannot receive")

    def test_held_yes_through_note_replay_read_reply_and_restart(self):
        """Lab 6.2 of the alignment plan, as a test: the inbox works as the executor assumes."""
        self.seed_fleet()
        bridge = self.bridge()
        self.tick(bridge)
        ref = "decision|primary|alpha-fix|merge-alpha-12"

        self.press(bridge, "yes", ref)
        result = self.tick(bridge).result
        self.assertEqual(result.state, "queued", result.text)
        self.assertTrue(result.text.startswith("queued YES"), result.text)
        rid = result.request_id
        self.assertTrue(rid.startswith("helm-yes-primary-alpha-fix-merge-alpha-12-"), rid)
        [note] = self.notes()
        self.assertEqual(note["request_id"], rid)
        self.assertTrue(note["body"].startswith(YES_PREFIX + " on `alpha-fix` / `merge-alpha-12`"), note["body"])
        self.assertEqual(next(i.pending for i in self.tick(bridge).items if i.ref == ref), "yes")

        # A second press is a replay of the same note, never a second one.
        self.press(bridge, "yes", ref)
        result = self.tick(bridge).result
        self.assertEqual((result.request_id, result.state), (rid, "queued"))
        self.assertTrue(result.text.startswith("already queued YES"), result.text)
        self.assertEqual(len(self.notes()), 1)

        # Firstmate reads it: the deck says seen.
        self.firstmate("fm-inbox.sh", "drain", "--ack", note["id"])
        result = self.tick(bridge, RECEIPTS_POLL_S).result
        self.assertEqual((result.state, result.seen), ("queued", True), result)

        # Firstmate replies: the deck shows the reply, and the item has nothing pending.
        self.firstmate("fm-inbox.sh", "reply", "--json", note["id"], "Contract reply: nothing was merged.")
        model = self.tick(bridge, RECEIPTS_POLL_S)
        self.assertEqual((model.result.request_id, model.result.state), (rid, "replied"))
        self.assertEqual(model.result.text, "Contract reply: nothing was merged.")
        self.assertIsNone(next(i.pending for i in model.items if i.ref == ref))

    def test_a_reply_after_a_restart_still_reaches_the_deck(self):
        self.seed_fleet()
        bridge = self.bridge()
        self.tick(bridge)
        ref = "decision|primary|alpha-fix|merge-alpha-12"
        self.press(bridge, "later", ref)
        rid = self.tick(bridge).result.request_id
        [note] = self.notes()
        self.assertIn("defer `alpha-fix` / `merge-alpha-12` until ", note["body"])

        # The bridge restarts (launchd restarts it on any exit) and takes its note back.
        restarted = self.bridge()
        self.assertIsNone(restarted.result)  # no reply came while it was down
        self.assertEqual(set(restarted.executor.pending), {rid})
        self.tick(restarted)
        self.firstmate("fm-inbox.sh", "reply", "--json", note["id"], "Deferred.")
        result = self.tick(restarted, RECEIPTS_POLL_S).result
        self.assertEqual((result.request_id, result.state, result.text), (rid, "replied", "Deferred."))


if __name__ == "__main__":
    unittest.main()
