"""The bridge main loop: read, build the Model, send it, handle device Events."""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, replace
from pathlib import Path
from typing import Optional

from helm.contract import (Context, Counts, Hello, Key, Knob, KnobPress, Link, Model, Result, Resync, Seen, Select,
                           Transport)
from helm.bridge.attention import Attention
from helm.bridge.context import context_gauge
from helm.bridge.intents import IntentExecutor
from helm.bridge.items import (Candidate, HomeSnapshot, LedgerState, agent_title, build_candidates, finalize_items,
                               summary_invalid, worker_problems)
from helm.bridge.lock import LockWatch
from helm.bridge.usage import UsagePoller
from helm.bridge.sources import (
    HomeRef,
    JsonFile,
    LedgerTail,
    discover_homes,
    parse_herdr_agents,
    parse_ready,
)

log = logging.getLogger(__name__)

SUMMARY_POLL_S = 2.0
READY_POLL_S = 15.0
HERDR_POLL_S = 3.0
RECEIPTS_POLL_S = 5.0
RESEND_S = 2.0
RESULT_LINGER_S = 120.0
HOMES_REFRESH_S = 60.0
RECOVERED_MAX = 5  # replies found at start beyond the one shown, kept to show next
# Firstmate postures (fm-inbox.sh ready). Away: the captain is gone, so the deck
# mutes chimes and locks YES / LATER / HOLD; SHOW ME still works. Quiet: firstmate
# treats a quiet captain as present and acts on their word at once, so the deck only
# mutes chimes. A captain inbox note still wakes firstmate in quiet mode.
AWAY_POSTURES = {"away"}
MUTED_POSTURES = {"away", "quiet"}
ACTING_KEYS = {"yes", "later", "hold"}
# `herdr agent list` exited 127: herdr is not installed (firstmate's default backend is tmux).
HERDR_MISSING_RC = 127


class Every:
    def __init__(self, interval: float):
        self.interval = interval
        self.next_at = 0.0  # due immediately

    def due(self, now: float) -> bool:
        if now >= self.next_at:
            self.next_at = now + self.interval
            return True
        return False


class HomeReaders:
    def __init__(self, home: HomeRef):
        self.home = home
        self.summary = JsonFile(home.path / "state" / "home-summary.json")
        self.pr_health = JsonFile(home.path / "state" / "pr-health.json")
        self.ledger = LedgerTail(home.path / "state" / "fleet-ledger.jsonl")


