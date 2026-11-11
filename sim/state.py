"""What the deck is doing, independent of any window.

The deck is thin: it draws the latest Model and reports
key and knob events. This class holds the little state that is local to the
device: which screen is up, which item is selected, a key being held, mute,
and whether the bridge has gone quiet. Inputs come in as method calls with a
timestamp; events for the bridge collect in `outbox`. Firmware later ports
this logic to C++.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from helm import contract as c

HOLD_S = 1.0  # a YES / LATER / HOLD press must be held this long (D14)
LINK_TIMEOUT_S = 10.0  # no model this long reads as unknown
SWEEP_S = 2.0  # green sweep when something lands
RESULT_LINGER_S = 8.0  # a final result stays up this long, then the deck goes home
FIRMWARE = "helm-sim-0.1"
CAPS = ["screen-1280x720", "keys-4", "knob", "lightbar-8", "chime"]

HOLD_KEYS = ("yes", "later", "hold")
KEY_LABELS = {"yes": "YES", "later": "LATER", "hold": "HOLD", "focus": "SHOW ME"}


@dataclass
class Hold:
    key: str
    item: c.Item
    started: float
    return_to: str


@dataclass
class Pending:
    key: str
    item: c.Item
    sent_at: float
    seq_after: int  # only a model newer than this can carry our result
    result: c.Result | None = None
    final_at: float | None = None


@dataclass
class Deck:
    model: c.Model | None = None
    last_model_at: float | None = None
    screen: str = "home"
    selected_ref: str | None = None  # always an item in the view
    view: str | None = None  # project the list is filtered to; None is the "all" view
    detail_scroll: int = 0
    muted: bool = False
    hold: Hold | None = None
    pending: Pending | None = None
    sweep_until: float = 0.0
    chimes: int = 0  # chimes requested and not yet played by the UI
    outbox: list[c.Event] = field(default_factory=list)
    _seen_sent_for: int | None = None

    # Link and attention

    def link_down_reason(self, now: float) -> str | None:
        if self.model is None or self.last_model_at is None:
            return "waiting for the bridge"
        if now - self.last_model_at > LINK_TIMEOUT_S:
            return "no word from the bridge for 10 s"
        link = self.model.link
        if not link.bridge_ok:
            return link.stale_reason or "the bridge reports a problem"
        if link.firstmate_can_receive is not True:
            return link.stale_reason or "firstmate is not listening"
        return None

    def attention(self, now: float) -> str:
        if self.link_down_reason(now) is not None:
            return "unknown"
        assert self.model is not None
        return self.model.attention

    # Items and keys

    @property
    def items(self) -> list[c.Item]:
        """Every item in the model, whatever the view."""
        return self.model.items if self.model else []

    @property
    def visible(self) -> list[c.Item]:
        """The items in the project view, in model order."""
        return [i for i in self.items if self.view is None or i.project == self.view]

    def projects(self) -> list[str]:
        """Each project the items name, sorted: the views after "all"."""
        return sorted({i.project for i in self.items if i.project})

    def selected_index(self) -> int | None:
        """The selection's position in the view."""
        for i, item in enumerate(self.visible):
            if item.ref == self.selected_ref:
                return i
        return None

    def selected_item(self) -> c.Item | None:
        i = self.selected_index()
        return self.visible[i] if i is not None else None

    @property
    def away(self) -> bool:
        return self.model is not None and self.model.link.away

    @property
    def mac_locked(self) -> bool:
        return self.model is not None and self.model.link.mac_locked

    def key_lit(self, key: str, now: float) -> bool:
        """A key is lit only when its action applies to the selected item, never
        while the Mac is locked, and YES / LATER / HOLD never while firstmate is away."""
        if self.hold is not None:
            return key == self.hold.key
        if self.screen == "result" or self.link_down_reason(now) is not None or self.mac_locked:
            return False
        if key in HOLD_KEYS and self.away:
            return False
        item = self.selected_item()
        return item is not None and key in item.actions

    # Inputs from the bridge

    def on_model(self, model: c.Model, now: float) -> None:
        previous = self.model
        self.model = model
        self.last_model_at = now
        if self.view is not None and self.view not in self.projects():
            self.view = None  # the view's project left: back to "all"
        if model.chime and not self.muted and not model.link.away:
            self.chimes += 1
        if self.hold is not None and (model.link.away or model.link.mac_locked):
            self._cancel_hold()  # going away, or the Mac locking, locks the keys
        if previous is not None and model.counts.landed_today > previous.counts.landed_today:
            self.sweep_until = now + SWEEP_S
        if self.hold is not None and self.selected_index() is None:
            # The held item left the list: cancel rather than let the hold land
            # on whatever gets selected next (the bridge acts on its last select).
            self._cancel_hold()
        if self.selected_index() is None:
            self._select(self.visible[0] if self.visible else None)
        if self.screen in ("list", "detail") and not self.visible:
            self.screen = "home"
        if self.screen == "detail" and self.selected_item() is None:
            self.screen = "list"
        p = self.pending
        if p is not None and model.result is not None and model.seq > p.seq_after:
            p.result = model.result
            if model.result.state != "queued" and p.final_at is None:
                p.final_at = now

    # Inputs from the controls

    def knob(self, delta: int, now: float) -> None:
        if delta == 0:
            return
        self._touch()
        self.outbox.append(c.Knob(delta=delta))
        if self.hold is not None:
            return
        if self.screen == "result":
            self._leave_result()
        elif self.screen == "home":
            if self.projects():
                self._turn_views(delta)
            elif self.visible:
                self.screen = "list"
        elif self.screen == "list":
            self._move_selection(delta)
        elif self.screen == "detail":
            self.detail_scroll = max(0, self.detail_scroll + delta)

    def knob_press(self, long: bool, now: float) -> None:
        self._touch()
        self.outbox.append(c.KnobPress(long=long))
        if long:
            self.muted = not self.muted
            return
        if self.hold is not None:
            return
        if self.screen == "home":
            if self.visible:
                self.screen = "list"
        elif self.screen == "list":
            if self.selected_item() is not None:
                self.screen = "detail"
                self.detail_scroll = 0
        elif self.screen == "detail":
            self.screen = "list"
        elif self.screen == "result":
            self._leave_result()

    def key_down(self, key: str, now: float) -> None:
        self._touch()
        if not self.key_lit(key, now) or self.hold is not None:
            return
        item = self.selected_item()
        assert item is not None
        self.outbox.append(c.Key(key=key, phase="down"))
        if key in HOLD_KEYS:
            self.hold = Hold(key=key, item=item, started=now, return_to=self.screen)
            self.screen = "confirm"

    def key_up(self, key: str, now: float) -> None:
        hold = self.hold
        if key == "focus":
            if hold is None and self.key_lit("focus", now):
                self.outbox.append(c.Key(key="focus", phase="up"))
            return
        if hold is None or hold.key != key:
            return
        # Released before the fill bar completed: nothing is sent but the up.
        self._cancel_hold()

    def tick(self, now: float) -> None:
        hold = self.hold
        if hold is not None and now - hold.started >= HOLD_S:
            self.hold = None
            self.outbox.append(c.Key(key=hold.key, phase="held"))
            self.pending = Pending(
                key=hold.key,
                item=hold.item,
                sent_at=now,
                seq_after=self.model.seq if self.model else -1,
            )
            self.screen = "result"
        p = self.pending
        if self.screen == "result" and p is not None and p.final_at is not None:
            if now - p.final_at >= RESULT_LINGER_S:
                self._leave_result()

    def hold_progress(self, now: float) -> float:
        if self.hold is None:
            return 0.0
        return min(1.0, (now - self.hold.started) / HOLD_S)

    # Helpers

    def _touch(self) -> None:
        """Any touch marks new items seen, once per model."""
        m = self.model
        if m is not None and m.unseen > 0 and self._seen_sent_for != m.seq:
            self._seen_sent_for = m.seq
            self.outbox.append(c.Seen())

    def _select(self, item: c.Item | None) -> None:
        ref = item.ref if item else None
        if ref == self.selected_ref:
            return
        self.selected_ref = ref
        if ref is not None:
            self.outbox.append(c.Select(ref=ref))

    def _cancel_hold(self) -> None:
        hold = self.hold
        assert hold is not None
        self.hold = None
        self.screen = hold.return_to
        self.outbox.append(c.Key(key=hold.key, phase="up"))

    def _move_selection(self, delta: int) -> None:
        """Move within the view; turning up from the first row goes back to Home."""
        visible = self.visible
        if not visible:
            return
        i = self.selected_index() or 0
        if i == 0 and delta < 0:
            self.screen = "home"
            return
        i = max(0, min(len(visible) - 1, i + delta))
        self._select(visible[i])

    def _turn_views(self, delta: int) -> None:
        """Step through all, then each project in order, and select the first item in the new view."""
        views: list[str | None] = [None, *self.projects()]
        at = views.index(self.view) if self.view in views else 0
        self.view = views[(at + delta) % len(views)]
        self._select(self.visible[0] if self.visible else None)

    def _leave_result(self) -> None:
        self.pending = None
        self.screen = "home"

    def take_outbox(self) -> list[c.Event]:
        out, self.outbox = self.outbox, []
        return out
