import plistlib
import unittest

from helm.bridge.commands import CommandRefused, Completed, check_allowed
from helm.bridge.lock import LOCK_ARGV, LockWatch, parse_lock
from tests.helpers import ioreg_root

UID = 501


class ParseLockTest(unittest.TestCase):
    def test_locked_and_unlocked(self):
        self.assertIs(parse_lock(ioreg_root(locked=True, uid=UID), UID), True)
        self.assertIs(parse_lock(ioreg_root(locked=False, uid=UID), UID), False)

    def test_screen_lock_flag_alone_counts(self):
        root = plistlib.loads(ioreg_root(locked=True, uid=UID).encode())
        root["IOConsoleLocked"] = False
        self.assertIs(parse_lock(plistlib.dumps(root).decode(), UID), True)

    def test_console_lock_alone_counts(self):
        # The login window is up: no session of ours is screen locked, but the console is.
        root = plistlib.loads(ioreg_root(locked=False, uid=UID).encode())
        root["IOConsoleLocked"] = True
        self.assertIs(parse_lock(plistlib.dumps(root).decode(), UID), True)

    def test_switched_to_another_user_counts_as_locked(self):
        root = plistlib.loads(ioreg_root(locked=False, uid=UID, on_console=False).encode())
        other = {"kCGSSessionUserIDKey": 502, "kCGSSessionOnConsoleKey": True}
        root["IOConsoleUsers"].append(other)
        self.assertIs(parse_lock(plistlib.dumps(root).decode(), UID), True)

    def test_another_users_lock_is_not_ours(self):
        # Our session has the console; another user's session is locked in the background.
        root = plistlib.loads(ioreg_root(locked=False, uid=UID).encode())
        root["IOConsoleUsers"].append({"kCGSSessionUserIDKey": 502, "kCGSSessionOnConsoleKey": False,
                                       "CGSSessionScreenIsLocked": True})
        self.assertIs(parse_lock(plistlib.dumps(root).decode(), UID), False)

    def test_no_session_of_ours_uses_the_console_flag(self):
        self.assertIs(parse_lock(ioreg_root(locked=False, uid=502), UID), False)
        self.assertIs(parse_lock(ioreg_root(locked=True, uid=502), UID), True)

    def test_unreadable_is_unknown(self):
        for text in ["", "not a plist", "<plist><array/></plist>", plistlib.dumps({"IOObjectClass": "x"}).decode(),
                     plistlib.dumps(["IOConsoleLocked"]).decode()]:
            with self.subTest(text=text[:40]):
                self.assertIsNone(parse_lock(text, UID))


class FixedRunner:
    def __init__(self, stdout: str, returncode: int = 0):
        self.stdout, self.returncode, self.calls = stdout, returncode, 0

    def run(self, argv, env=None, timeout=10.0):
        check_allowed(argv, allow_writes=False)  # a read: allowed without --live
        self.calls += 1
        return Completed(self.returncode, self.stdout, "")


class LockWatchTest(unittest.TestCase):
    def test_argv_is_the_allowlisted_read(self):
        check_allowed(LOCK_ARGV, allow_writes=False)

    def test_polls_on_its_interval_and_reports_changes(self):
        runner = FixedRunner(ioreg_root(locked=False, uid=UID))
        watch = LockWatch(runner, uid=UID, interval=3.0)
        self.assertTrue(watch.poll(100.0))  # unknown to unlocked
        self.assertIs(watch.locked, False)
        self.assertFalse(watch.poll(101.0))
        self.assertEqual(runner.calls, 1)
        runner.stdout = ioreg_root(locked=True, uid=UID)
        self.assertTrue(watch.poll(103.0))
        self.assertIs(watch.locked, True)
        self.assertEqual(runner.calls, 2)

    def test_a_failed_read_is_unknown_and_logged_once(self):
        runner = FixedRunner("", returncode=127)
        watch = LockWatch(runner, uid=UID)
        with self.assertLogs("helm.bridge.lock", level="INFO") as logs:
            watch.read(1.0)
            watch.read(5.0)
        self.assertIsNone(watch.locked)
        self.assertEqual(len(logs.records), 1)

    def test_a_runner_os_error_is_unknown_not_raised(self):
        class Failing:
            def run(self, argv, env=None, timeout=10.0):
                raise PermissionError(13, "Permission denied", argv[0])

        watch = LockWatch(Failing(), uid=UID)
        with self.assertLogs("helm.bridge.lock", level="INFO"):
            watch.read(1.0)
        self.assertIsNone(watch.locked)

    def test_a_refused_command_still_raises(self):
        class Refusing:
            def run(self, argv, env=None, timeout=10.0):
                raise CommandRefused("not on the bridge allowlist")

        with self.assertRaises(CommandRefused):
            LockWatch(Refusing(), uid=UID).read(1.0)


if __name__ == "__main__":
    unittest.main()
