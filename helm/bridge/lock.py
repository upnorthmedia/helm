"""Whether the Mac's login session is locked, so the deck's keys can be locked with it.

Read from the I/O Registry root with `ioreg -n Root -d1 -a`: a read-only
command in every macOS install (/usr/sbin/ioreg) that prints the root's
properties as an XML property list, which plistlib (standard library) parses.
Two properties answer it, both kept by the window server and loginwindow:

- IOConsoleLocked (on the root): true while the console is locked, and while
  the login window is up (nobody logged in, or a user switch in progress).
- IOConsoleUsers: one entry per GUI session. For this user's session
  (kCGSSessionUserIDKey is our uid), CGSSessionScreenIsLocked is present and
  true while its screen is locked, and kCGSSessionOnConsoleKey is false
  while another user has the console (fast user switching).

The session is locked when IOConsoleLocked is true, or this user's session
is screen locked or not on the console. Checked on this Mac (Darwin 27,
Apple silicon) with the screen locked: both IOConsoleLocked and
CGSSessionScreenIsLocked read true. One read and parse takes about 22 ms.

Limits:
- kCGSSessionUserIDKey and kCGSSessionOnConsoleKey are public: CoreGraphics'
  CGSession.h defines them as kCGSessionUserIDKey and kCGSessionOnConsoleKey,
  keys of CGSessionCopyCurrentDictionary. IOConsoleLocked and
  CGSSessionScreenIsLocked are not documented by Apple. They have kept their
  meaning across releases, but a future macOS could rename them; then a
  locked screen reads as unlocked (or unknown), so the keys stay usable.
- A display that sleeps without locking is not detected: Apple silicon has
  no IODisplayWrangler, and per-display power states differ by display. With
  "Require password after screen saver begins or display is turned off" set
  to immediately (System Settings, Lock Screen), a display sleep locks the
  session, and that is seen here.
- Unknown (ioreg missing, as off macOS, failing, or unparseable) leaves the
  keys unlocked, as before this feature, and is logged once.
- It is polled every LOCK_POLL_S; the bridge also reads it again right
  before acting on a held key or a SHOW ME tap, so a lock in between still
  refuses the action.
"""

from __future__ import annotations

import logging
import os
import plistlib
from typing import Optional

from helm.bridge.commands import Completed

log = logging.getLogger(__name__)

LOCK_ARGV = ["/usr/sbin/ioreg", "-n", "Root", "-d1", "-a"]
LOCK_POLL_S = 3.0
LOCK_TIMEOUT_S = 5.0


def parse_lock(stdout: str, uid: int) -> Optional[bool]:
    """True when the session is locked, False when it is not, None when the output does not say."""
    try:
        root = plistlib.loads(stdout.encode("utf-8"))
    except (plistlib.InvalidFileException, ValueError, TypeError, OverflowError):
        return None
    if not isinstance(root, dict):
        return None
    console_locked = root.get("IOConsoleLocked")
    users = root.get("IOConsoleUsers")
    mine = None
    for user in users if isinstance(users, list) else []:
        if isinstance(user, dict) and user.get("kCGSSessionUserIDKey") == uid:
            mine = user
            break
    if console_locked is True:
        return True
    if mine is not None and (mine.get("CGSSessionScreenIsLocked") is True or mine.get("kCGSSessionOnConsoleKey") is False):
        return True
    if console_locked is False:
        return False
    return None


class LockWatch:
    """Reads the lock state every LOCK_POLL_S, and on demand before an action."""

    def __init__(self, runner, uid: Optional[int] = None, interval: float = LOCK_POLL_S):
        self.runner = runner
        self.uid = os.getuid() if uid is None else uid
        self.interval = interval
        self.locked: Optional[bool] = None
        self._next_at = 0.0
        self._logged_unknown = False

    def read(self, now: float) -> bool:
        """Read now. True when the state changed."""
        self._next_at = now + self.interval
        try:
            done = self.runner.run(LOCK_ARGV, timeout=LOCK_TIMEOUT_S)
        except OSError as exc:
            # ioreg could not start (permission, fork failure): unknown, never raised into the
            # bridge loop. A CommandRefused is not an OSError, so an allowlist mistake still surfaces.
            done = Completed(126, "", "%s: %s" % (type(exc).__name__, exc))
        locked = parse_lock(done.stdout, self.uid) if done.returncode == 0 else None
        if locked is None and not self._logged_unknown:
            log.info("Mac lock state unknown (ioreg exit %d); keys stay unlocked", done.returncode)
            self._logged_unknown = True
        changed = locked != self.locked
        self.locked = locked
        return changed

    def poll(self, now: float) -> bool:
        return self.read(now) if now >= self._next_at else False
