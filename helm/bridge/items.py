"""Turn firstmate and herdr records into deck items and counts.

Item refs are stable strings the device echoes back in `select`:
  decision|<home>|<task>|<key>   a row of decisions_open[]
  pr|<home>|<pr url>             a PR waiting on the captain
  worker|<home>|<task>           a blocked or failed worker
  herdr|<pane id>                a herdr agent showing an approval or question UI
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from helm.contract import Counts, Item
from helm.bridge.sources import HomeRef, read_meta, safe_task_id, status_line_epoch

PR_URL = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+/pull/\d+")
RELAYED_HOLD = re.compile(r"^captain-hold-(.+)-\d+$")
SHORT_ID_MAX = 28
PROJECT_MAX = 32
WORKER_PROBLEM_STATES = {"blocked", "failed"}
# Ledger records older than this are history (the ledger backfills when turned on).
LEDGER_FRESH_S = 600
# A ledger-derived item stands in for the summary for at most this long.
PROVISIONAL_TTL_S = 900
COLOR_RANK = {"red": 0, "amber": 1, "blue": 2, "green": 3}


def decision_ref(home: str, task: str, key: str) -> str:
    return "decision|%s|%s|%s" % (home, task, key)


def pr_ref(home: str, url: str) -> str:
    return "pr|%s|%s" % (home, url)


def worker_ref(home: str, task: str) -> str:
    return "worker|%s|%s" % (home, task)


def herdr_ref(pane: str) -> str:
    return "herdr|%s" % pane


def clip(text: str, limit: int = SHORT_ID_MAX) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "~"


def pr_short(url: str) -> str:
    parts = url.rstrip("/").split("/")
    return "%s#%s" % (parts[-3], parts[-1]) if len(parts) >= 4 else url


def pr_repo(url: Optional[str]) -> Optional[str]:
    """The repository name in a PR URL (github.com/<owner>/<repo>/pull/<n>)."""
    parts = (url or "").rstrip("/").split("/")
    return clip(parts[-3], PROJECT_MAX) if len(parts) >= 4 and parts[-2] == "pull" else None


def task_project(home: Path, task: str, child_repos: dict[str, str]) -> Optional[str]:
    """The project a firstmate task works in: its active child's repo, else the basename of
    the `project` path in its meta. A second mate's meta names its own checkout, not a project."""
    if child_repos.get(task):
        return child_repos[task]
    meta = read_meta(home, task) if task else {}
    if meta.get("kind") == "secondmate" or not meta.get("project"):
        return None
    return clip(Path(meta["project"]).name, PROJECT_MAX) or None


def find_pr_url(*texts: Optional[str]) -> Optional[str]:
    for text in texts:
        match = PR_URL.search(text or "")
        if match:
            return match.group(0)
    return None


@dataclass
class Candidate:
    """An item before attention is applied, plus what the bridge needs to act on it."""

    item: Item
    task: str  # firstmate task id named in a note ("" for herdr items)
    note_key: str  # the key named in a note
    home_path: Optional[Path]
    pane: Optional[str]
    origin_epoch: Optional[float] = None  # when the item started needing the captain, if known


@dataclass
class HomeSnapshot:
    home: HomeRef
    summary: Optional[dict]
    pr_health: Optional[dict]


@dataclass
class Provisional:
    ref: str
    kind: str
    home: str
    task: str
    key: str
    text: str
    pr_url: Optional[str]
    ts: float


