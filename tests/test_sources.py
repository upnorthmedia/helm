import json
import tempfile
import unittest
from pathlib import Path

from helm.bridge.sources import (
    JsonFile, LedgerTail, discover_homes, parse_herdr_agents, parse_ready, read_meta, status_line_epoch,
)
from tests.helpers import make_homes


class SourcesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.primary, self.mate = make_homes(self.tmp)

    def tearDown(self):
        self._tmp.cleanup()

    def test_discover_homes_reads_second_mate_roster(self):
        homes = discover_homes(self.primary)
        self.assertEqual([(h.label, h.path) for h in homes], [("primary", self.primary), ("mate1", self.mate)])

    def test_discover_homes_without_roster(self):
        (self.primary / "data" / "secondmates.md").unlink()
        self.assertEqual([h.label for h in discover_homes(self.primary)], ["primary"])

    def test_read_meta_and_rejects_path_tricks(self):
        self.assertEqual(read_meta(self.primary, "alpha-fix")["herdr_pane_id"], "wA:p2")
        self.assertEqual(read_meta(self.primary, "../primary/state/alpha-fix"), {})
        self.assertEqual(read_meta(self.primary, "missing"), {})

    def test_status_line_epoch_by_key(self):
        self.assertEqual(status_line_epoch(self.primary, "alpha-fix", "merge-alpha-12"), 1700000000)
        self.assertEqual(status_line_epoch(self.primary, "alpha-fix"), 1700000000)
        self.assertIsNone(status_line_epoch(self.primary, "alpha-fix", "nope"))

    def test_json_file_rereads_only_on_change(self):
        reader = JsonFile(self.primary / "state" / "home-summary.json")
        self.assertTrue(reader.poll())
        self.assertFalse(reader.poll())
        self.assertEqual(reader.data["counts"]["queued"], 4)
        missing = JsonFile(self.tmp / "nope.json")
        missing.poll()
        self.assertEqual(missing.error, "missing")

    def test_ledger_tail_skips_history_and_follows_appends(self):
        path = self.primary / "state" / "fleet-ledger.jsonl"
        tail = LedgerTail(path)
        self.assertEqual(tail.poll(), [])  # absent
        path.write_text(json.dumps({"v": 1, "ts": 1, "event": "task.status", "task": "old"}) + "\n")
        self.assertEqual(tail.poll(), [])  # first sight: history is skipped
        with path.open("a") as fh:
            fh.write(json.dumps({"v": 1, "ts": 2, "event": "task.status", "task": "new"}) + "\n")
            fh.write('{"v": 1, "ts": 3, "event": "task.st')  # partial line
        self.assertEqual([r["task"] for r in tail.poll()], ["new"])
        with path.open("a") as fh:
            fh.write('atus", "task": "later"}\nnot json\n')
        self.assertEqual([r["task"] for r in tail.poll()], ["later"])
        path.write_text("")  # truncated
        self.assertEqual(tail.poll(), [])
        path.write_text(json.dumps({"v": 1, "ts": 4, "event": "task.merged", "task": "after"}) + "\n")
        self.assertEqual([r["task"] for r in tail.poll()], ["after"])

    def test_parsers_reject_garbage(self):
        self.assertIsNone(parse_ready("not json"))
        self.assertIsNone(parse_ready('{"schema": "other"}'))
        self.assertIsNone(parse_herdr_agents('{"result": {}}'))
        self.assertEqual(parse_herdr_agents('{"result": {"agents": [{"pane_id": "a"}, 3]}}'), [{"pane_id": "a"}])


if __name__ == "__main__":
    unittest.main()
