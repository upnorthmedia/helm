"""Read-only readers for firstmate and herdr records (decision D11 in docs/research/README.md).

Nothing here writes under a firstmate home. File reads are cached by mtime and
size, so polling every couple of seconds costs a stat call per file.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

PRIMARY_LABEL = "primary"
_SAFE_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SECONDMATE_LINE = re.compile(r"^- (?P<id>[A-Za-z0-9][A-Za-z0-9._-]*) - .*\(home: (?P<home>[^;)]+)[;)]")
_STATUS_AT = re.compile(r"\[at=(\d+)\]")


@dataclass(frozen=True)
class HomeRef:
    label: str  # "primary", or the second mate's id
    path: Path

    @property
    def primary(self) -> bool:
        return self.label == PRIMARY_LABEL


def discover_homes(primary: Path) -> list[HomeRef]:
    """The primary home plus every second mate home listed in its data/secondmates.md (D19)."""
    homes = [HomeRef(PRIMARY_LABEL, primary)]
    roster = primary / "data" / "secondmates.md"
    try:
        lines = roster.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return homes
    seen = {primary.resolve()}
    for line in lines:
        match = _SECONDMATE_LINE.match(line)
        if not match:
            continue
        path = Path(match.group("home").strip()).expanduser()
        if not path.is_absolute() or path.resolve() in seen:
            continue
        seen.add(path.resolve())
        homes.append(HomeRef(match.group("id"), path))
    return homes


class JsonFile:
    """A JSON document re-read only when its mtime or size changes."""

    def __init__(self, path: Path):
        self.path = path
        self._stamp: Optional[tuple] = None
        self.data: Optional[Any] = None
        self.error: Optional[str] = None

    def poll(self) -> bool:
        """Refresh from disk if changed. Returns True when the content changed."""
        try:
            st = self.path.stat()
        except FileNotFoundError:
            changed = self.data is not None or self.error != "missing"
            self._stamp, self.data, self.error = None, None, "missing"
            return changed
        except OSError as exc:
            self.error = str(exc)
            return False
        stamp = (st.st_mtime_ns, st.st_size)
        if stamp == self._stamp:
            return False
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            # A torn write is not expected (the summary is published atomically),
            # but keep the last good copy and retry on the next stamp change.
            self.error = "unreadable: %s" % exc
            return False
        self._stamp, self.data, self.error = stamp, data, None
        return True


class LedgerTail:
    """Follows state/fleet-ledger.jsonl, returning only records appended after the bridge started.

    Turning the ledger on backfills every live task's existing status lines, so the
    tail starts at the end of the file, and callers ignore records with an old `ts`.
    """

    def __init__(self, path: Path):
        self.path = path
        self.offset: Optional[int] = None
        self.present = False

    def poll(self) -> list[dict]:
        try:
            size = self.path.stat().st_size
        except OSError:
            self.present = False
            self.offset = 0 if self.offset is not None else None
            return []
        if not self.present and self.offset is None:
            self.present = True
            self.offset = size  # first sight: skip history
            return []
        self.present = True
        if size < (self.offset or 0):
            self.offset = 0  # truncated with `: >`
        if size == self.offset:
            return []
        with self.path.open("rb") as fh:
            fh.seek(self.offset or 0)
            chunk = fh.read(size - (self.offset or 0))
        end = chunk.rfind(b"\n")
        if end < 0:
            return []  # no complete line yet
        self.offset = (self.offset or 0) + end + 1
        records = []
        for raw in chunk[: end + 1].splitlines():
            try:
                record = json.loads(raw)
            except ValueError:
                continue
            if isinstance(record, dict) and record.get("v") == 1:
                records.append(record)
        return records


def safe_task_id(task_id: str) -> bool:
    return bool(task_id) and bool(_SAFE_TASK_ID.match(task_id)) and ".." not in task_id


def read_meta(home: Path, task_id: str) -> dict:
    """state/<id>.meta as a dict; empty when absent or the id is not a plain task id."""
    if not safe_task_id(task_id):
        return {}
    try:
        text = (home / "state" / ("%s.meta" % task_id)).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    meta = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            meta[key.strip()] = value.strip()
    return meta


def task_metas(home: Path) -> dict[str, dict]:
    """Every state/<id>.meta in a home, by task id: firstmate's record of which tasks exist."""
    try:
        names = [p.name[: -len(".meta")] for p in (home / "state").glob("*.meta")]
    except OSError:
        return {}
    return {task: read_meta(home, task) for task in names if safe_task_id(task)}


def status_tail(home: Path, task_id: str) -> list[str]:
    """The last 64 KiB of state/<id>.status as lines, oldest first; empty when absent or the id is unsafe."""
    if not safe_task_id(task_id):
        return []
    path = home / "state" / ("%s.status" % task_id)
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - 65536))
            return fh.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return []


def status_line_epoch(home: Path, task_id: str, key: Optional[str] = None) -> Optional[int]:
    """The [at=<epoch>] stamp of the newest status line for a task (matching [key=...] when given)."""
    needle = "[key=%s]" % key if key else None
    for line in reversed(status_tail(home, task_id)):
        if needle and needle not in line:
            continue
        match = _STATUS_AT.search(line)
        if match:
            return int(match.group(1))
    return None


def parse_ready(stdout: str) -> Optional[dict]:
    try:
        data = json.loads(stdout)
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("schema") != "fm-primary-ready.v1":
        return None
    return data


def parse_herdr_agents(stdout: str) -> Optional[list[dict]]:
    try:
        data = json.loads(stdout)
    except ValueError:
        return None
    agents = data.get("result", {}).get("agents") if isinstance(data, dict) else None
    if not isinstance(agents, list):
        return None
    return [a for a in agents if isinstance(a, dict)]
