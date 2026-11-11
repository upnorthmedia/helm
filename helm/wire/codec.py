"""Contract messages to frame payloads and back.

Every Helm message rides in a TYPE_JSON frame: compact UTF-8 JSON with a "t"
discriminator, the same convention the Harness Pro cable uses. "model" goes
bridge to device; "hello", "key", "knob", "knob_press", "select" and "seen" go
device to bridge, plus "resync" (a lost model; send it again now). Decoding validates shapes and enum values, because
everything arriving on a port is untrusted.
"""

from __future__ import annotations

import copy
import json
from dataclasses import asdict
from typing import Any, get_args

from helm import contract as c
from helm.wire import frame

ATTENTION = get_args(c.Attention)
ITEM_KINDS = get_args(c.ItemKind)
COLORS = get_args(c.Color)
ACTIONS = get_args(c.Action)
CHECKS = get_args(c.Checks)
RESULT_STATES = get_args(c.ResultState)
KEY_PHASES = get_args(c.KeyPhase)


class DecodeError(ValueError):
    pass


def _dumps(obj: dict[str, Any]) -> bytes:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def encode_model(model: c.Model) -> bytes:
    """Return a complete frame. Raises frame.FrameTooLarge over 8192 bytes."""
    return frame.encode(frame.TYPE_JSON, _dumps({"t": "model", **asdict(model)}))


DETAIL_CAPS = (1200, 600, 300, 120, 0)  # bytes of detail kept per item, tried in order


def _payload_len(model: c.Model) -> int:
    return len(_dumps({"t": "model", **asdict(model)}))


def _cut(text: str, limit: int) -> str:
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text
    if limit == 0:
        return ""
    return raw[: max(0, limit - 3)].decode("utf-8", "ignore").rstrip() + "..."


def fit_model(model: c.Model) -> c.Model:
    """Return a copy of `model` small enough for one frame.

    The frame carries at most 8192 bytes. Shorten each item's detail text
    first (the full text is only shown on a knob press), then drop items from
    the end; the bridge sorts unseen items first, and the counts stay as they
    are, so the screen still says how many there are.
    """
    if _payload_len(model) <= frame.MAX_PAYLOAD:
        return model
    fitted = copy.deepcopy(model)
    for cap in DETAIL_CAPS:
        for item, original in zip(fitted.items, model.items):
            item.detail = _cut(original.detail, cap)
        if _payload_len(fitted) <= frame.MAX_PAYLOAD:
            return fitted
    while fitted.items and _payload_len(fitted) > frame.MAX_PAYLOAD:
        fitted.items.pop()
    return fitted


def encode_event(event: c.Event) -> bytes:
    tag = c.event_type(event)
    return frame.encode(frame.TYPE_JSON, _dumps({"t": tag, **asdict(event)}))


def _load(payload: bytes) -> dict[str, Any]:
    try:
        obj = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DecodeError(f"payload is not JSON: {exc}") from exc
    if not isinstance(obj, dict) or not isinstance(obj.get("t"), str):
        raise DecodeError("payload is not an object with a string 't'")
    return obj


def _get(obj: dict[str, Any], key: str, kind: type | tuple[type, ...], *, optional: bool = False) -> Any:
    if key not in obj or obj[key] is None:
        if optional:
            return None
        raise DecodeError(f"missing {key!r}")
    value = obj[key]
    # bool is an int subclass; never accept it where an int is meant.
    if kind is int and isinstance(value, bool):
        raise DecodeError(f"{key!r} must be int")
    if not isinstance(value, kind):
        raise DecodeError(f"{key!r} has the wrong type")
    return value


def _enum(obj: dict[str, Any], key: str, allowed: tuple[str, ...], *, optional: bool = False) -> Any:
    value = _get(obj, key, str, optional=optional)
    if value is not None and value not in allowed:
        raise DecodeError(f"{key!r} is {value!r}, expected one of {allowed}")
    return value


def _obj(obj: dict[str, Any], key: str) -> dict[str, Any]:
    return _get(obj, key, dict)


