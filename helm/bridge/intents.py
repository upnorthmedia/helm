"""Key presses to firstmate notes, herdr focus, and SHOW ME's viewers (decisions D13 to D15 and D17 in docs/research/README.md).

A held YES, LATER, or HOLD becomes exactly one `fm-inbox.sh note --request-id <id> --json`
in the primary home. Firstmate reads it and acts through its own guarded commands,
or declines and replies. SHOW ME runs `herdr agent focus <pane>`, then opens the
item's Lavish board, report, or PR when it has one (helm/bridge/show.py).
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import re
import shlex
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from helm.contract import Result
from helm.bridge.commands import CommandRefused
from helm.bridge.items import Candidate
from helm.bridge.report_html import render_report
from helm.bridge.show import LAVISH_LIST_ARGV, ShowTarget, default_cache_dir, find_target, parse_lavish_sessions
from helm.bridge.sources import status_tail

log = logging.getLogger(__name__)

# A firstmate home with the YES rule (docs/firstmate-setup.md, the user's own opt-in) treats a
# note beginning with exactly this text as the captain's word for the one task, key, or PR it
# names (D14). The rule and the doctor match these words byte for byte: do not reword them.
YES_PREFIX = "Captain, from the Helm deck, held to confirm: YES"
NOTE_EXIT_SAVED_NOT_ANNOUNCED = 3
# On start, notes older than this are not taken back: firstmate has had a day to reply.
ADOPT_MAX_AGE_S = 86400
# The last firstmate reply this bridge has read, in the helm cache (never under a firstmate home).
CURSOR_FILE = "inbox-reply-cursor.json"
REQUEST_ID_MAX = 128  # fm-inbox.sh's limit
INTENTS = ("yes", "later", "hold")
# An answer that countermands an outstanding YES on the same item names that YES's request id.
COUNTERMANDS_YES = ("later", "hold")
_REQUEST_ID_UNSAFE = re.compile(r"[^A-Za-z0-9._:-]+")
_FULL_SHA = re.compile(r"[0-9a-f]{40}")
_STATUS_AT = re.compile(r"\[at=(\d+)\]")


def pinned_head(cand: Candidate) -> Optional[str]:
    """The PR commit a YES is pinned to: the item's head, only when it is a full 40 character SHA."""
    head = cand.head if isinstance(cand.head, str) else ""
    return head if cand.item.pr_url and _FULL_SHA.fullmatch(head) else None


def decision_opened(home: Optional[Path], task: str, key: str) -> Optional[int]:
    """When this decision was opened: the first status line for its key since the key was last resolved."""
    if home is None or not task or not key:
        return None
    needle = "[key=%s]" % key
    opened = None
    for line in status_tail(home, task):
        if needle not in line:
            continue
        if line.startswith("resolved"):
            opened = None  # closed; a later line for the key opens it again
        elif opened is None:
            match = _STATUS_AT.search(line)
            opened = int(match.group(1)) if match else None
    return opened


def item_instance(cand: Candidate) -> Optional[str]:
    """What makes this ask a new one on the same item: when a decision opened, and the PR commit shown."""
    parts = []
    if cand.item.kind == "decision":
        opened = decision_opened(cand.home_path, cand.task, cand.note_key)
        if opened is not None:
            parts.append("o%d" % opened)
        else:
            # No status record to date it (a captain hold carries only a whole-day age): its question stands in.
            parts.append("q" + hashlib.sha256(cand.item.detail.encode("utf-8")).hexdigest()[:8])
    head = pinned_head(cand)
    if head:
        parts.append(head[:12])
    return "-".join(parts) or None


def request_id(intent: str, cand: Candidate, now: float) -> str:
    """Stable per item instance, intent, and day, so a repeat press is a replay rather than a second note,
    while a new commit on the PR or a reopened decision is a new ask."""
    return _request_id(intent, cand, now, item_instance(cand))


