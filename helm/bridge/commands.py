"""The only external commands the bridge may run, enforced in one place.

The bridge never calls fm-wake-drain.sh, fm-inbox.sh drain,
fm-send.sh, fm-control.sh, fm-pr-merge.sh, fm-teardown.sh,
fm-home-summary-refresh.sh, tasks-axi, or any herdr command except
`agent list` and `agent focus`. The usage gauge adds one read,
`quota-axi --provider claude --json`, and the Mac lock check another,
`ioreg -n Root -d1 -a`. SHOW ME adds three viewer commands whose arguments
are checked too: `lavish-axi` alone (list the open boards), `lavish-axi <page>`
for an HTML page in the helm cache or a firstmate home's data/ directory, and
`open <url>` for a Lavish board on this Mac or a GitHub PR. Rather than list
what is forbidden, the runner refuses everything that is not on this allowlist.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence

log = logging.getLogger(__name__)

READ_COMMANDS = {
    ("fm-inbox.sh", "ready"),
    ("fm-inbox.sh", "receipts"),
    ("herdr", "agent", "list"),
    ("quota-axi", "--provider", "claude", "--json"),
    ("ioreg", "-n", "Root", "-d1", "-a"),
}
# Commands with an effect outside the bridge. Allowed only when the runner is live.
WRITE_COMMANDS = {
    ("fm-inbox.sh", "note"),
    ("fm-inbox.sh", "announce"),
    ("herdr", "agent", "focus"),
}

# SHOW ME's viewers. Unlike the commands above, these match a whole argv, not
# a prefix, and the program must be named bare (found on PATH), not by path.
LAVISH_LIST = ("lavish-axi",)  # read: exactly `lavish-axi`, which lists the open sessions
LAVISH_OPEN = ("lavish-axi", "<page>")  # live only: `lavish-axi <page.html> [--reopen] [--no-gate]`
OPEN_URL = ("open", "<url>")  # live only: `open <url>`, one argument, checked by openable_url
LAVISH_OPEN_FLAGS = ("--reopen", "--no-gate")
VIEWER_WRITES = {LAVISH_OPEN, OPEN_URL}

# A Lavish board served on this Mac (lavish-axi listens on loopback), or a GitHub PR.
# Matched with fullmatch, so a trailing newline or anything else extra is refused.
_BOARD_URL = re.compile(r"http://(?:127\.0\.0\.1|localhost):([0-9]{1,5})/session/[0-9a-f]{8,64}")
_PR_URL = re.compile(r"https://github\.com/[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9._-]+/pull/[0-9]+")


class CommandRefused(Exception):
    pass


@dataclass
class Completed:
    returncode: int
    stdout: str
    stderr: str


def openable_url(url: str) -> bool:
    """True for a loopback Lavish board URL or a GitHub PR URL, and nothing else."""
    board = _BOARD_URL.fullmatch(url)
    if board:
        return 0 < int(board.group(1)) < 65536
    return bool(_PR_URL.fullmatch(url))


def _viewer_signature(argv: Sequence[str]) -> Optional[tuple]:
    if list(argv) == ["lavish-axi"]:
        return LAVISH_LIST
    if argv[0] == "lavish-axi" and len(argv) >= 2:
        page, flags = argv[1], list(argv[2:])
        if (os.path.isabs(page) and page.endswith(".html") and "\0" not in page
                and all(f in LAVISH_OPEN_FLAGS for f in flags) and len(set(flags)) == len(flags)):
            return LAVISH_OPEN
        return None
    if argv[0] == "open" and len(argv) == 2 and openable_url(argv[1]):
        return OPEN_URL
    return None


def command_signature(argv: Sequence[str]) -> Optional[tuple]:
    """The (program, subcommand...) tuple an argv matches, or None when it matches nothing allowed."""
    if not argv:
        return None
    if argv[0] in ("lavish-axi", "open"):
        return _viewer_signature(argv)
    program = os.path.basename(argv[0])
    for allowed in READ_COMMANDS | WRITE_COMMANDS:
        if program == allowed[0] and tuple(argv[1 : len(allowed)]) == allowed[1:]:
            return allowed
    return None


def page_inside(page: str, roots: Iterable[Path]) -> bool:
    """True when page is an existing .html file under one of roots, after symlinks, outside any dot directory."""
    try:
        real = Path(page).resolve(strict=True)
    except (OSError, RuntimeError):
        return False
    if not real.is_file() or real.suffix.lower() != ".html":
        return False
    for root in roots:
        try:
            base = Path(root).resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if real.is_relative_to(base):
            return not any(part.startswith(".") for part in real.relative_to(base).parts)
    return False


def check_allowed(argv: Sequence[str], allow_writes: bool, page_roots: Iterable[Path] = ()) -> None:
    signature = command_signature(argv)
    if signature is None:
        raise CommandRefused("not on the bridge allowlist: %s" % " ".join(argv[:3]))
    if (signature in WRITE_COMMANDS or signature in VIEWER_WRITES) and not allow_writes:
        raise CommandRefused("write command refused outside --live: %s" % " ".join(signature))
    if signature == LAVISH_OPEN and not page_inside(argv[1], page_roots):
        raise CommandRefused("page is not in the helm cache or a firstmate data directory: %s" % argv[1])


class Runner:
    """Runs allowlisted commands. Tests substitute an object with the same `run` method.

    page_roots names the directories `lavish-axi <page>` may open from; it is
    read only when such a command is checked, since second mate homes come and go.
    """

    def __init__(self, allow_writes: bool = False, page_roots: Callable[[], Iterable[Path]] = lambda: ()):
        self.allow_writes = allow_writes
        self.page_roots = page_roots

    def run(self, argv: Sequence[str], env: Optional[dict] = None, timeout: float = 10.0) -> Completed:
        roots = list(self.page_roots()) if command_signature(argv) == LAVISH_OPEN else []
        check_allowed(argv, self.allow_writes, roots)
        full_env = dict(os.environ)
        if env:
            full_env.update(env)
        try:
            proc = subprocess.run(
                list(argv),
                capture_output=True,
                text=True,
                env=full_env,
                timeout=timeout,
                stdin=subprocess.DEVNULL,
            )
        except FileNotFoundError as exc:
            return Completed(127, "", str(exc))
        except subprocess.TimeoutExpired:
            return Completed(124, "", "timed out after %ss" % timeout)
        return Completed(proc.returncode, proc.stdout, proc.stderr)
