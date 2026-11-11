"""Shared contract between the Helm host bridge and the Helm device (or its simulator).

The bridge sends a full Model to the device every 2 seconds and whenever it
changes. The device sends Events back. Neither side depends on how the other
moves bytes: that is the Transport's job.

Fields added after the first release (Link.away, Link.mac_locked,
Item.project, Model.usage, Model.context, Key.ref) have defaults, and both decoders (helm/wire/codec.py and firmware/core) treat
them as optional, so a newer bridge and an older device, or the reverse, still
work together: each side skips JSON keys it does not know.

One exception is deliberate. Key.ref names the item the deck showed, and the
bridge acts only on that ref, never on the last `select` it received (a lost
`select` frame would turn a held YES onto another item). So a deck from before
Key.ref still shows models and still sends keys, but every answer key and SHOW
ME it sends is refused until its firmware is updated.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Literal, Optional, Union

Attention = Literal["calm", "new", "unknown"]
ItemKind = Literal["decision", "pr_ready", "worker_problem", "herdr_blocked"]
Color = Literal["red", "amber", "blue", "green"]
Action = Literal["yes", "later", "hold", "focus"]
Checks = Literal["green", "red", "pending", "unknown"]
ResultState = Literal["queued", "replied", "failed"]
KeyName = Literal["yes", "later", "hold", "focus"]
KeyPhase = Literal["down", "up", "held"]


# Bridge to device.


@dataclass
class Link:
    bridge_ok: bool
    firstmate_can_receive: Optional[bool]
    posture: Optional[str]
    stale_reason: Optional[str]
    # Firstmate's posture is away: the deck mutes chimes and locks YES, LATER,
    # and HOLD; SHOW ME still works. The bridge also drops those actions from
    # every item, so a device that predates this field locks too. In quiet
    # mode this stays false (firstmate treats a quiet captain as present);
    # the bridge mutes by sending no chime.
    away: bool = False
    # The Mac's login session is locked (or switched to another user): the
    # deck locks every key, SHOW ME included, since nobody should approve or
    # focus panes on a locked Mac. The bridge drops every action too.
    mac_locked: bool = False


@dataclass
class Counts:
    decisions: int = 0
    working: int = 0
    queued: int = 0
    prs_ready: int = 0
    landed_today: int = 0
    herdr_working: int = 0
    herdr_blocked: int = 0


@dataclass
class Item:
    ref: str  # stable id the bridge understands; the device echoes it in `select` and `key`
    kind: ItemKind
    color: Color
    short_id: str
    age_s: int
    unseen: bool
    home: str
    detail: str  # full text, shown only on a knob press
    actions: list[Action] = field(default_factory=list)
    pr_url: Optional[str] = None
    checks: Optional[Checks] = None
    project: Optional[str] = None  # repo name when known; the knob can filter the list by it


@dataclass
class Usage:
    """What is left of the Claude 5 hour and weekly usage windows, from quota-axi.

    None means unknown (quota-axi missing, failing, or not signed in), never full.
    """

    five_hour_left: Optional[int] = None  # percent left, 0 to 100
    five_hour_resets_s: Optional[int] = None  # seconds until the window resets
    week_left: Optional[int] = None
    week_resets_s: Optional[int] = None


@dataclass
class Context:
    """How full the herdr agents' context windows are, from each agent's `tokens.context`.

    None means unknown (herdr unavailable, or no agent reports a percent of its
    window), never empty. top_used and near_limit are known or unknown together.
    """

    top_used: Optional[int] = None  # percent of its window the fullest agent uses, 0 to 100
    top_agent: Optional[str] = None  # that agent's pane title
    near_limit: Optional[int] = None  # agents at or above the bridge's near-limit percent


@dataclass
class Result:
    request_id: str
    state: ResultState
    text: str


@dataclass
class Model:
    seq: int  # +1 on every model sent; a gap tells the device a frame was lost
    link: Link
    attention: Attention
    unseen: int
    counts: Counts
    items: list[Item] = field(default_factory=list)
    result: Optional[Result] = None
    chime: bool = False  # play one chime for this model, once
    usage: Usage = field(default_factory=Usage)
    context: Context = field(default_factory=Context)


def model_to_dict(model: Model) -> dict:
    return asdict(model)


def model_from_dict(data: dict) -> Model:
    return Model(
        seq=data["seq"],
        link=Link(**data["link"]),
        attention=data["attention"],
        unseen=data["unseen"],
        counts=Counts(**data["counts"]),
        items=[Item(**item) for item in data.get("items", [])],
        result=Result(**data["result"]) if data.get("result") else None,
        chime=data.get("chime", False),
        usage=Usage(**data["usage"]) if data.get("usage") else Usage(),
        context=Context(**data["context"]) if data.get("context") else Context(),
    )


# Device to bridge.


PRODUCT = "helm"


@dataclass
class Hello:
    fw: str
    caps: list[str] = field(default_factory=list)
    # Names the product, as the Harness Pro's hello does ("harness" there). The
    # frame magic is the Harness one (D9), so this is what tells a Harness
    # daemon to let go of the port and tells the bridge it found a Helm deck.
    product: str = PRODUCT


@dataclass
class Key:
    key: KeyName
    phase: KeyPhase  # held = the 1 s hold completed
    # The ref of the item the deck showed for this key (the selection, or the
    # held item), or None when nothing was selected. The bridge acts on this
    # ref only, so a lost `select` cannot move an answer onto another item.
    ref: Optional[str] = None


@dataclass
class Knob:
    delta: int


@dataclass
class KnobPress:
    long: bool


@dataclass
class Select:
    ref: str


@dataclass
class Seen:
    """Any touch on the deck."""


@dataclass
class Resync:
    """A model frame was lost (seq gap or bad CRC): send the full model now.

    Not a touch, so it must not mark items seen. The device sends it at most
    once per 2 s, as the Harness Pro does.
    """


Event = Union[Hello, Key, Knob, KnobPress, Select, Seen, Resync]

EVENT_TYPES: dict[str, type] = {
    "hello": Hello,
    "key": Key,
    "knob": Knob,
    "knob_press": KnobPress,
    "select": Select,
    "seen": Seen,
    "resync": Resync,
}
_EVENT_NAMES = {cls: name for name, cls in EVENT_TYPES.items()}


def event_type(event: Event) -> str:
    return _EVENT_NAMES[type(event)]


def event_to_dict(event: Event) -> dict:
    return {"type": event_type(event), **asdict(event)}


def event_from_dict(data: dict) -> Event:
    cls = EVENT_TYPES[data["type"]]
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in names})


class Transport:
    """Moves Models to the device and Events back. Implementations: helm.wire (serial or pty), tests (memory)."""

    def send_model(self, model: Model) -> None:
        raise NotImplementedError

    def poll_events(self, timeout_s: float) -> list[Event]:
        raise NotImplementedError
