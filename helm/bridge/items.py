"""Turn firstmate and herdr records into deck items and counts.

Item refs are stable strings the device echoes back in `select` and `key`:
  decision|<home>|<task>|<key>   a row of decisions_open[]
  pr|<home>|<pr url>             a PR waiting on the captain
  worker|<home>|<task>           a blocked or failed worker
  herdr|<pane id>                a herdr agent showing an approval or question UI
  more|<home>|<surface>          rows the home's summary left out (decisions_open or endpoints); shown only
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from helm.contract import Counts, Item
from helm.bridge.show import has_something_to_open
from helm.bridge.sources import HomeRef, read_meta, safe_task_id, status_line_epoch, task_metas

PR_URL = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+/pull/\d+")
RELAYED_HOLD = re.compile(r"^captain-hold-(.+)-\d+$")
SHORT_ID_MAX = 28
PROJECT_MAX = 32
WORKER_PROBLEM_STATES = {"blocked", "failed"}
# Ledger records older than this are history (the ledger backfills when turned on).
LEDGER_FRESH_S = 600
# A ledger-derived item stands in for the summary for at most this long.
PROVISIONAL_TTL_S = 900
# A captain row without a hold is firstmate's own "checks green, mergeable" verdict, and
# firstmate keeps it only this long (FM_CONTRIBUTIONS_MAX_AGE in fm-contributions.sh).
CAPTAIN_ROW_FRESH_S = 900
# Summary surfaces whose left-out rows could hide something that needs the captain.
OMITTED_SURFACES = {"decisions_open": "decisions", "endpoints": "tasks"}
COLOR_RANK = {"red": 0, "amber": 1, "blue": 2, "green": 3}


def decision_ref(home: str, task: str, key: str) -> str:
    return "decision|%s|%s|%s" % (home, task, key)


def pr_ref(home: str, url: str) -> str:
    return "pr|%s|%s" % (home, url)


def worker_ref(home: str, task: str) -> str:
    return "worker|%s|%s" % (home, task)


def herdr_ref(pane: str) -> str:
    return "herdr|%s" % pane


def more_ref(home: str, surface: str) -> str:
    return "more|%s|%s" % (home, surface)


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
    head: Optional[str] = None  # the PR's head commit as firstmate last read it, when the item names a PR
    informational: bool = False  # a "+N more" row: never new, never answered


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

    def expire(self, now: float, summary_epochs: dict[str, float], keep: frozenset = frozenset()) -> None:
        """Drop stand-ins once a summary published after the event exists: the summary is the state of record.

        A stand-in in `keep` (a worker the summary still shows blocked or failed) stays: its text
        and time describe the item the summary now carries.
        """
        for ref, prov in list(self.provisional.items()):
            if ref in keep:
                continue
            published = summary_epochs.get(prov.home)
            if now - prov.ts > PROVISIONAL_TTL_S or (published is not None and published > prov.ts):
                del self.provisional[ref]
        today = time.strftime("%Y-%m-%d", time.localtime(now))
        for key, ts in list(self.merged.items()):
            if time.strftime("%Y-%m-%d", time.localtime(ts)) != today:
                del self.merged[key]


def iso_epoch(text: object) -> Optional[int]:
    """An ISO 8601 UTC time such as 2026-11-11T00:00:00Z as epoch seconds, or None."""
    if not isinstance(text, str):
        return None
    try:
        return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def fresh_green(row: Optional[dict], now: float) -> bool:
    """A captain row with no hold, checked within firstmate's own freshness bound.

    Firstmate writes such a row only after a fresh read found the PR mergeable with no
    failed or pending checks (fm-contributions.jq), so it is the green verdict. A row
    with `hold` set exists because of the captain hold, and its checks were never judged.
    """
    if not isinstance(row, dict) or row.get("hold") is not None:
        return False
    checked = iso_epoch(row.get("checked_at"))
    return checked is not None and 0 <= int(now) - checked <= CAPTAIN_ROW_FRESH_S


def pr_verdict(url: str, pr_health: Optional[dict], row: Optional[dict] = None,
               now: Optional[float] = None) -> tuple[str, Optional[str]]:
    """(checks, note): green, red, or unknown, and for red what it rests on.

    Order: a fresh captain row is green. Otherwise state/pr-health.json applies; it is a
    record of failures already reported, never cleared when a re-run passes, so it counts
    only for the commit it names. With the commit unknown (no captain row), any report counts.
    """
    if fresh_green(row, time.time() if now is None else now):
        return "green", None
    head = row.get("head") if isinstance(row, dict) else None
    prs = (pr_health or {}).get("prs") or {}
    rec = prs.get(url) if isinstance(prs, dict) else None
    if isinstance(rec, dict):
        failing = [c for c in rec.get("checks") or [] if isinstance(c, dict) and (head is None or c.get("head") == head)]
        conflicts = [h for h in rec.get("conflicts") or [] if head is None or h == head]
        if failing or conflicts:
            where = "at this commit" if head else "at an unknown commit"
            return "red", "pr-health reported %s %s" % ("conflicts" if conflicts else "failing checks", where)
    return "unknown", None


def pr_checks(url: str, pr_health: Optional[dict], row: Optional[dict] = None, now: Optional[float] = None) -> str:
    return pr_verdict(url, pr_health, row, now)[0]


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


def _actions(showable: bool, *base: str) -> list:
    actions = list(base)
    if showable:
        actions.append("focus")
    return actions


def _showable(pane: Optional[str], home_path: Optional[Path], task: str, detail: str, pr_url: Optional[str]) -> bool:
    """SHOW ME applies when there is a pane to focus or a board, report, or PR to open."""
    return bool(pane) or has_something_to_open(home_path, task, detail, pr_url)


def worker_problems(snapshots: list[HomeSnapshot]) -> dict[str, tuple[HomeSnapshot, dict]]:
    """Worker ref to (home, endpoint row) for every task the summary shows blocked or failed.

    endpoints[] carries every task's reconciled current state (fm-crew-state.sh);
    active_children lists only working tasks. A second mate is a home, not a worker,
    and its own items come from its home.
    """
    problems = {}
    for snap in snapshots:
        for row in (snap.summary or {}).get("endpoints") or []:
            if not isinstance(row, dict) or row.get("state") not in WORKER_PROBLEM_STATES:
                continue
            task = str(row.get("id") or "")
            if not safe_task_id(task) or read_meta(snap.home.path, task).get("kind") == "secondmate":
                continue
            problems[worker_ref(snap.home.label, task)] = (snap, row)
    return problems


def summary_invalid(summary: Optional[dict]) -> Optional[str]:
    """Why a home's summary is invalid (`valid: false`), or None when it is valid or unread."""
    if not isinstance(summary, dict) or summary.get("valid") is not False:
        return None
    invalidity = summary.get("invalidity") if isinstance(summary.get("invalidity"), dict) else {}
    return str(summary.get("reason") or invalidity.get("kind") or "invalid")