def _request_id(intent: str, cand: Candidate, now: float, instance: Optional[str]) -> str:
    day = time.strftime("%Y%m%d", time.localtime(now))
    tail = _REQUEST_ID_UNSAFE.sub("_", "%s-%s" % (instance, day) if instance else day)
    identity = "-".join(["helm", intent, cand.item.home, cand.task or "x", cand.note_key or "x"])
    head = _REQUEST_ID_UNSAFE.sub("_", identity)
    room = REQUEST_ID_MAX - len(tail) - 1
    if len(head) > room:
        # Long task or key names give way first, so the instance and day always survive. A digest of
        # the whole identity keeps two items apart when only the cut part (often the key) differs.
        digest = "h" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:8]
        head = "%s-%s" % (head[: room - len(digest) - 1], digest)
    return "%s-%s" % (head, tail)


def _subject(cand: Candidate) -> str:
    subject = "`%s` / `%s`" % (cand.task, cand.note_key)
    if cand.item.home != "primary":
        subject += " (second mate home `%s`)" % cand.item.home
    return subject


def next_local_date(now: float) -> str:
    return (datetime.date.fromtimestamp(now) + datetime.timedelta(days=1)).isoformat()


def intent_of(rid) -> str:
    """The intent a Helm request id names (helm-<intent>-...), or "" for any other id."""
    parts = rid.split("-", 2) if isinstance(rid, str) else []
    return parts[1] if len(parts) > 2 and parts[0] == "helm" and parts[1] in INTENTS else ""


def note_text(intent: str, cand: Candidate, now: float, replaces_yes: Optional[str] = None) -> str:
    """The note for a held key. `replaces_yes` is the request id of a YES on this item that firstmate
    has not replied to yet; a LATER or HOLD names it, so firstmate can tell which answer stands."""
    subject = _subject(cand)
    replaces = " This replaces my earlier YES on it (request `%s`)." % replaces_yes if replaces_yes else ""
    if intent == "yes":
        pr = "`%s`" % cand.item.pr_url if cand.item.pr_url else "the PR it names"
        head = pinned_head(cand)
        if head:
            # Firstmate passes this as fm-pr-merge.sh --expected-head and refuses if the PR has moved.
            pr += " at commit `%s`" % head
        return (
            "%s on %s. If this is a merge ask, merge %s under your normal checks. "
            "Otherwise go with your single recommended option, only if you gave exactly one. "
            "If neither applies, change nothing and reply." % (YES_PREFIX, subject, pr)
        )
    if intent == "later":
        return "Captain, from the Helm deck: defer %s until %s.%s" % (subject, next_local_date(now), replaces)
    if intent == "hold":
        return "Captain, from the Helm deck: do not proceed on %s.%s Raise it with me in chat." % (subject, replaces)
    raise ValueError("unknown intent %r" % intent)


@dataclass
class Pending:
    request_id: str
    note_id: str
    started: float
    earlier: bool = False  # a replay of a note firstmate had already read: its reply is from before this press
    intent: str = ""  # yes, later, or hold
    ref: Optional[str] = None  # the item it answers, once known (a note taken back at start learns it by its id)
    seen: bool = False  # firstmate has read the note (receipts' `acknowledged`), with no reply yet


