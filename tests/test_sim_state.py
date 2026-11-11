import unittest

from helm import contract as c
from sim import fixtures
from sim.state import HOLD_S, LINK_TIMEOUT_S, Deck

T = 100.0


def busy_deck() -> Deck:
    deck = Deck()
    deck.on_model(fixtures.busy(seq=2), T)
    return deck


class Selection(unittest.TestCase):
    def test_first_model_selects_top_item(self):
        deck = busy_deck()
        self.assertEqual(deck.selected_ref, fixtures.DECISION.ref)
        self.assertEqual(deck.take_outbox(), [c.Select(ref=fixtures.DECISION.ref)])

    def test_knob_opens_list_then_moves(self):
        deck = busy_deck()
        deck.take_outbox()
        deck.knob(1, T)
        self.assertEqual(deck.screen, "list")
        deck.knob(1, T)
        self.assertEqual(deck.selected_ref, fixtures.PR_READY.ref)
        deck.knob(10, T)
        self.assertEqual(deck.selected_ref, fixtures.HERDR_BLOCKED.ref)
        out = deck.take_outbox()
        self.assertIn(c.Seen(), out)
        self.assertIn(c.Select(ref=fixtures.PR_READY.ref), out)
        self.assertEqual(out.count(c.Seen()), 1)  # once per model, not per touch

    def test_selection_survives_reorder_and_clamps_on_removal(self):
        deck = busy_deck()
        deck.knob(1, T)
        deck.knob(1, T)
        reordered = fixtures.model(3, [fixtures.WORKER_PROBLEM, fixtures.PR_READY])
        deck.on_model(reordered, T)
        self.assertEqual(deck.selected_ref, fixtures.PR_READY.ref)
        deck.on_model(fixtures.model(4, [fixtures.WORKER_PROBLEM]), T)
        self.assertEqual(deck.selected_ref, fixtures.WORKER_PROBLEM.ref)

    def test_full_text_only_after_knob_press(self):
        deck = busy_deck()
        deck.knob(1, T)
        self.assertEqual(deck.screen, "list")
        deck.knob_press(False, T)
        self.assertEqual(deck.screen, "detail")
        deck.knob_press(False, T)
        self.assertEqual(deck.screen, "list")

    def test_turning_up_from_the_first_row_goes_home(self):
        deck = busy_deck()
        deck.knob(1, T)
        deck.knob(2, T)
        deck.knob(-100, T)  # a fast turn stops at the top
        self.assertEqual((deck.screen, deck.selected_ref), ("list", fixtures.DECISION.ref))
        deck.take_outbox()
        deck.knob(-1, T)
        self.assertEqual((deck.screen, deck.selected_ref), ("home", fixtures.DECISION.ref))
        self.assertEqual(deck.take_outbox(), [c.Knob(delta=-1)])

    def test_empty_model_returns_home(self):
        deck = busy_deck()
        deck.knob(1, T)
        deck.knob_press(False, T)
        deck.on_model(fixtures.calm(seq=5), T)
        self.assertEqual(deck.screen, "home")
        self.assertIsNone(deck.selected_item())


class ProjectViews(unittest.TestCase):
    def test_knob_on_home_turns_through_views(self):
        deck = Deck()
        deck.on_model(fixtures.projects(seq=1), T)
        deck.take_outbox()
        self.assertEqual(deck.projects(), ["gizmo", "widget-api"])
        deck.knob(1, T)
        self.assertEqual((deck.screen, deck.view, deck.selected_ref), ("home", "gizmo", fixtures.PR_READY.ref))
        deck.knob(1, T)
        self.assertEqual((deck.view, deck.selected_ref), ("widget-api", fixtures.DECISION.ref))
        deck.knob(1, T)
        self.assertIsNone(deck.view)
        deck.knob(-1, T)
        self.assertEqual(deck.view, "widget-api")
        self.assertEqual(deck.take_outbox(), [
            c.Seen(), c.Knob(delta=1), c.Select(ref=fixtures.PR_READY.ref), c.Knob(delta=1),
            c.Select(ref=fixtures.DECISION.ref), c.Knob(delta=1), c.Knob(delta=-1),
        ])
        deck.knob(5, T)  # five steps over three views is two
        self.assertEqual(deck.view, "gizmo")

    def test_list_holds_only_the_view(self):
        deck = Deck()
        deck.on_model(fixtures.projects(seq=1), T)
        deck.knob(-1, T)  # all -> widget-api
        deck.knob_press(False, T)
        self.assertEqual(deck.screen, "list")
        self.assertEqual([i.ref for i in deck.visible], [fixtures.DECISION.ref, fixtures.WORKER_PROBLEM.ref])
        deck.knob(5, T)
        self.assertEqual(deck.selected_ref, fixtures.WORKER_PROBLEM.ref)
        deck.knob(-1, T)
        deck.knob(-1, T)
        self.assertEqual(deck.screen, "home")

    def test_view_falls_back_to_all_when_its_project_leaves(self):
        deck = Deck()
        deck.on_model(fixtures.projects(seq=1), T)
        deck.knob(-1, T)
        deck.screen = "list"
        deck.take_outbox()
        deck.on_model(fixtures.with_projects(fixtures.model(2, [fixtures.PR_READY, fixtures.HERDR_BLOCKED])), T)
        self.assertIsNone(deck.view)
        self.assertEqual((deck.screen, deck.selected_ref), ("list", fixtures.PR_READY.ref))
        self.assertEqual(deck.take_outbox(), [c.Select(ref=fixtures.PR_READY.ref)])

    def test_without_projects_a_turn_on_home_opens_the_list(self):
        deck = busy_deck()
        self.assertEqual(deck.projects(), [])
        deck.knob(1, T)
        self.assertEqual(deck.screen, "list")


