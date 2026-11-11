import unittest

from helm.contract import (
    Counts, Hello, Item, Key, Knob, KnobPress, Link, Model, Result, Seen, Select,
    event_from_dict, event_to_dict, model_from_dict, model_to_dict,
)
from helm.bridge.commands import CommandRefused, Runner, check_allowed


class ContractTest(unittest.TestCase):
    def test_model_round_trips_through_dicts(self):
        model = Model(
            seq=3,
            link=Link(True, True, "present", None),
            attention="new",
            unseen=1,
            counts=Counts(decisions=2, herdr_blocked=1),
            items=[Item("decision|primary|a|b", "decision", "red", "a/b", 5, True, "primary", "text",
                        ["yes", "focus"], "https://github.com/x/y/pull/1", "green")],
            result=Result("r1", "queued", "queued"),
            chime=True,
        )
        self.assertEqual(model_from_dict(model_to_dict(model)), model)

    def test_events_round_trip_with_type_tag(self):
        for event in (Hello("1.0", ["keys"]), Key("yes", "held"), Knob(-2), KnobPress(True), Select("x"), Seen()):
            data = event_to_dict(event)
            self.assertIn("type", data)
            self.assertEqual(event_from_dict(data), event)
        self.assertEqual(event_to_dict(KnobPress(False)), {"type": "knob_press", "long": False})


class AllowlistTest(unittest.TestCase):
    def test_reads_are_allowed_without_live(self):
        check_allowed(["/h/bin/fm-inbox.sh", "ready"], allow_writes=False)
        check_allowed(["/h/bin/fm-inbox.sh", "receipts"], allow_writes=False)
        check_allowed(["herdr", "agent", "list"], allow_writes=False)
        check_allowed(["/usr/sbin/ioreg", "-n", "Root", "-d1", "-a"], allow_writes=False)

    def test_only_the_root_read_of_ioreg(self):
        for argv in (["ioreg", "-l"], ["ioreg", "-n", "IODisplayWrangler"], ["ioreg"]):
            with self.assertRaises(CommandRefused):
                check_allowed(argv, allow_writes=True)

    def test_writes_need_live(self):
        for argv in (["/h/bin/fm-inbox.sh", "note", "--", "x"], ["/h/bin/fm-inbox.sh", "announce", "n"],
                     ["herdr", "agent", "focus", "w:p1"]):
            with self.assertRaises(CommandRefused):
                check_allowed(argv, allow_writes=False)
            check_allowed(argv, allow_writes=True)

    def test_never_called_commands_are_refused_even_live(self):
        # Commands the bridge must never run (helm/bridge/commands.py).
        for argv in (
            ["/h/bin/fm-wake-drain.sh"],
            ["/h/bin/fm-inbox.sh", "drain", "--ack", "x"],
            ["/h/bin/fm-send.sh", "task", "hi"],
            ["/h/bin/fm-control.sh"],
            ["/h/bin/fm-pr-merge.sh", "url"],
            ["/h/bin/fm-teardown.sh"],
            ["/h/bin/fm-home-summary-refresh.sh"],
            ["tasks-axi"],
            ["herdr", "agent", "send-text", "w:p1", "y"],
            ["herdr", "agent", "prompt"],
            ["herdr", "pane", "send-keys"],
            ["herdr", "agent"],
            [],
        ):
            with self.assertRaises(CommandRefused, msg=argv):
                check_allowed(argv, allow_writes=True)

    def test_runner_refuses_before_spawning(self):
        with self.assertRaises(CommandRefused):
            Runner(allow_writes=False).run(["herdr", "agent", "focus", "w:p1"])

    def test_runner_reports_missing_program(self):
        done = Runner().run(["/nonexistent/bin/fm-inbox.sh", "ready"])
        self.assertEqual(done.returncode, 127)


if __name__ == "__main__":
    unittest.main()