def _omitted(summary: dict) -> dict[str, int]:
    out = {}
    for row in summary.get("omitted") or []:
        if isinstance(row, dict) and row.get("surface") in OMITTED_SURFACES and isinstance(row.get("count"), int):
            out[row["surface"]] = out.get(row["surface"], 0) + max(0, row["count"])
    return out


def _known_tasks(snapshots: list[HomeSnapshot]) -> tuple[set[str], set[str]]:
    """Every firstmate task the bridge can see, by id and by herdr pane, from each home's state/*.meta."""
    ids, panes = set(), set()
    for snap in snapshots:
        for task, meta in task_metas(snap.home.path).items():
            ids.add(task)
            if meta.get("herdr_pane_id"):
                panes.add(meta["herdr_pane_id"])
    return ids, panes


def build_candidates(
    snapshots: list[HomeSnapshot],
    ledger: LedgerState,
    agents: list[dict],
    now: float,
    panes: bool = True,
) -> tuple[list[Candidate], Counts]:
    """Items and counts from every home. With panes=False (no herdr), no item names a pane to focus."""
    candidates: dict[str, Candidate] = {}
    counts = Counts()
    today = time.strftime("%Y-%m-%d", time.localtime(now))
    merge_ask_urls: set[str] = set()
    omitted_decisions = 0
    problems = worker_problems(snapshots)

    def pane_of(home: Optional[Path], task: str) -> Optional[str]:
        return (read_meta(home, task).get("herdr_pane_id") if home and task else None) if panes else None

    for snap in snapshots:
        label, path = snap.home.label, snap.home.path
        summary = snap.summary or {}
        fm_pane = firstmate_pane(path, agents) if panes else None
        repos = child_repos(summary)
        rows = {}
        for c in (summary.get("contributions") or {}).get("captain") or []:
            if isinstance(c, dict) and c.get("url"):
                rows[c["url"]] = c

        for row in summary.get("decisions_open") or []:
            if not isinstance(row, dict) or not row.get("id"):
                continue
            task, key = str(row["id"]), str(row.get("key") or row["id"])
            ref = decision_ref(label, task, key)
            detail = row.get("question") or row.get("summary") or row.get("reason") or ""
            url = find_pr_url(row.get("summary"), row.get("question"), row.get("reason"))
            checks, why = pr_verdict(url, snap.pr_health, rows.get(url), now) if url else (None, None)
            if why:
                detail = "%s (%s)" % (detail, why)
            if url and key.startswith("merge-"):
                merge_ask_urls.add(url)
            if row.get("verb") == "captain-hold" and isinstance(row.get("hold_age_days"), (int, float)):
                origin = now - row["hold_age_days"] * 86400
            else:
                origin = status_line_epoch(path, task, key)
            pane = fm_pane or pane_of(path, task)
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
                actions=_actions(_showable(pane, path, task, detail, url), *base),
                pr_url=url,
                checks=checks,
                project=task_project(path, task, repos) or pr_repo(url),
            )
            candidates[ref] = Candidate(item, task, key, path, pane, origin, head=(rows.get(url) or {}).get("head") if url else None)

        for c in rows.values():
            if c.get("kind") != "pr":
                continue
            url, task = c["url"], str(c.get("task") or "")
            if c.get("hold") is not None:
                # On the deck because of a captain hold, not because it is ready: it belongs to
                # that hold's decision, which decisions_open lists under the hold's task id.
                hold = str(c["hold"])
                ref = decision_ref(label, hold, hold)
                cand = candidates.get(ref)
                if cand is not None:
                    if url not in cand.item.detail:
                        cand.item.detail = "%s PR %s" % (cand.item.detail, url)
                    cand.item.project = cand.item.project or pr_repo(url)
                    continue
                detail = "%s: %s PR %s" % (hold, c.get("reason") or "captain hold", url)
                pane = fm_pane or pane_of(path, hold)
                item = Item(ref, "decision", "red", clip(hold), 0, False, label, detail,
                            _actions(_showable(pane, path, hold, detail, None), "yes", "later", "hold"),
                            project=task_project(path, hold, repos) or pr_repo(url))
                candidates[ref] = Candidate(item, hold, hold, path, pane)
                continue
            ref = pr_ref(label, url)
            checks, why = pr_verdict(url, snap.pr_health, c, now)
            pane = pane_of(path, task) or fm_pane
            base = ["later", "hold"] if checks == "red" else ["yes", "later", "hold"]
            detail = "%s: %s %s" % (task, c.get("reason") or "ready", url)
            if why:
                detail = "%s (%s)" % (detail, why)
            item = Item(
                ref=ref,
                kind="pr_ready",
                color="blue",
                short_id=clip(pr_short(url)),
                age_s=0,
                unseen=False,
                home=label,
                detail=detail,
                actions=_actions(_showable(pane, path, task, detail, url), *base),
                pr_url=url,
                checks=checks,
                project=(task_project(path, task, repos) if task else None) or pr_repo(url),
            )
            candidates[ref] = Candidate(item, task, "pr-%s" % url.rstrip("/").split("/")[-1], path, pane, head=c.get("head"))

        holds = {str(h.get("id")): h for h in summary.get("holds") or [] if isinstance(h, dict) and h.get("id")}
        for row in summary.get("endpoints") or []:
            if not isinstance(row, dict) or row.get("state") != "working":
                continue
            if read_meta(path, str(row.get("id") or "")).get("kind") != "secondmate":
                counts.working += 1
        for ref, (problem_snap, row) in problems.items():
            if problem_snap is not snap:
                continue
            task, state = str(row["id"]), str(row["state"])
            prov = ledger.provisional.get(ref)
            text = (holds.get(task) or {}).get("reason") or (prov.text if prov else "")
            detail = "%s %s: %s" % (task, state, text) if text else "%s %s" % (task, state)
            pane = pane_of(path, task)
            item = Item(
                ref=ref,
                kind="worker_problem",
                color="amber",
                short_id=clip(task),
                age_s=0,
                unseen=False,
                home=label,
                detail=detail,
                actions=_actions(_showable(pane, path, task, detail, None), "hold"),
                project=task_project(path, task, repos),
            )
            origin = prov.ts if prov else status_line_epoch(path, task)
            candidates[ref] = Candidate(item, task, state, path, pane, origin)

        for surface, n in _omitted(summary).items():
            if surface == "decisions_open":
                omitted_decisions += n
            what = OMITTED_SURFACES[surface]
            ref = more_ref(label, surface)
            detail = ("Firstmate's summary for %s left out %d more %s, so the deck cannot show them. "
                      "Ask firstmate for the full list." % (label, n, what))
            item = Item(ref, "decision" if surface == "decisions_open" else "worker_problem",
                        "red" if surface == "decisions_open" else "amber", clip("+%d more %s" % (n, what)),
                        0, False, label, detail)
            candidates[ref] = Candidate(item, "", "", None, None, informational=True)

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
            pane = ((firstmate_pane(path, agents) if path and panes else None) or pane_of(path, prov.task))
            checks = pr_checks(prov.pr_url, health.get(prov.home), None, now) if prov.pr_url else None
            if prov.pr_url and prov.key.startswith("merge-"):
                merge_ask_urls.add(prov.pr_url)
            item = Item(ref, "decision", "red", clip("%s/%s" % (prov.task, prov.key)), 0, False, prov.home,
                        prov.text, _actions(_showable(pane, path, prov.task, prov.text, prov.pr_url),
                                            *(["later", "hold"] if checks == "red" else ["yes", "later", "hold"])),
                        prov.pr_url, checks, project)
            candidates[ref] = Candidate(item, prov.task, prov.key, path, pane, prov.ts)
        elif prov.kind == "worker_problem":
            pane = pane_of(path, prov.task)
            detail = "%s: %s" % (prov.task, prov.text)
            item = Item(ref, "worker_problem", "amber", clip(prov.task), 0, False, prov.home,
                        detail, _actions(_showable(pane, path, prov.task, detail, None), "hold"), project=project)
            candidates[ref] = Candidate(item, prov.task, "", path, pane, prov.ts)
        elif prov.kind == "pr_ready" and prov.pr_url:
            pane = pane_of(path, prov.task) or (firstmate_pane(path, agents) if path and panes else None)
            detail = "%s: ready %s" % (prov.task, prov.pr_url)
            item = Item(ref, "pr_ready", "blue", clip(pr_short(prov.pr_url)), 0, False, prov.home,
                        detail, _actions(_showable(pane, path, prov.task, detail, prov.pr_url), "yes", "later", "hold"),
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

    # A waiting pane that runs a firstmate task is firstmate's to handle: its watcher sees the
    # same transition, and the task's own item (if any) covers it. Other agents still ring.
    task_ids, task_panes = _known_tasks(snapshots)
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
        tokens = agent.get("tokens") if isinstance(agent.get("tokens"), dict) else {}
        if pane in task_panes or tokens.get("fm_task") in task_ids:
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
    counts.decisions = omitted_decisions + sum(
        1 for c in candidates.values() if c.item.kind == "decision" and not c.informational)
    return list(candidates.values()), counts


def finalize_items(candidates: list[Candidate], attention, now: float) -> list[Item]:
    """Fill age and unseen from the attention model, and order: unseen first, then by color, newest first.

    "+N more" rows go last."""
    items = []
    for cand in candidates:
        origin = cand.origin_epoch if cand.origin_epoch is not None else attention.first_seen(cand.item.ref)
        cand.item.age_s = max(0, int(now - origin)) if origin is not None else 0
        cand.item.unseen = attention.is_unseen(cand.item.ref)
        items.append((cand.informational, cand.item))
    items.sort(key=lambda pair: (pair[0], not pair[1].unseen, COLOR_RANK.get(pair[1].color, 9), pair[1].age_s))
    return [item for _, item in items]