class IntentExecutor:
    def __init__(self, primary_home: Path, runner, dry_run: bool = True, clock=time.time,
                 cache_dir: Optional[Path] = None):
        self.primary_home = primary_home
        self.runner = runner
        self.dry_run = dry_run
        self.clock = clock
        self.cache_dir = cache_dir or default_cache_dir()  # rendered report pages; never under a firstmate home
        self.pending: dict[str, Pending] = {}
        self.dry_log: list[str] = []  # every command a dry run would have run
        self._cursor: Optional[str] = None  # receipts reply cursor; None until read from the cache

    @property
    def inbox(self) -> str:
        return str(self.primary_home / "bin" / "fm-inbox.sh")

    @property
    def env(self) -> dict:
        return {"FM_HOME": str(self.primary_home)}

    def _dry(self, argv: list[str], what: str, env: Optional[dict] = None) -> None:
        line = shlex.join(argv)
        self.dry_log.append(line)
        prefix = "".join("%s=%s " % (k, shlex.quote(v)) for k, v in (env or {}).items())
        log.info("dry run, not running %s: %s%s", what, prefix, line)

    def note(self, intent: str, cand: Candidate) -> Result:
        now = self.clock()
        rid = request_id(intent, cand, now)
        earlier_yes = self.outstanding(cand, "yes") if intent in COUNTERMANDS_YES else None
        text = note_text(intent, cand, now, earlier_yes.request_id if earlier_yes else None)
        argv = [self.inbox, "note", "--request-id", rid, "--json", "--", text]
        if self.dry_run:
            self._dry(argv, "note", self.env)
            return Result(rid, "queued", "dry run: %s on %s logged, not sent" % (intent.upper(), cand.item.short_id))
        done = self.runner.run(argv, env=self.env, timeout=20)
        info = _json_or_none(done.stdout) or {}
        note_id = info.get("id")
        what = "%s on %s" % (intent.upper(), cand.item.short_id)
        if done.returncode == 0 and note_id:
            if info.get("outcome") == "replay":
                return self._replayed(rid, note_id, info, what, now, intent, cand.item.ref)
            self.pending[rid] = Pending(rid, note_id, now, intent=intent, ref=cand.item.ref)
            return Result(rid, "queued", "queued %s" % what)
        if done.returncode == NOTE_EXIT_SAVED_NOT_ANNOUNCED and note_id:
            # Saved but the wake failed: repair the wake, never send the note again.
            self.pending[rid] = Pending(rid, note_id, now, intent=intent, ref=cand.item.ref)
            fixed = self.runner.run([self.inbox, "announce", "--json", note_id], env=self.env, timeout=20)
            if fixed.returncode == 0:
                return Result(rid, "queued", "queued %s (wake repaired)" % what)
            log.warning("announce %s failed (%s): %s", note_id, fixed.returncode, fixed.stderr.strip())
            return Result(rid, "queued", "saved, firstmate not woken yet")
        log.warning("note failed (%s): %s", done.returncode, done.stderr.strip())
        return Result(rid, "failed", "note not saved: %s" % (done.stderr.strip()[:80] or "exit %d" % done.returncode))

    def focus(self, pane: str) -> bool:
        argv = ["herdr", "agent", "focus", pane]
        if self.dry_run:
            self._dry(argv, "focus")
            return True
        done = self.runner.run(argv, timeout=5)
        if done.returncode != 0:
            log.warning("focus %s failed (%s): %s", pane, done.returncode, done.stderr.strip())
        return done.returncode == 0

    def show_target(self, cand: Candidate) -> Optional[ShowTarget]:
        """What SHOW ME opens for this item. Lists Lavish sessions (a read, so dry runs do it too)."""
        if cand.home_path is None and not cand.item.pr_url:
            return None
        sessions = None
        if cand.home_path is not None:
            done = self.runner.run(LAVISH_LIST_ARGV, timeout=10)
            if done.returncode == 0:
                sessions = parse_lavish_sessions(done.stdout)
            else:
                log.info("lavish-axi unreadable (%s), looking for a report instead", done.returncode)
        return find_target(cand, sessions, self.cache_dir)

    def open(self, target: ShowTarget, cand: Candidate) -> bool:
        """Render a Markdown report's page if needed, then run the target's command (or log it in a dry run)."""
        argv = list(target.argv)
        if target.source is not None:
            page = Path(argv[1])
            homes = [h for h in (self.primary_home, cand.home_path) if h is not None]
            if any(_inside(page, home) for home in homes):
                log.warning("refusing to write a report page under a firstmate home: %s", page)
                return False
        if self.dry_run:
            self._dry(argv, "open %s" % target.what)
            return True
        if target.source is not None:
            try:
                text = target.source.read_text(encoding="utf-8", errors="replace")
                page.parent.mkdir(parents=True, exist_ok=True)
                tmp = page.with_name(page.name + ".tmp")
                tmp.write_text(render_report(text, target.source, cand.item.home, cand.task, self.clock()), encoding="utf-8")
                tmp.replace(page)
            except (OSError, RecursionError) as exc:  # RecursionError: quotes nested too deep to render
                log.warning("report page %s not written: %s", page, exc)
                return False
        try:
            done = self.runner.run(argv, timeout=20)
        except CommandRefused as exc:  # the page went away, or moved, since it was found
            log.warning("open %s refused: %s", target.what, exc)
            return False
        if done.returncode != 0:
            log.warning("open %s failed (%s): %s", target.what, done.returncode, done.stderr.strip()[:200])
        return done.returncode == 0

    def _replayed(self, rid: str, note_id: str, info: dict, what: str, now: float, intent: str, ref: str) -> Result:
        """The same ask again. If firstmate already read the note, say so, and label any reply as earlier.

        fm-inbox.sh can report a replayed note as not acknowledged once it has been announced,
        so the receipts row decides; the note's path is the fallback when receipts do not list it.
        """
        data = self._receipts([])
        row = _notes(data).get(note_id) if data else None
        if row is not None:
            acknowledged = row.get("acknowledged") is True
        else:
            acknowledged = info.get("acknowledged") is True or "/handled/" in str(info.get("path") or "")
        reply = _reply_body(row.get("reply")) if row else None
        if reply is not None:
            self.pending.pop(rid, None)
            return Result(rid, "replied", "answered earlier: %s. Earlier reply: %s" % (what, reply or "firstmate replied"))
        if acknowledged:
            self.pending[rid] = Pending(rid, note_id, now, earlier=True, intent=intent, ref=ref, seen=True)
            return Result(rid, "queued", "answered earlier: %s, no reply yet" % what)
        self.pending[rid] = Pending(rid, note_id, now, intent=intent, ref=ref)
        return Result(rid, "queued", "already queued %s" % what)

    def outstanding(self, cand: Candidate, intent: str) -> Optional[Pending]:
        """The note with this intent still waiting on a reply for this item instance, if any."""
        found = self._answered([cand], intent)
        return found.get(cand.item.ref)

    def answered(self, candidates: Iterable[Candidate]) -> dict[str, str]:
        """Each item's answer still waiting on firstmate's reply (the latest sent, when there are two)."""
        return {ref: pend.intent for ref, pend in self._answered(candidates).items()}

    def _answered(self, candidates: Iterable[Candidate], intent: Optional[str] = None) -> dict[str, Pending]:
        """Pending notes by the item they answer. A note counts only for the item instance it was sent for:
        its request id must be the one this item would get today for that intent, on the day it was sent.
        So a new commit on the PR, or a reopened decision, has nothing pending."""
        by_ref = {c.item.ref: c for c in candidates}
        instances: dict[str, Optional[str]] = {}  # item_instance reads status files: once per item per call

        def matches(pend: Pending, cand: Candidate) -> bool:
            ref = cand.item.ref
            if ref not in instances:
                instances[ref] = item_instance(cand)
            return _request_id(pend.intent, cand, pend.started, instances[ref]) == pend.request_id

        found: dict[str, Pending] = {}
        for pend in self.pending.values():
            if not pend.intent or (intent is not None and pend.intent != intent):
                continue
            if pend.ref is not None:
                cand = by_ref.get(pend.ref)
                cand = cand if cand is not None and matches(pend, cand) else None
            else:  # taken back at start: find its item by its request id
                cand = next((c for c in by_ref.values() if matches(pend, c)), None)
                if cand is not None:
                    pend.ref = cand.item.ref
            if cand is None:
                continue
            best = found.get(cand.item.ref)
            if best is None or pend.started >= best.started:
                found[cand.item.ref] = pend
        return found

    def check_receipts(self) -> list[Result]:
        """Firstmate's replies to pending notes, and which of them it has read. Runs `receipts` only while
        something is pending."""
        if not self.pending:
            return []
        cursor = self._load_cursor()
        data = self._receipts(["--after", cursor] if cursor else [])
        if data is None:
            return []
        notes = _notes(data)
        for pend in self.pending.values():
            row = notes.get(pend.note_id)
            if row is not None and row.get("acknowledged") is True:
                pend.seen = True  # never unset: a note leaves the bounded list, not handled/
        replies = {note_id: note["reply"] for note_id, note in notes.items() if note.get("reply")}
        for reply in data.get("replies") or []:
            if isinstance(reply, dict) and reply.get("id"):
                replies[reply["id"]] = reply
        results = []
        for rid, pend in list(self.pending.items()):
            body = _reply_body(replies.get(pend.note_id))
            if body is None:
                continue
            text = body or "firstmate replied"
            results.append(Result(rid, "replied", "earlier reply: %s" % text if pend.earlier else text))
            del self.pending[rid]
        self._save_cursor(data.get("reply_cursor"))
        return results

    def adopt(self) -> list[Result]:
        """On start: take back this bridge's notes still waiting on a reply, and return the replies
        that came while it was down. A dry run sent nothing and leaves the live cursor alone."""
        if self.dry_run:
            return []
        cursor = self._load_cursor()
        # With no cursor yet, every reply listed is from before this bridge kept one: none is shown.
        data = self._receipts(["--after", cursor, "--all-replies"] if cursor else [])
        if data is None:
            return []
        now = self.clock()
        notes = _notes(data)
        for note_id, note in notes.items():
            rid = note.get("request_id")
            if not _ours(rid) or note.get("reply") or rid in self.pending:
                continue
            at = _utc_epoch(note.get("at"))
            if at is None or now - at > ADOPT_MAX_AGE_S:
                continue
            self.pending[rid] = Pending(rid, note_id, at, intent=intent_of(rid), seen=note.get("acknowledged") is True)
        results = []
        for reply in (data.get("replies") or []) if cursor else []:
            note = notes.get(reply.get("id")) if isinstance(reply, dict) else None
            body = _reply_body(reply)
            if note is not None and _ours(note.get("request_id")) and body is not None:
                results.append(Result(note["request_id"], "replied", body or "firstmate replied"))
        self._save_cursor(data.get("reply_cursor"))
        if self.pending or results:
            log.info("after restart: %d note(s) waiting, %d reply(ies) since last run", len(self.pending), len(results))
        return results

    def _receipts(self, extra: list[str]) -> Optional[dict]:
        done = self.runner.run([self.inbox, "receipts", *extra], env=self.env, timeout=10)
        data = _json_or_none(done.stdout)
        if done.returncode != 0 or not isinstance(data, dict):
            return None
        return data

    @property
    def _cursor_path(self) -> Path:
        return self.cache_dir / CURSOR_FILE

    def _load_cursor(self) -> str:
        """The saved reply cursor for this home, or "" when there is none (or it belongs to another home)."""
        if self._cursor is None:
            self._cursor = ""
            try:
                saved = json.loads(self._cursor_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                saved = None
            if isinstance(saved, dict) and saved.get("home") == str(self.primary_home) and _valid_cursor(saved.get("cursor")):
                self._cursor = saved["cursor"]
        return self._cursor

    def _save_cursor(self, cursor) -> None:
        if not _valid_cursor(cursor) or (self._cursor and int(cursor) <= int(self._cursor)):
            return
        self._cursor = cursor
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            tmp = self._cursor_path.with_name(CURSOR_FILE + ".tmp")
            tmp.write_text(json.dumps({"home": str(self.primary_home), "cursor": cursor}), encoding="utf-8")
            tmp.replace(self._cursor_path)
        except OSError as exc:
            log.warning("reply cursor not saved: %s", exc)


def _inside(path: Path, root: Path) -> bool:
    try:
        return path.resolve().is_relative_to(root.resolve())
    except (OSError, RuntimeError):
        return True  # cannot tell, so treat it as inside


def _json_or_none(text: str):
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def _ours(rid) -> bool:
    return isinstance(rid, str) and rid.startswith("helm-")


def _notes(data: dict) -> dict[str, dict]:
    """Pending and handled notes from a receipts read, by note id."""
    notes = {}
    for group in ("pending", "handled"):
        for note in data.get(group) or []:
            if isinstance(note, dict) and note.get("id"):
                notes[note["id"]] = note
    return notes


def _reply_body(reply) -> Optional[str]:
    """A reply record's text, stripped ("" for an empty one), or None when there is no reply."""
    if not isinstance(reply, dict):
        return None
    return str(reply.get("body") or "").strip()


def _valid_cursor(cursor) -> bool:
    return isinstance(cursor, str) and cursor.isascii() and cursor.isdigit()


def _utc_epoch(stamp) -> Optional[float]:
    """fm-inbox.sh's note time, 2026-11-11T16:06:06Z, as epoch seconds."""
    try:
        return datetime.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc).timestamp()
    except (TypeError, ValueError):
        return None