def _model_from(obj: dict[str, Any]) -> c.Model:
    link = _obj(obj, "link")
    counts = _obj(obj, "counts")
    items = []
    for raw in _get(obj, "items", list):
        if not isinstance(raw, dict):
            raise DecodeError("item is not an object")
        actions = _get(raw, "actions", list)
        if any(a not in ACTIONS for a in actions):
            raise DecodeError(f"unknown action in {actions!r}")
        items.append(
            c.Item(
                ref=_get(raw, "ref", str),
                kind=_enum(raw, "kind", ITEM_KINDS),
                color=_enum(raw, "color", COLORS),
                short_id=_get(raw, "short_id", str),
                age_s=_get(raw, "age_s", int),
                unseen=_get(raw, "unseen", bool),
                home=_get(raw, "home", str),
                detail=_get(raw, "detail", str),
                actions=list(actions),
                pr_url=_get(raw, "pr_url", str, optional=True),
                checks=_enum(raw, "checks", CHECKS, optional=True),
                project=_get(raw, "project", str, optional=True),
            )
        )
    result = None
    if obj.get("result") is not None:
        raw = _obj(obj, "result")
        result = c.Result(
            request_id=_get(raw, "request_id", str),
            state=_enum(raw, "state", RESULT_STATES),
            text=_get(raw, "text", str),
        )
    return c.Model(
        seq=_get(obj, "seq", int),
        link=c.Link(
            bridge_ok=_get(link, "bridge_ok", bool),
            firstmate_can_receive=_get(link, "firstmate_can_receive", bool, optional=True),
            posture=_get(link, "posture", str, optional=True),
            stale_reason=_get(link, "stale_reason", str, optional=True),
            away=bool(_get(link, "away", bool, optional=True)),
            mac_locked=bool(_get(link, "mac_locked", bool, optional=True)),
        ),
        attention=_enum(obj, "attention", ATTENTION),
        unseen=_get(obj, "unseen", int),
        counts=c.Counts(**{name: _get(counts, name, int) for name in c.Counts.__dataclass_fields__}),
        items=items,
        result=result,
        chime=_get(obj, "chime", bool),
        usage=_usage_from(obj),
        context=_context_from(obj),
    )


# Inclusive bounds for each usage field. Left is a percentage; a reset is
# never in the past.
USAGE_BOUNDS = {
    "five_hour_left": (0, 100),
    "five_hour_resets_s": (0, None),
    "week_left": (0, 100),
    "week_resets_s": (0, None),
}


def _usage_from(obj: dict[str, Any]) -> c.Usage:
    """Absent or null is all unknown (a bridge from before the usage gauge)."""
    if obj.get("usage") is None:
        return c.Usage()
    raw = _obj(obj, "usage")
    values = {}
    for name, (lo, hi) in USAGE_BOUNDS.items():
        value = _get(raw, name, int, optional=True)
        if value is not None and (value < lo or (hi is not None and value > hi)):
            raise DecodeError(f"{name!r} is {value}, outside {lo} to {hi if hi is not None else 'any'}")
        values[name] = value
    return c.Usage(**values)


# Inclusive bounds for the context gauge's numbers: a percent used, and a count.
CONTEXT_BOUNDS = {
    "top_used": (0, 100),
    "near_limit": (0, None),
}


def _context_from(obj: dict[str, Any]) -> c.Context:
    """Absent or null is all unknown (a bridge from before the context gauge)."""
    if obj.get("context") is None:
        return c.Context()
    raw = _obj(obj, "context")
    values = {}
    for name, (lo, hi) in CONTEXT_BOUNDS.items():
        value = _get(raw, name, int, optional=True)
        if value is not None and (value < lo or (hi is not None and value > hi)):
            raise DecodeError(f"{name!r} is {value}, outside {lo} to {hi if hi is not None else 'any'}")
        values[name] = value
    return c.Context(top_agent=_get(raw, "top_agent", str, optional=True), **values)


def _event_from(obj: dict[str, Any]) -> c.Event:
    tag = obj["t"]
    if tag == "hello":
        caps = _get(obj, "caps", list)
        if not all(isinstance(cap, str) for cap in caps):
            raise DecodeError("caps must be strings")
        return c.Hello(fw=_get(obj, "fw", str), caps=list(caps), product=_get(obj, "product", str))
    if tag == "key":
        return c.Key(key=_enum(obj, "key", ACTIONS), phase=_enum(obj, "phase", KEY_PHASES),
                     ref=_get(obj, "ref", str, optional=True))
    if tag == "knob":
        return c.Knob(delta=_get(obj, "delta", int))
    if tag == "knob_press":
        return c.KnobPress(long=_get(obj, "long", bool))
    if tag == "select":
        return c.Select(ref=_get(obj, "ref", str))
    if tag == "seen":
        return c.Seen()
    if tag == "resync":
        return c.Resync()
    raise DecodeError(f"unknown event {tag!r}")


def decode_model(payload: bytes) -> c.Model:
    obj = _load(payload)
    if obj["t"] != "model":
        raise DecodeError(f"expected a model, got {obj['t']!r}")
    return _model_from(obj)


def decode_event(payload: bytes) -> c.Event:
    return _event_from(_load(payload))