@dataclass
class LedgerState:
    """Event edges from each home's fleet ledger, and items the summary has not caught up to yet."""

    provisional: dict[str, Provisional] = field(default_factory=dict)
    merged: dict[tuple[str, str], float] = field(default_factory=dict)  # (home, task) -> ts

    def apply(self, home: str, records: list[dict], now: float) -> set[str]:
        """Fold new ledger records in; returns refs that just entered an attention state."""
        edges: set[str] = set()
        for rec in records:
            ts = rec.get("ts")
            task = rec.get("task")
            if not isinstance(ts, (int, float)) or now - ts > LEDGER_FRESH_S:
                continue
            if not isinstance(task, str) or not safe_task_id(task):
                continue
            event = rec.get("event")
            if event == "task.status":
                state, key = rec.get("state"), rec.get("key")
                text = (rec.get("text") or "").strip()
                if state == "needs-decision" and key:
                    ref = decision_ref(home, task, key)
                    self.provisional[ref] = Provisional(ref, "decision", home, task, key, text, find_pr_url(text), ts)
                    edges.add(ref)
                elif state in WORKER_PROBLEM_STATES:
                    ref = worker_ref(home, task)
                    self.provisional[ref] = Provisional(ref, "worker_problem", home, task, "", text, None, ts)
                    edges.add(ref)
                else:
                    self.provisional.pop(worker_ref(home, task), None)
                    if state == "resolved" and key:
                        self.provisional.pop(decision_ref(home, task, key), None)
            elif event == "task.pr_ready" and isinstance(rec.get("pr"), str):
                ref = pr_ref(home, rec["pr"])
                self.provisional[ref] = Provisional(ref, "pr_ready", home, task, "", rec["pr"], rec["pr"], ts)
                edges.add(ref)
            elif event == "task.merged":
                self.merged[(home, task)] = ts
                for ref, prov in list(self.provisional.items()):
                    if prov.home == home and prov.task == task and prov.kind == "pr_ready":
                        del self.provisional[ref]
        return edges

    def expire(self, now: float, summary_epochs: dict[str, float]) -> None:
        """Drop stand-ins once a summary published after the event exists: the summary is the state of record."""
        for ref, prov in list(self.provisional.items()):
            published = summary_epochs.get(prov.home)
            if now - prov.ts > PROVISIONAL_TTL_S or (published is not None and published > prov.ts):
                del self.provisional[ref]
        today = time.strftime("%Y-%m-%d", time.localtime(now))
        for key, ts in list(self.merged.items()):
            if time.strftime("%Y-%m-%d", time.localtime(ts)) != today:
                del self.merged[key]


def pr_checks(url: str, pr_health: Optional[dict], head: Optional[str] = None, reason: Optional[str] = None) -> str:
    """green, red, or unknown. pr-health records failures only, so green comes from firstmate's own verdict."""
    prs = (pr_health or {}).get("prs") or {}
    rec = prs.get(url) if isinstance(prs, dict) else None
    if isinstance(rec, dict):
        failing = [c for c in rec.get("checks") or [] if isinstance(c, dict) and (head is None or c.get("head") == head)]
        conflicts = [h for h in rec.get("conflicts") or [] if head is None or h == head]
        if failing or conflicts:
            return "red"
    if reason and "checks green" in reason:
        return "green"
    return "unknown"


def firstmate_pane(home: Path, agents: list[dict]) -> Optional[str]:
    """The herdr pane running the firstmate of a home: an agent whose working directory is the home."""
    try:
        target = home.resolve()
    except OSError:
        return None
    for agent in agents:
        cwd = agent.get("cwd")
        pane = agent.get("pane_id")
        if not cwd or not pane:
            continue
        try:
            if Path(cwd).resolve() == target:
                return pane
        except OSError:
            continue
    return None


def child_repos(summary: dict) -> dict[str, str]:
    """Task id to repo name for each active child that names one."""
    repos = {}
    for child in summary.get("active_children") or []:
        if isinstance(child, dict) and child.get("id") and isinstance(child.get("repo"), str) and child["repo"].strip():
            repos[str(child["id"])] = clip(child["repo"], PROJECT_MAX)
    return repos


def agent_title(agent: dict) -> str:
    """A herdr agent's name for the deck: its title token, else its terminal title, else its pane id."""
    tokens = agent.get("tokens") if isinstance(agent.get("tokens"), dict) else {}
    return clip(tokens.get("title") or agent.get("terminal_title_stripped") or agent.get("pane_id") or "agent")


def _actions(pane: Optional[str], *base: str) -> list:
    actions = list(base)
    if pane:
        actions.append("focus")
    return actions


