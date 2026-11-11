import json
import threading
import time
import unittest

from helm.bridge.commands import Completed
from helm.bridge.usage import USAGE_ARGV, USAGE_MAX_AGE_S, UsagePoller, Window, parse_quota
from helm.contract import Usage
from tests.helpers import QUOTA_OK


def quota(**changes) -> dict:
    data = json.loads(json.dumps(QUOTA_OK))
    data["providers"][0].update(changes)
    return data


class ParseQuotaTest(unittest.TestCase):
    def test_fresh_reading(self):
        windows, reason = parse_quota(json.dumps(QUOTA_OK))
        self.assertIsNone(reason)
        self.assertEqual(windows["five_hour"].left, 62)
        self.assertEqual(windows["week"].left, 40)
        self.assertEqual(windows["week"].resets_at, 1794441600.0)  # 2026-11-12T00:00:00Z
        self.assertEqual(set(windows), {"five_hour", "week"})  # model windows are not the gauge

    def test_anything_short_of_fresh_is_unknown(self):
        cases = {
            "not json": "quota-axi: something broke",
            "no providers": json.dumps({"providers": []}),
            "auth required": json.dumps(quota(windows=[], state={"status": "auth_required", "stale": False,
                                                                 "error": "keychain_prompt_required"})),
            "cached": json.dumps(quota(state={"status": "stale", "stale": True})),
            "rate limited": json.dumps(quota(state={"status": "rate_limited", "stale": False})),
        }
        for name, stdout in cases.items():
            with self.subTest(name):
                windows, reason = parse_quota(stdout)
                self.assertEqual(windows, {})
                self.assertTrue(reason)
        self.assertIn("keychain_prompt_required", parse_quota(cases["auth required"])[1])

    def test_bad_windows_are_dropped_not_guessed(self):
        data = quota()
        data["providers"][0]["windows"][0]["percentRemaining"] = 140
        data["providers"][0]["windows"][1]["percentRemaining"] = True
        windows, reason = parse_quota(json.dumps(data))
        self.assertEqual(windows, {})
        self.assertIn("five_hour or week", reason)
        data["providers"][0]["windows"][1] = {"id": "seven_day", "percentRemaining": 0, "resetsAt": "soon"}
        windows, reason = parse_quota(json.dumps(data))
        self.assertEqual(windows, {"week": Window(0, None)})
        self.assertIn("five_hour", reason)


def wait_for(condition, timeout: float = 5.0) -> bool:
    """Wait for something the poller thread does; the thread may not have run yet."""
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.01)
    return condition()


class Runner:
    def __init__(self, stdout: str = json.dumps(QUOTA_OK), rc: int = 0, gate: threading.Event | None = None):
        self.stdout, self.rc, self.gate = stdout, rc, gate
        self.calls = 0

    def run(self, argv, env=None, timeout=10.0):
        assert list(argv) == USAGE_ARGV
        self.calls += 1
        if self.gate:
            self.gate.wait(5)
        return Completed(self.rc, self.stdout if self.rc in (0, 1) else "", "" if self.rc == 0 else "boom")


class UsagePollerTest(unittest.TestCase):
    def test_reading_expires_to_unknown(self):
        poller = UsagePoller(Runner(), background=False)
        now = 1794400000.0
        self.assertTrue(poller.poll(now))
        self.assertEqual(poller.usage(now).five_hour_left, 62)
        self.assertEqual(poller.usage(now + USAGE_MAX_AGE_S + 1), Usage())

    def test_resets_never_go_negative(self):
        poller = UsagePoller(Runner(), background=False)
        now = 1794441600.0 + 10  # after both resets
        poller.poll(now)
        usage = poller.usage(now)
        self.assertEqual((usage.five_hour_resets_s, usage.week_resets_s), (0, 0))

    def test_resets_are_clamped_to_the_device_int32(self):
        data = quota()
        data["providers"][0]["windows"][1]["resetsAt"] = "2200-01-01T00:00:00Z"
        poller = UsagePoller(Runner(json.dumps(data)), background=False)
        poller.poll(0.0)
        self.assertEqual(poller.usage(0.0).week_resets_s, 2**31 - 1)

    def test_a_runner_exception_is_a_failed_read_and_polling_continues(self):
        class Raising(Runner):
            def run(self, argv, env=None, timeout=10.0):
                self.calls += 1
                raise OSError("fork failed")

        runner = Raising()
        poller = UsagePoller(runner, background=True, interval=10)
        poller.poll(0.0)
        wait_for(lambda: poller.poll(1.0) or poller.read_at is not None)  # takes in the finished read
        self.assertEqual(poller.usage(1.0), Usage())
        self.assertIn("fork failed", poller.reason)
        poller.poll(10.0)  # the next read starts on schedule
        self.assertTrue(wait_for(lambda: runner.calls == 2))

    def test_failure_replaces_the_last_reading(self):
        runner = Runner()
        poller = UsagePoller(runner, background=False, interval=10)
        poller.poll(0.0)
        runner.rc = 2  # a crash: no report
        self.assertTrue(poller.poll(10.0))
        self.assertEqual(poller.usage(10.0), Usage())
        self.assertIn("boom", poller.reason)

    def test_every_provider_failed_reads_the_report(self):
        # quota-axi exits 1 when every provider failed and still prints the report.
        runner = Runner(json.dumps(quota(windows=[], state={"status": "auth_required", "error": "keychain_prompt_required"})), rc=1)
        poller = UsagePoller(runner, background=False)
        poller.poll(0.0)
        self.assertEqual(poller.usage(0.0), Usage())
        self.assertEqual(poller.reason, "claude quota auth_required (keychain_prompt_required)")

    def test_background_read_does_not_block(self):
        gate = threading.Event()
        runner = Runner(gate=gate)
        poller = UsagePoller(runner, background=True)
        start = time.monotonic()
        self.assertFalse(poller.poll(0.0))  # started, not finished
        self.assertLess(time.monotonic() - start, 1)
        self.assertFalse(poller.poll(1.0))
        self.assertTrue(wait_for(lambda: runner.calls == 1))  # one read, blocked at the gate
        self.assertFalse(poller.poll(1.5))  # still running: no second read starts
        gate.set()
        poller._thread.join(5)
        self.assertTrue(poller.poll(2.0))
        self.assertEqual(poller.usage(2.0).week_left, 40)


if __name__ == "__main__":
    unittest.main()