class Bridge:
    def __init__(self, transport: Transport, primary_home: Path, runner, executor: IntentExecutor, clock=time.time,
                 usage: Optional[UsagePoller] = None, lock: Optional[LockWatch] = None):
        self.transport = transport
        self.primary_home = primary_home
        self.runner = runner
        self.executor = executor
        self.clock = clock
        self.usage = usage or UsagePoller(runner)
        self.lock = lock or LockWatch(runner)
        self.attention = Attention()
        self.ledger = LedgerState()
        self.readers: dict[str, HomeReaders] = {}
        self.ready: Optional[dict] = None
        self.ready_error: Optional[str] = "not checked yet"
        self.agents: list[dict] = []
        self.herdr_error: Optional[str] = None
        self.herdr_installed: Optional[bool] = None  # unknown until the first `herdr agent list`
        self.candidates: dict[str, Candidate] = {}
        self.counts = Counts()
        self.result: Optional[Result] = None
        self.result_at = 0.0
        self._recovered: list[Result] = []  # replies from while the bridge was down, newest first
        # PR heads as of the last model sent, and as of each YES hold's start: YES is bound to these.
        self._shown_heads: dict[str, Optional[str]] = {}
        self._hold_heads: dict[str, Optional[str]] = {}
        self.seq = 0
        self.hello: Optional[Hello] = None
        self._last_sent: Optional[dict] = None
        self._last_sent_at = 0.0
        self._summary_tick = Every(SUMMARY_POLL_S)
        self._ready_tick = Every(READY_POLL_S)
        self._herdr_tick = Every(HERDR_POLL_S)
        self._receipts_tick = Every(RECEIPTS_POLL_S)
        self._homes_tick = Every(HOMES_REFRESH_S)
        self._dirty = True

    # Reading.

    def _refresh_homes(self) -> None:
        homes = discover_homes(self.primary_home)
        labels = {h.label for h in homes}
        for home in homes:
            if home.label not in self.readers or self.readers[home.label].home.path != home.path:
                self.readers[home.label] = HomeReaders(home)
                self._dirty = True
        for label in list(self.readers):
            if label not in labels:
                del self.readers[label]
                self._dirty = True

    def poll_sources(self, now: float) -> None:
        if self._homes_tick.due(now):
            self._refresh_homes()
        edges: set[str] = set()
        for label, readers in self.readers.items():
            records = readers.ledger.poll()
            if records:
                edges |= self.ledger.apply(label, records, now)
                self._dirty = True
        if self._summary_tick.due(now):
            for readers in self.readers.values():
                if readers.summary.poll():
                    self._dirty = True
                if readers.pr_health.poll():
                    self._dirty = True
        if self._ready_tick.due(now):
            done = self.runner.run([str(self.primary_home / "bin" / "fm-inbox.sh"), "ready"],
                                   env={"FM_HOME": str(self.primary_home)}, timeout=10)
            ready = parse_ready(done.stdout) if done.returncode == 0 else None
            self.ready, self.ready_error = ready, None if ready else "firstmate readiness unreadable"
            self._dirty = True
        if self._herdr_tick.due(now):
            done = self.runner.run(["herdr", "agent", "list"], timeout=5)
            agents = parse_herdr_agents(done.stdout) if done.returncode == 0 else None
            if done.returncode == HERDR_MISSING_RC:
                # Not a fault: without herdr there are no panes to count or focus.
                self.agents, self.herdr_error, self.herdr_installed = [], None, False
            elif agents is None:
                self.herdr_error, self.herdr_installed = "herdr unavailable", True
            else:
                self.agents, self.herdr_error, self.herdr_installed = agents, None, True
            self._dirty = True
        if self.usage.poll(now):
            self._dirty = True
        if self.lock.poll(now):
            self._dirty = True
        if self.executor.pending and self._receipts_tick.due(now):
            for result in self.executor.check_receipts():
                self._set_result(result, now)
        if edges or self._dirty:
            self._rebuild(now, edges)

    # Building.

    def _posture(self) -> Optional[str]:
        posture = (self.ready.get("posture") or {}).get("state") if self.ready else None
        return posture if isinstance(posture, str) else None

    def away(self) -> bool:
        return self._posture() in AWAY_POSTURES

    def muted(self) -> bool:
        return self._posture() in MUTED_POSTURES

    def _invalid_summaries(self) -> list[str]:
        """'<home> summary invalid: <reason>' for each home whose summary says valid is false."""
        out = []
        for label, readers in self.readers.items():
            reason = summary_invalid(readers.summary.data)
            if reason:
                out.append("%s summary invalid: %s" % (label, reason))
        return out

    def _link(self) -> Link:
        can_receive = self.ready.get("can_receive") if self.ready else None
        posture = self._posture()
        reasons = []
        if self.ready_error:
            reasons.append(self.ready_error)
        elif can_receive is not True:
            reasons.append("firstmate cannot receive")
        for label, readers in self.readers.items():
            if readers.summary.error:
                reasons.append("%s summary %s" % (label, readers.summary.error))
        reasons.extend(self._invalid_summaries())
        if self.herdr_error:
            reasons.append(self.herdr_error)
        return Link(
            bridge_ok=True,
            firstmate_can_receive=can_receive if isinstance(can_receive, bool) else None,
            posture=posture,
            stale_reason="; ".join(reasons) or None,
            away=posture in AWAY_POSTURES,
            mac_locked=self.lock.locked is True,
        )

    def _rebuild(self, now: float, edges: set[str]) -> None:
        snapshots = [HomeSnapshot(r.home, r.summary.data, r.pr_health.data) for r in self.readers.values()]
        epochs = {
            r.home.label: r.summary.data.get("generated_epoch")
            for r in self.readers.values()
            if isinstance(r.summary.data, dict) and isinstance(r.summary.data.get("generated_epoch"), (int, float))
        }
        problems = worker_problems(snapshots)
        self.ledger.expire(now, epochs, keep=frozenset(problems))
        candidates, self.counts = build_candidates(snapshots, self.ledger, self.agents, now,
                                                   panes=self.herdr_installed is not False)
        # A stuck firstmate task lights at once and chimes only if still stuck later:
        # from its ledger event's time when the fleet ledger reported it, else from now.
        deferred = {c.item.ref: getattr(self.ledger.provisional.get(c.item.ref), "ts", None)
                    for c in candidates if c.item.kind == "worker_problem" and not c.informational}
        self.attention.observe([c.item.ref for c in candidates if not c.informational], now, edges, deferred)
        self.candidates = {c.item.ref: c for c in candidates}
        self._dirty = False

    def build_model(self, now: float) -> Model:
        if self.result and self.result.state != "queued" and now - self.result_at > RESULT_LINGER_S:
            self.result = self._recovered.pop(0) if self._recovered else None
            self.result_at = now
        link = self._link()
        items = finalize_items(list(self.candidates.values()), self.attention, now)
        attention = self.attention.state(link.firstmate_can_receive is True)
        if attention == "calm" and self._invalid_summaries():
            # Never calm on a summary firstmate itself marks invalid; link.stale_reason says why.
            attention = "unknown"
        if link.mac_locked:
            # Nothing acts on a locked Mac, SHOW ME included, so even an older deck keeps every key dark.
            items = [replace(item, actions=[]) for item in items]
        elif link.away:
            # Follow away mode: only SHOW ME stays, so even an older deck keeps the keys dark.
            items = [replace(item, actions=[a for a in item.actions if a not in ACTING_KEYS]) for item in items]
        return Model(
            seq=self.seq,
            link=link,
            attention=attention,
            unseen=self.attention.unseen_count,
            counts=self.counts,
            items=items,
            result=self.result,
            chime=False,
            usage=self.usage.usage(now),
            context=Context() if self.herdr_error or self.herdr_installed is False
            else context_gauge(self.agents, agent_title),
        )

    # Sending.

    def tick(self, now: Optional[float] = None) -> Optional[Model]:
        """Poll what is due, and send the Model when it changed or 2 s have passed. Returns what was sent."""
        now = self.clock() if now is None else now
        self.poll_sources(now)
        self.attention.fire_due(now)  # a deferred chime lights its item in this model
        model = self.build_model(now)
        body = asdict(model)
        body.pop("seq")
        for item in body["items"]:
            item.pop("age_s")
        for name in ("five_hour_resets_s", "week_resets_s"):
            body["usage"].pop(name)  # counts down every second, like age_s
        changed = body != self._last_sent
        # Taken even while muted, so a muted chime does not ring on return.
        chime = self.attention.take_chime() and not self.muted()
        if not (changed or chime or now - self._last_sent_at >= RESEND_S):
            return None
        self.seq += 1
        model.seq = self.seq
        model.chime = chime
        self.transport.send_model(model)
        self._last_sent, self._last_sent_at = body, now
        self._shown_heads = {ref: cand.head for ref, cand in self.candidates.items()}
        return model

    # Events.

    def _set_result(self, result: Result, now: float) -> None:
        self.result, self.result_at = result, now

    def handle(self, event, now: Optional[float] = None) -> None:
        now = self.clock() if now is None else now
        if isinstance(event, Hello):
            self.hello = event
            log.info("device hello: fw=%s caps=%s", event.fw, ",".join(event.caps))
            self._last_sent = None  # send the full model right away
            return
        if isinstance(event, Resync):
            self._last_sent = None  # the device lost a model frame; not a touch
            return
        # Any touch on the deck marks new items as seen (D2).
        self.attention.mark_all_seen()
        if isinstance(event, Key):
            self._handle_key(event, now)
        elif isinstance(event, (Select, Knob, KnobPress, Seen)):
            # Scrolling, selecting, opening detail, and mute are the device's own
            # business. A key names its own item, so a select is never acted on.
            pass

    def _mac_locked_now(self, now: float) -> bool:
        """Read the lock state again before acting, so a lock since the last poll still refuses."""
        if self.lock.read(now):
            self._dirty = True
        if self.lock.locked is True:
            self._set_result(Result("none", "failed", "keys locked: the Mac is locked"), now)
            return True
        return False

    def _key_item(self, event: Key, request_id: str, now: float) -> Optional[Candidate]:
        """The live item the key names, or None after refusing.

        Only the ref in the key counts: the last select may have been lost, and
        acting on it would answer an item the deck was not showing.
        """
        if event.ref is None:
            # A deck that predates Key.ref; a current one sends no key without an item.
            self._set_result(Result(request_id, "failed", "key named no item: update the deck"), now)
            return None
        cand = self.candidates.get(event.ref)
        if cand is None:
            self._set_result(Result(request_id, "failed", "that item is gone"), now)
        return cand

    def _handle_key(self, event: Key, now: float) -> None:
        if event.key == "focus":
            if event.phase != "up" or self._mac_locked_now(now):
                return
            cand = self._key_item(event, "focus", now)
            if cand is not None:
                self._show(cand, now)
            return
        if event.key == "yes" and event.ref is not None:
            if event.phase == "down":
                self._hold_heads[event.ref] = self._shown_heads.get(event.ref)
            elif event.phase == "up":
                self._hold_heads.pop(event.ref, None)
        if event.phase != "held" or self._mac_locked_now(now):
            return
        if self.away():
            self._set_result(Result("none", "failed", "keys locked: firstmate is %s" % self._posture()), now)
            return
        cand = self._key_item(event, "none", now)
        if cand is None:
            return
        if event.key not in cand.item.actions or cand.item.kind == "herdr_blocked":
            self._set_result(Result("none", "failed", "%s does not apply to %s" % (event.key.upper(), cand.item.short_id)), now)
            return
        if event.key == "yes" and not self._head_unchanged(event.ref, cand):
            self._set_result(Result("none", "failed", "PR changed, look again: %s" % cand.item.short_id), now)
            return
        self._set_result(self.executor.note(event.key, cand), now)

    def _head_unchanged(self, ref: str, cand: Candidate) -> bool:
        """True when the item's PR head is the one the deck had when the hold began (or, with no
        `down` seen, in the last model sent), so a refresh during a hold never pins YES to a commit
        the captain did not see."""
        shown = self._hold_heads.pop(ref) if ref in self._hold_heads else self._shown_heads.get(ref)
        return cand.head == shown

    def _show(self, cand: Candidate, now: float) -> None:
        """SHOW ME: focus the pane first (it is instant), then open the board, report, or PR if there is one."""
        focused = self.executor.focus(cand.pane) if cand.pane else None
        target = self.executor.show_target(cand)
        opened = self.executor.open(target, cand) if target else None
        name, dry = cand.item.short_id, self.executor.dry_run
        if target is None and focused is None:
            self._set_result(Result("focus", "failed", "nothing to show"), now)
        elif target is None:
            text = ("dry run: focus %s logged" if dry else "showing %s") % name
            self._set_result(Result("focus", "replied" if focused else "failed", text if focused else "focus failed"), now)
        elif opened:
            text = ("dry run: %s for %s logged" if dry else "opening %s for %s") % (target.what, name)
            if focused is False:
                text += "; focus failed"
            self._set_result(Result("focus", "replied", text), now)
        else:
            text = "%s for %s did not open" % (target.what, name)
            if focused:
                text += "; pane focused"
            self._set_result(Result("focus", "failed", text), now)

    # Running.

    def step(self, timeout_s: float = 0.5) -> None:
        for event in self.transport.poll_events(timeout_s):
            self.handle(event)
        self.tick()

    def start(self) -> None:
        """Take back notes sent before a restart, and show the replies that came while the bridge was down:
        the newest first, then the rest in turn as each one's linger ends."""
        recovered = list(reversed(self.executor.adopt()))
        for result in recovered:
            log.info("reply from while the bridge was down: %s: %s", result.request_id, result.text)
        if recovered:
            self._set_result(recovered[0], self.clock())
            self._recovered = recovered[1 : 1 + RECOVERED_MAX]

    def run_forever(self) -> None:
        log.info("helm bridge running (%s)", "dry run" if self.executor.dry_run else "LIVE")
        self.start()
        while True:
            self.step()