def build_candidates(
    snapshots: list[HomeSnapshot],
    ledger: LedgerState,
    agents: list[dict],
    now: float,
) -> tuple[list[Candidate], Counts]:
    candidates: dict[str, Candidate] = {}
    counts = Counts()
    today = time.strftime("%Y-%m-%d", time.localtime(now))
    merge_ask_urls: set[str] = set()

    for snap in snapshots:
        label, path = snap.home.label, snap.home.path
        summary = snap.summary or {}
        fm_pane = firstmate_pane(path, agents)
        repos = child_repos(summary)
        heads = {}
        for c in (summary.get("contributions") or {}).get("captain") or []:
            if isinstance(c, dict) and c.get("url"):
                heads[c["url"]] = c.get("head")

        for row in summary.get("decisions_open") or []:
            if not isinstance(row, dict) or not row.get("id"):
                continue
            task, key = str(row["id"]), str(row.get("key") or row["id"])
            ref = decision_ref(label, task, key)
            detail = row.get("question") or row.get("summary") or row.get("reason") or ""
            url = find_pr_url(row.get("summary"), row.get("question"), row.get("reason"))
            checks = pr_checks(url, snap.pr_health, heads.get(url)) if url else None
            if url and key.startswith("merge-"):
                merge_ask_urls.add(url)
            if row.get("verb") == "captain-hold" and isinstance(row.get("hold_age_days"), (int, float)):
                origin = now - row["hold_age_days"] * 86400
            else:
                origin = status_line_epoch(path, task, key)
            pane = fm_pane or read_meta(path, task).get("herdr_pane_id")
            base = ["later", "hold"] if checks == "red" else ["yes", "later", "hold"]
            item = Item(
                ref=ref,
                kind="decision",
                color="red",
                short_id=clip(task if task == key else "%s/%s" % (task, key)),
                age_s=0,
                unseen=False,
                home=label,
                detail=detail,
                actions=_actions(pane, *base),
                pr_url=url,
                checks=checks,
                project=task_project(path, task, repos) or pr_repo(url),
            )
            candidates[ref] = Candidate(item, task, key, path, pane, origin)

        for c in (summary.get("contributions") or {}).get("captain") or []:
            if not isinstance(c, dict) or c.get("kind") != "pr" or not c.get("url"):
                continue
            url, task = c["url"], str(c.get("task") or "")
            ref = pr_ref(label, url)
            checks = pr_checks(url, snap.pr_health, c.get("head"), c.get("reason"))
            pane = (read_meta(path, task).get("herdr_pane_id") if task else None) or fm_pane
            base = ["later", "hold"] if checks == "red" else ["yes", "later", "hold"]
            item = Item(
                ref=ref,
                kind="pr_ready",
                color="blue",
                short_id=clip(pr_short(url)),
                age_s=0,
                unseen=False,
                home=label,
                detail="%s: %s %s" % (task, c.get("reason") or "ready", url),
                actions=_actions(pane, *base),
                pr_url=url,
                checks=checks,
                project=(task_project(path, task, repos) if task else None) or pr_repo(url),
            )
            candidates[ref] = Candidate(item, task, "pr-%s" % url.rstrip("/").split("/")[-1], path, pane)

        for child in summary.get("active_children") or []:
            if not isinstance(child, dict) or not child.get("id"):
                continue
            if child.get("state") == "working":
                counts.working += 1
            if child.get("state") not in WORKER_PROBLEM_STATES:
                continue
            task = str(child["id"])
            ref = worker_ref(label, task)
            pane = read_meta(path, task).get("herdr_pane_id")
            item = Item(
                ref=ref,
                kind="worker_problem",
                color="amber",
                short_id=clip(task),
                age_s=0,
                unseen=False,
                home=label,
                detail="%s %s: %s" % (task, child.get("state"), child.get("doing") or child.get("name") or ""),
                actions=_actions(pane, "hold"),
                project=task_project(path, task, repos),
            )
            candidates[ref] = Candidate(item, task, child.get("state") or "", path, pane, status_line_epoch(path, task))

        sc = summary.get("counts") or {}
        if isinstance(sc.get("queued"), int):
            counts.queued += sc["queued"]
        landed_ids = {
            str(row.get("id"))
            for row in summary.get("landed") or []
            if isinstance(row, dict) and (row.get("completion") or {}).get("date") == today
        }
        landed_ids |= {task for (home, task) in ledger.merged if home == label}
        counts.landed_today += len(landed_ids)

    # Ledger stand-ins for items the summary has not republished yet.
    paths = {snap.home.label: snap.home.path for snap in snapshots}
    health = {snap.home.label: snap.pr_health for snap in snapshots}
    repos_by_home = {snap.home.label: child_repos(snap.summary or {}) for snap in snapshots}
    for ref, prov in ledger.provisional.items():
        if ref in candidates:
            continue
        path = paths.get(prov.home)
        project = (task_project(path, prov.task, repos_by_home.get(prov.home, {})) if path else None) or pr_repo(prov.pr_url)
        if prov.kind == "decision":
            pane = (firstmate_pane(path, agents) if path else None) or (read_meta(path, prov.task).get("herdr_pane_id") if path else None)
            checks = pr_checks(prov.pr_url, health.get(prov.home)) if prov.pr_url else None
            if prov.pr_url and prov.key.startswith("merge-"):
                merge_ask_urls.add(prov.pr_url)
            item = Item(ref, "decision", "red", clip("%s/%s" % (prov.task, prov.key)), 0, False, prov.home,
                        prov.text, _actions(pane, *(["later", "hold"] if checks == "red" else ["yes", "later", "hold"])),
                        prov.pr_url, checks, project)
            candidates[ref] = Candidate(item, prov.task, prov.key, path, pane, prov.ts)
        elif prov.kind == "worker_problem":
            pane = read_meta(path, prov.task).get("herdr_pane_id") if path else None
            item = Item(ref, "worker_problem", "amber", clip(prov.task), 0, False, prov.home,
                        "%s: %s" % (prov.task, prov.text), _actions(pane, "hold"), project=project)
            candidates[ref] = Candidate(item, prov.task, "", path, pane, prov.ts)
        elif prov.kind == "pr_ready" and prov.pr_url:
            pane = (read_meta(path, prov.task).get("herdr_pane_id") if path else None) or (firstmate_pane(path, agents) if path else None)
            item = Item(ref, "pr_ready", "blue", clip(pr_short(prov.pr_url)), 0, False, prov.home,
                        "%s: ready %s" % (prov.task, prov.pr_url), _actions(pane, "yes", "later", "hold"),
                        prov.pr_url, "unknown", project)
            candidates[ref] = Candidate(item, prov.task, "pr-%s" % prov.pr_url.rstrip("/").split("/")[-1], path, pane, prov.ts)

    # A second mate's captain hold is relayed into the primary summary as a needs-decision row
    # (task = second mate id, key = captain-hold-<hold id>-<n>). When that second mate's home
    # is read directly, show the hold once, from its own home.
    direct = {(c.item.home, c.task) for c in candidates.values() if c.item.kind == "decision"}
    for ref, cand in list(candidates.items()):
        match = RELAYED_HOLD.match(cand.note_key)
        if cand.item.kind == "decision" and cand.item.home == "primary" and match and (cand.task, match.group(1)) in direct:
            del candidates[ref]

    # A PR that is already a merge ask on a decision row is shown once, as the decision.
    decision_urls = {c.item.pr_url for c in candidates.values() if c.item.kind == "decision" and c.item.pr_url}
    for ref in [r for r, c in candidates.items() if c.item.kind == "pr_ready" and c.item.pr_url in decision_urls]:
        del candidates[ref]

    for agent in agents:
        status = agent.get("agent_status")
        pane = agent.get("pane_id")
        if status == "working":
            counts.herdr_working += 1
        elif status == "blocked":
            counts.herdr_blocked += 1
        # idle never means finished: a harness can read idle while it waits on its own tool.
        if status != "blocked" or not pane:
            continue
        ref = herdr_ref(pane)
        item = Item(
            ref=ref,
            kind="herdr_blocked",
            color="amber",
            short_id=agent_title(agent),
            age_s=0,
            unseen=False,
            home="herdr",
            detail="%s in %s is waiting: %s" % (agent.get("agent") or "agent", agent.get("cwd") or "?",
                                                agent.get("terminal_title_stripped") or ""),
            actions=["focus"],
        )
        candidates[ref] = Candidate(item, "", "", None, pane)

    pr_urls = {c.item.pr_url for c in candidates.values() if c.item.kind == "pr_ready"}
    counts.prs_ready = len(pr_urls | merge_ask_urls)
    counts.decisions = sum(1 for c in candidates.values() if c.item.kind == "decision")
    return list(candidates.values()), counts


def finalize_items(candidates: list[Candidate], attention, now: float) -> list[Item]:
    """Fill age and unseen from the attention model, and order: unseen first, then by color, newest first."""
    items = []
    for cand in candidates:
        origin = cand.origin_epoch if cand.origin_epoch is not None else attention.first_seen(cand.item.ref)
        cand.item.age_s = max(0, int(now - origin)) if origin is not None else 0
        cand.item.unseen = attention.is_unseen(cand.item.ref)
        items.append(cand.item)
    items.sort(key=lambda it: (not it.unseen, COLOR_RANK.get(it.color, 9), it.age_s))
    return items