class AwayMode(unittest.TestCase):
    def away_model(self, seq: int, chime: bool = False) -> c.Model:
        # Keep the acting keys in the items (the bridge drops them) to test the deck's own lock.
        m = fixtures.projects(seq)
        m.link = fixtures.LINK_AWAY
        m.chime = chime
        return m

    def test_away_mutes_chimes_and_locks_acting_keys(self):
        deck = Deck()
        deck.on_model(self.away_model(1, chime=True), T)
        self.assertEqual(deck.chimes, 0)
        self.assertIsNone(deck.link_down_reason(T))  # away is not a link problem
        self.assertEqual([k for k in ("yes", "later", "hold", "focus") if deck.key_lit(k, T)], ["focus"])
        deck.take_outbox()
        deck.key_down("yes", T)
        deck.tick(T + 2)
        self.assertEqual(deck.screen, "home")
        deck.key_down("focus", T + 2)
        deck.key_up("focus", T + 2.1)
        self.assertEqual(deck.take_outbox(), [c.Seen(), c.Key(key="focus", phase="down"), c.Key(key="focus", phase="up")])

    def test_going_away_mid_hold_cancels_it(self):
        deck = Deck()
        deck.on_model(fixtures.projects(1), T)
        deck.key_down("yes", T)
        deck.take_outbox()
        deck.on_model(self.away_model(2), T + 0.5)
        self.assertIsNone(deck.hold)
        self.assertEqual(deck.screen, "home")
        self.assertEqual(deck.take_outbox(), [c.Key(key="yes", phase="up")])
        deck.tick(T + 2)
        self.assertIsNone(deck.pending)


    def test_locked_mac_darkens_every_key_but_still_chimes(self):
        deck = Deck()
        m = fixtures.projects(1)  # the items still offer every action, to test the deck's own lock
        m.link = fixtures.LINK_LOCKED
        m.chime = True
        deck.on_model(m, T)
        self.assertEqual(deck.chimes, 1)
        self.assertIsNone(deck.link_down_reason(T))
        self.assertFalse(any(deck.key_lit(k, T) for k in ("yes", "later", "hold", "focus")))
        deck.take_outbox()
        deck.key_down("yes", T)
        deck.key_down("focus", T)
        deck.key_up("focus", T)
        self.assertEqual(deck.take_outbox(), [c.Seen()])

    def test_locking_mid_hold_cancels_it(self):
        deck = Deck()
        deck.on_model(fixtures.projects(1), T)
        deck.key_down("yes", T)
        deck.take_outbox()
        locked = fixtures.projects(2)
        locked.link = fixtures.LINK_LOCKED
        deck.on_model(locked, T + 0.5)
        self.assertIsNone(deck.hold)
        self.assertEqual(deck.take_outbox(), [c.Key(key="yes", phase="up")])


