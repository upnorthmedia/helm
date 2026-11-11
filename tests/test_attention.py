import unittest

from helm.bridge.attention import Attention


class AttentionTest(unittest.TestCase):
    def test_baseline_is_seen_so_standing_items_stay_calm(self):
        att = Attention()
        att.observe(["a", "b"], now=0)
        self.assertEqual(att.state(True), "calm")
        self.assertFalse(att.take_chime())

    def test_new_item_is_unseen_and_chimes_once(self):
        att = Attention()
        att.observe(["a"], now=0)
        att.observe(["a", "b"], now=1)
        self.assertEqual(att.state(True), "new")
        self.assertTrue(att.is_unseen("b"))
        self.assertFalse(att.is_unseen("a"))
        self.assertTrue(att.take_chime())
        self.assertFalse(att.take_chime())
        att.observe(["a", "b"], now=2)  # still present, not new again
        self.assertFalse(att.take_chime())

    def test_touch_marks_seen(self):
        att = Attention()
        att.observe([], now=0)
        att.observe(["a"], now=1)
        att.mark_all_seen()
        self.assertEqual(att.state(True), "calm")
        self.assertEqual(att.unseen_count, 0)

    def test_item_that_leaves_is_dropped_and_returns_as_new(self):
        att = Attention()
        att.observe([], now=0)
        att.observe(["a"], now=1)
        att.observe([], now=2)
        self.assertEqual(att.unseen_count, 0)
        att.observe(["a"], now=3)
        self.assertTrue(att.is_unseen("a"))
        self.assertEqual(att.first_seen("a"), 3)

    def test_ledger_edge_re_raises_a_present_item(self):
        att = Attention()
        att.observe(["a"], now=0)
        att.observe(["a"], now=1, edges={"a", "not-present"})
        self.assertTrue(att.is_unseen("a"))
        self.assertEqual(att.unseen_count, 1)

    def test_unknown_when_link_is_down_even_with_new_items(self):
        att = Attention()
        att.observe([], now=0)
        att.observe(["a"], now=1)
        self.assertEqual(att.state(False), "unknown")


if __name__ == "__main__":
    unittest.main()
