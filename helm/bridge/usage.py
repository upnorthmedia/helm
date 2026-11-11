"""The usage gauge: what is left of the Claude 5 hour and weekly windows.

Read from `quota-axi --provider claude --json` every 5 minutes. Anything short
of a fresh reading (quota-axi missing, failing, timed out, not signed in, or
serving a cached reading because the live one failed) is unknown, never full.

quota-axi can take several seconds (it asks the vendor), so the command runs
on a thread and the bridge keeps sending models meanwhile. It runs with
`--no-credential-refresh` so the bridge never renews a session on its own: the
bridge only reads. On macOS, quota-axi reads Claude's credentials from the
Keychain only after `quota-axi --allow-keychain-prompt` has been run once by hand.
"""

from __future__ import annotations

import json
import logging
import math
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from helm.bridge.commands import Completed
from helm.contract import Usage

log = logging.getLogger(__name__)

USAGE_ARGV = ["quota-axi", "--provider", "claude", "--json", "--no-credential-refresh"]
USAGE_POLL_S = 300.0
USAGE_TIMEOUT_S = 60.0
# A reading older than this is unknown, even if no newer poll has finished.
USAGE_MAX_AGE_S = 900.0
# The device keeps resets as int32 (firmware/core); a reset decades away is clamped to that.
RESETS_MAX_S = 2**31 - 1
# quota-axi window ids to contract field prefixes.
WINDOWS = {"five_hour": "five_hour", "seven_day": "week"}


@dataclass(frozen=True)
class Window:
    left: int  # percent left, rounded down
    resets_at: Optional[float]  # epoch seconds


def _epoch(text) -> Optional[float]:
    if not isinstance(text, str):
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def parse_quota(stdout: str) -> tuple[dict[str, Window], Optional[str]]:
    """The known windows from quota-axi JSON, and why the rest are unknown (None when nothing is)."""
    try:
        data = json.loads(stdout)
    except (TypeError, ValueError):
        return {}, "quota-axi output is not JSON"
    providers = data.get("providers") if isinstance(data, dict) else None
    claude = next((p for p in providers or [] if isinstance(p, dict) and p.get("provider") == "claude"), None)
    if claude is None:
        return {}, "quota-axi reported no claude provider"
    state = claude.get("state") if isinstance(claude.get("state"), dict) else {}
    status = state.get("status")
    if status != "fresh":
        detail = state.get("error") or state.get("reason")
        return {}, "claude quota %s%s" % (status or "unreadable", " (%s)" % detail if detail else "")
    found: dict[str, Window] = {}
    for window in claude.get("windows") or []:
        if not isinstance(window, dict) or window.get("id") not in WINDOWS:
            continue
        left = window.get("percentRemaining")
        if isinstance(left, bool) or not isinstance(left, (int, float)) or not 0 <= left <= 100:
            continue
        found[WINDOWS[window["id"]]] = Window(math.floor(left), _epoch(window.get("resetsAt")))
    missing = [name for name in WINDOWS.values() if name not in found]
    return found, ("no %s window in the claude quota" % " or ".join(missing)) if missing else None


class UsagePoller:
    """Runs quota-axi every USAGE_POLL_S and keeps the last reading.

    With background=False the command runs inline, which the tests use.
    """

    def __init__(self, runner, background: bool = True, interval: float = USAGE_POLL_S):
        self.runner = runner
        self.background = background
        self.interval = interval
        self.windows: dict[str, Window] = {}
        self.read_at: Optional[float] = None
        self.reason: Optional[str] = "not read yet"
        self._next_at = 0.0
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._done = None  # a Completed, handed over by the thread

    def _read(self) -> Completed:
        # Any failure becomes a failed read, so the next poll is never blocked by a dead thread.
        try:
            return self.runner.run(USAGE_ARGV, timeout=USAGE_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001 - reported as unknown usage, never raised into the bridge
            return Completed(125, "", "%s: %s" % (type(exc).__name__, exc))

    def _run(self) -> None:
        done = self._read()
        with self._lock:
            self._done = done

    def poll(self, now: float) -> bool:
        """Start a read when due and take in a finished one. True when the reading changed."""
        if now >= self._next_at and self._thread is None:
            self._next_at = now + self.interval
            if self.background:
                self._thread = threading.Thread(target=self._run, name="helm-usage", daemon=True)
                self._thread.start()
            else:
                self._done = self._read()
        with self._lock:
            done, self._done = self._done, None
        if done is None:
            return False
        self._thread = None
        completed = done
        # Exit 1 means every provider failed, and quota-axi still prints its report, which says why.
        if completed.returncode in (0, 1) and completed.stdout.strip().startswith("{"):
            windows, reason = parse_quota(completed.stdout)
        else:
            windows, reason = {}, "quota-axi failed: %s" % (completed.stderr.strip()[:120] or "exit %d" % completed.returncode)
        changed = windows != self.windows or reason != self.reason
        if reason != self.reason and reason:
            log.info("claude usage partly unknown: %s", reason)
        self.windows, self.reason, self.read_at = windows, reason, now
        return changed

    def usage(self, now: float) -> Usage:
        if self.read_at is None or now - self.read_at > USAGE_MAX_AGE_S:
            return Usage()
        values = {}
        for name in WINDOWS.values():
            window = self.windows.get(name)
            values["%s_left" % name] = window.left if window else None
            if window and window.resets_at is not None:
                values["%s_resets_s" % name] = min(RESETS_MAX_S, max(0, int(window.resets_at - now)))
        return Usage(**values)
