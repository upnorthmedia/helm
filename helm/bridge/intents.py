"""Key presses to firstmate notes, herdr focus, and SHOW ME's viewers (decisions D13 to D15 and D17 in docs/research/README.md).

A held YES, LATER, or HOLD becomes exactly one `fm-inbox.sh note --request-id <id> --json`
in the primary home. Firstmate reads it and acts through its own guarded commands,
or declines and replies. SHOW ME runs `herdr agent focus <pane>`, then opens the
item's Lavish board, report, or PR when it has one (helm/bridge/show.py).
"""

from __future__ import annotations

import json
import logging
import re
import shlex
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from helm.contract import Result
from helm.bridge.commands import CommandRefused
from helm.bridge.items import Candidate
from helm.bridge.report_html import render_report
from helm.bridge.show import LAVISH_LIST_ARGV, ShowTarget, default_cache_dir, find_target, parse_lavish_sessions

log = logging.getLogger(__name__)

# Firstmate treats a note beginning with exactly this text as the captain's word
# for the one task, key, or PR it names (D14). Do not reword it.
YES_PREFIX = "Captain, from the Helm deck, held to confirm: YES"
NOTE_EXIT_SAVED_NOT_ANNOUNCED = 3
_REQUEST_ID_UNSAFE = re.compile(r"[^A-Za-z0-9._:-]+")


def request_id(intent: str, cand: Candidate, now: float) -> str:
    """Stable per item, intent, and day, so a repeat press is a replay rather than a second note."""
    day = time.strftime("%Y%m%d", time.localtime(now))
    parts = ["helm", intent, cand.item.home, cand.task or "x", cand.note_key or "x", day]
    rid = _REQUEST_ID_UNSAFE.sub("_", "-".join(parts))
    return rid[:128]


def _subject(cand: Candidate) -> str:
    subject = "`%s` / `%s`" % (cand.task, cand.note_key)
    if cand.item.home != "primary":
        subject += " (second mate home `%s`)" % cand.item.home
    return subject


def note_text(intent: str, cand: Candidate) -> str:
    subject = _subject(cand)
    if intent == "yes":
        pr = "`%s`" % cand.item.pr_url if cand.item.pr_url else "the PR it names"
        return (
            "%s on %s. If this is a merge ask, merge %s under your normal checks. "
            "Otherwise go with your single recommended option, only if you gave exactly one. "
            "If neither applies, change nothing and reply." % (YES_PREFIX, subject, pr)
        )
    if intent == "later":
        return "Captain, from the Helm deck: defer %s until tomorrow." % subject
    if intent == "hold":
        return "Captain, from the Helm deck: do not proceed on %s. Raise it with me in chat." % subject
    raise ValueError("unknown intent %r" % intent)


@dataclass
class Pending:
    request_id: str
    note_id: str
    started: float


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
        rid = request_id(intent, cand, self.clock())
        argv = [self.inbox, "note", "--request-id", rid, "--json", "--", note_text(intent, cand)]
        if self.dry_run:
            self._dry(argv, "note", self.env)
            return Result(rid, "queued", "dry run: %s on %s logged, not sent" % (intent.upper(), cand.item.short_id))
        done = self.runner.run(argv, env=self.env, timeout=20)
        info = _json_or_none(done.stdout) or {}
        note_id = info.get("id")
        if done.returncode == 0 and note_id:
            self.pending[rid] = Pending(rid, note_id, self.clock())
            word = "already queued" if info.get("outcome") == "replay" else "queued"
            return Result(rid, "queued", "%s %s on %s" % (word, intent.upper(), cand.item.short_id))
        if done.returncode == NOTE_EXIT_SAVED_NOT_ANNOUNCED and note_id:
            # Saved but the wake failed: repair the wake, never send the note again.
            self.pending[rid] = Pending(rid, note_id, self.clock())
            fixed = self.runner.run([self.inbox, "announce", "--json", note_id], env=self.env, timeout=20)
            if fixed.returncode == 0:
                return Result(rid, "queued", "queued %s on %s (wake repaired)" % (intent.upper(), cand.item.short_id))
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

    def check_receipts(self) -> list[Result]:
        """Firstmate's replies to pending notes. Runs `receipts` only while something is pending."""
        if not self.pending:
            return []
        done = self.runner.run([self.inbox, "receipts"], env=self.env, timeout=10)
        data = _json_or_none(done.stdout)
        if done.returncode != 0 or not isinstance(data, dict):
            return []
        notes = {}
        for group in ("pending", "handled"):
            for note in data.get(group) or []:
                if isinstance(note, dict) and note.get("id"):
                    notes[note["id"]] = note
        results = []
        for rid, pend in list(self.pending.items()):
            note = notes.get(pend.note_id)
            if not note or not note.get("reply"):
                continue
            body = (note["reply"].get("body") or "").strip()
            results.append(Result(rid, "replied", body or "firstmate replied"))
            del self.pending[rid]
        return results


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
