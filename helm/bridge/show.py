"""What SHOW ME opens beside the herdr pane: the item's Lavish board, its report, or its PR.

Resolution reads only, and the first match wins:
1. A live Lavish board: a session `lavish-axi` lists whose id a board URL in
   the item's text names (its detail, or its task's newest status lines), or
   whose file is the report path the item names, or sits in the task's own
   data/<task>/ directory. The board opens on loopback, whatever host the
   text or the listing names.
2. The task's report in its own home: a data/... .md or .html path the item
   names, else data/<task>/report.md. An HTML report opens in Lavish as it is;
   Markdown is rendered to a page in the helm cache first, never under a
   firstmate home.
3. The item's PR on GitHub.
Otherwise SHOW ME only focuses the pane, as before.
"""

from __future__ import annotations

import csv
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

from helm.bridge.commands import LAVISH_LIST, openable_url
from helm.bridge.items import Candidate
from helm.bridge.sources import safe_task_id, status_tail

LAVISH_LIST_ARGV = list(LAVISH_LIST)
LAVISH_OPEN_FLAGS = ["--reopen", "--no-gate"]  # a tap is an explicit ask, so reopen an ended board, and at once
STATUS_LINES = 20  # newest status lines searched for a board URL or report path
_SESSIONS_HEADER = re.compile(r"^sessions\[\d+\]\{([^}]*)\}:\s*$")
_SESSION_PATH = re.compile(r"/session/([0-9a-f]{8,64})")
_TEXT_BOARD = re.compile(r"https?://[^\s/\"'`<>()]+/session/([0-9a-f]{8,64})(?![0-9a-f])")
_TEXT_REPORT = re.compile(r"(?<![\w./-])((?:/[^\s\"'`<>()]*)?data/[A-Za-z0-9][\w.-]*/[^\s\"'`<>()]*?\.(?:md|html))(?![\w/-])")
_PAGE_NAME_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class LavishSession:
    file: Path
    url: str  # http://127.0.0.1:<port>/session/<id>

    @property
    def id(self) -> str:
        return self.url.rsplit("/", 1)[1]


@dataclass(frozen=True)
class ShowTarget:
    what: str  # "board", "report", or "PR"
    argv: tuple[str, ...]  # the command that opens it
    source: Optional[Path] = None  # Markdown to render to the page argv names, before opening


def default_cache_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "helm"
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "helm"


def loopback_board_url(url: str) -> Optional[str]:
    """A Lavish session URL moved to 127.0.0.1 on the same port, or None if it is not one."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    match = _SESSION_PATH.fullmatch(parts.path)
    if parts.scheme != "http" or not port or not match or parts.query or parts.fragment or parts.username:
        return None
    board = "http://127.0.0.1:%d/session/%s" % (port, match.group(1))
    return board if openable_url(board) else None


def parse_lavish_sessions(stdout: str) -> list[LavishSession]:
    """The sessions in `lavish-axi` output: a `sessions[N]{file,status,url,...}:` header, then one row per line."""
    lines = stdout.splitlines()
    for start, line in enumerate(lines):
        header = _SESSIONS_HEADER.match(line)
        if header:
            break
    else:
        return []
    columns = [c.strip() for c in header.group(1).split(",")]
    sessions = []
    for line in lines[start + 1 :]:
        if not line.startswith("  "):
            break
        row = dict(zip(columns, next(csv.reader([line.strip()]), [])))
        url = loopback_board_url(row.get("url", ""))
        file = row.get("file", "")
        if url and os.path.isabs(file) and row.get("status") != "ended":
            sessions.append(LavishSession(Path(file), url))
    return sessions


def _resolved(path: Path) -> Optional[Path]:
    try:
        return path.resolve(strict=True)
    except (OSError, RuntimeError):
        return None


def _in_data(path: Path, data: Path) -> bool:
    """True for an existing file under data/, after symlinks, outside any dot directory."""
    real, base = _resolved(path), _resolved(data)
    if real is None or base is None or not real.is_file() or not real.is_relative_to(base):
        return False
    return not any(part.startswith(".") for part in real.relative_to(base).parts)


def item_texts(cand: Candidate) -> list[str]:
    """The item's detail, then its task's status lines, newest first."""
    texts = [cand.item.detail or ""]
    if cand.home_path is not None and cand.task:
        texts += list(reversed(status_tail(cand.home_path, cand.task)[-STATUS_LINES:]))
    return texts


def named_report(cand: Candidate, texts: list[str]) -> Optional[Path]:
    """The first data/... .md or .html path the item names that is a file in its own home's data/."""
    if cand.home_path is None:
        return None
    data = cand.home_path / "data"
    for text in texts:
        for match in _TEXT_REPORT.finditer(text):
            raw = match.group(1)
            path = Path(raw) if raw.startswith("/") else cand.home_path / raw
            if _in_data(path, data):
                return _resolved(path)
    return None


def _newest(sessions: list[LavishSession]) -> Optional[LavishSession]:
    def mtime(session: LavishSession) -> float:
        try:
            return session.file.stat().st_mtime
        except OSError:
            return -1.0
    return max(sessions, key=mtime) if sessions else None


def find_board(cand: Candidate, sessions: list[LavishSession], texts: list[str],
               report: Optional[Path]) -> Optional[LavishSession]:
    by_id = {s.id: s for s in sessions}
    for text in texts:
        for match in _TEXT_BOARD.finditer(text):
            if match.group(1) in by_id:
                return by_id[match.group(1)]
    if report is not None:
        for session in sessions:
            if _resolved(session.file) == report:
                return session
    if cand.home_path is not None and safe_task_id(cand.task):
        task_dir = _resolved(cand.home_path / "data" / cand.task)
        if task_dir is not None:
            mine = [s for s in sessions if (_resolved(s.file) or Path("/")).is_relative_to(task_dir)]
            return _newest(mine)
    return None


def report_page(cache_dir: Path, cand: Candidate, report: Path) -> Path:
    """Where a Markdown report's rendered page goes: one stable file per home, task, and report."""
    name = _PAGE_NAME_UNSAFE.sub("_", "%s-%s-%s" % (cand.item.home, cand.task or "x", report.stem))
    return cache_dir / "reports" / ("%s.html" % name[:120])


def find_target(cand: Candidate, sessions: Optional[list[LavishSession]], cache_dir: Path) -> Optional[ShowTarget]:
    """What SHOW ME should open for this item, or None to only focus. sessions is None when Lavish was unreadable."""
    texts = item_texts(cand)
    named = named_report(cand, texts)
    board = find_board(cand, sessions or [], texts, named)
    if board is not None:
        return ShowTarget("board", ("open", board.url))
    report = named
    if report is None and cand.home_path is not None and safe_task_id(cand.task):
        default = cand.home_path / "data" / cand.task / "report.md"
        report = _resolved(default) if _in_data(default, cand.home_path / "data") else None
    if report is not None and report.suffix == ".html":
        return ShowTarget("report", ("lavish-axi", str(report), *LAVISH_OPEN_FLAGS))
    if report is not None:
        page = report_page(cache_dir, cand, report)
        return ShowTarget("report", ("lavish-axi", str(page), *LAVISH_OPEN_FLAGS), source=report)
    if cand.item.pr_url and openable_url(cand.item.pr_url):
        return ShowTarget("PR", ("open", cand.item.pr_url))
    return None