class HoldToConfirm(unittest.TestCase):
    def test_full_hold_sends_held_and_shows_result(self):
        deck = busy_deck()
        deck.take_outbox()
        deck.key_down("yes", T)
        self.assertEqual(deck.screen, "confirm")
        deck.tick(T + HOLD_S / 2)
        self.assertAlmostEqual(deck.hold_progress(T + HOLD_S / 2), 0.5)
        deck.tick(T + HOLD_S)
        self.assertEqual(deck.screen, "result")
        out = deck.take_outbox()
        self.assertEqual(out[-2:], [c.Key(key="yes", phase="down"), c.Key(key="yes", phase="held")])
        deck.key_up("yes", T + HOLD_S + 0.1)  # the release after a completed hold sends nothing
        self.assertEqual(deck.take_outbox(), [])

    def test_early_release_cancels(self):
        deck = busy_deck()
        deck.knob(1, T)
        deck.take_outbox()
        deck.key_down("later", T)
        deck.tick(T + 0.4)
        deck.key_up("later", T + 0.5)
        deck.tick(T + 2)
        self.assertEqual(deck.screen, "list")
        self.assertEqual(deck.take_outbox(), [c.Key(key="later", phase="down"), c.Key(key="later", phase="up")])

    def test_hold_targets_item_selected_at_press(self):
        deck = busy_deck()
        deck.key_down("hold", T)
        # The list reorders under the held key; the hold still names the original item.
        deck.on_model(fixtures.model(3, [fixtures.PR_READY, fixtures.DECISION]), T + 0.5)
        deck.tick(T + HOLD_S)
        self.assertEqual(deck.pending.item.ref, fixtures.DECISION.ref)

    def test_hold_cancels_when_held_item_leaves_the_list(self):
        deck = busy_deck()
        deck.take_outbox()
        deck.key_down("yes", T)
        # The held item is gone; the bridge must not get a held key for whatever is selected next.
        deck.on_model(fixtures.model(3, [fixtures.PR_READY]), T + 0.5)
        deck.tick(T + HOLD_S)
        deck.key_up("yes", T + HOLD_S + 0.1)
        self.assertIsNone(deck.hold)
        self.assertIsNone(deck.pending)
        self.assertEqual(deck.screen, "home")
        self.assertEqual(
            deck.take_outbox(),
            [c.Seen(), c.Key(key="yes", phase="down"), c.Key(key="yes", phase="up"), c.Select(ref=fixtures.PR_READY.ref)],
        )

    def test_dark_key_does_nothing(self):
        deck = Deck()
        deck.on_model(fixtures.model(1, [fixtures.HERDR_BLOCKED]), T)
        deck.take_outbox()
        deck.key_down("yes", T)
        deck.tick(T + 2)
        self.assertEqual(deck.screen, "home")
        self.assertEqual(deck.take_outbox(), [])

    def test_show_me_is_a_tap(self):
        deck = busy_deck()
        deck.take_outbox()
        deck.key_down("focus", T)
        deck.key_up("focus", T + 0.1)
        self.assertEqual(deck.screen, "home")
        self.assertEqual(deck.take_outbox(), [c.Seen(), c.Key(key="focus", phase="down"), c.Key(key="focus", phase="up")])

    def test_result_follows_newer_model_only(self):
        deck = busy_deck()
        old = fixtures.busy(seq=2)
        old.result = c.Result(request_id="old", state="replied", text="stale reply")
        deck.on_model(old, T)
        deck.key_down("yes", T)
        deck.tick(T + HOLD_S)
        self.assertIsNone(deck.pending.result)  # a result from before the press is not ours
        queued = fixtures.busy(seq=3)
        queued.result = c.Result(request_id="r1", state="queued", text="Queued")
        deck.on_model(queued, T + 1.5)
        self.assertEqual(deck.pending.result.state, "queued")
        replied = fixtures.busy(seq=4)
        replied.result = c.Result(request_id="r1", state="replied", text="done")
        deck.on_model(replied, T + 2)
        deck.tick(T + 2 + 9)
        self.assertEqual(deck.screen, "home")


class AttentionAndLink(unittest.TestCase):
    def test_link_timeout_reads_unknown_and_darkens_keys(self):
        deck = busy_deck()
        self.assertEqual(deck.attention(T + 1), "new")
        self.assertTrue(deck.key_lit("yes", T + 1))
        self.assertEqual(deck.attention(T + LINK_TIMEOUT_S + 0.1), "unknown")
        self.assertFalse(deck.key_lit("yes", T + LINK_TIMEOUT_S + 0.1))

    def test_firstmate_not_receiving_is_unknown(self):
        deck = Deck()
        deck.on_model(fixtures.stale(seq=1), T)
        self.assertEqual(deck.attention(T), "unknown")
        self.assertEqual(deck.link_down_reason(T), "firstmate is not listening")

    def test_unknown_before_any_model(self):
        self.assertEqual(Deck().attention(T), "unknown")

    def test_chime_once_per_flagged_model_unless_muted(self):
        deck = busy_deck()
        self.assertEqual(deck.chimes, 1)
        deck.on_model(fixtures.model(3, [fixtures.DECISION]), T)  # a resend without the flag
        self.assertEqual(deck.chimes, 1)
        deck.knob_press(True, T)
        self.assertTrue(deck.muted)
        deck.on_model(fixtures.busy(seq=4), T)
        self.assertEqual(deck.chimes, 1)

    def test_landing_starts_green_sweep(self):
        deck = busy_deck()
        deck.on_model(fixtures.model(3, [], landed_today=4), T + 1)
        self.assertGreater(deck.sweep_until, T + 1)


if __name__ == "__main__":
    unittest.main()
