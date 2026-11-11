"""Cross-tests: the C device core (firmware/core) against helm/wire, byte for byte.

Builds firmware/build/helm_wire_tool with CMake and drives it over stdin. Each
test runs the same input through the Python code and the C code and compares
the bytes: event frames, model payloads parsed by C and written back out, and
the frame decoder's output and counters on random noisy streams.
"""

from __future__ import annotations

import copy
import json
import random
import re
import shutil
import subprocess
import unittest
from dataclasses import asdict
from pathlib import Path

from helm import contract as c
from helm.wire import codec, frame
from sim import fixtures, render

REPO = Path(__file__).resolve().parent.parent
FIRMWARE = REPO / "firmware"
BUILD = FIRMWARE / "build"
TOOL = BUILD / "helm_wire_tool"

_built = False


def _build_tool() -> None:
    global _built
    if _built:
        return
    if shutil.which("cmake") is None:
        raise unittest.SkipTest("cmake is not installed; scripts/test-firmware.sh needs it too")
    for cmd in (
        ["cmake", "-S", str(FIRMWARE), "-B", str(BUILD)],
        ["cmake", "--build", str(BUILD), "--target", "helm_wire_tool"],
    ):
        done = subprocess.run(cmd, capture_output=True, text=True)
        if done.returncode != 0:
            raise AssertionError(f"{' '.join(cmd)} failed:\n{done.stdout}\n{done.stderr}")
    _built = True


def run_tool(lines: list[str]) -> list[str]:
    done = subprocess.run([str(TOOL)], input="\n".join(lines) + "\n", capture_output=True, text=True)
    if done.returncode != 0:
        raise AssertionError(f"helm_wire_tool exited {done.returncode}: {done.stderr}")
    out = done.stdout.splitlines()
    if len(out) != len(lines):
        raise AssertionError(f"helm_wire_tool answered {len(out)} of {len(lines)} lines: {done.stderr}")
    return out


def h(text: str) -> str:
    return text.encode("utf-8").hex() or "-"  # the tool reads "-" as an empty string


def random_text(rng: random.Random, max_len: int = 40) -> str:
    """Any Unicode the bridge could send: no NUL (the device refuses it) and no lone surrogates."""
    pools = [
        lambda: chr(rng.randint(1, 0x7F)),
        lambda: chr(rng.randint(0x80, 0x7FF)),
        lambda: chr(rng.choice([rng.randint(0x800, 0xD7FF), rng.randint(0xE000, 0xFFFF)])),
        lambda: chr(rng.randint(0x10000, 0x10FFFF)),
        lambda: rng.choice('"\\/\b\f\n\r\t\x01\x1f\x7f '),
    ]
    return "".join(rng.choice(pools)() for _ in range(rng.randint(0, max_len)))


EDGE_STRINGS = [
    "",
    "decision|main|demo-task|status-key",
    "pr|main|https://github.com/upnorthmedia/helm/pull/3",
    'quote " backslash \\ slash /',
    "\x01\x02\x1f\x7f",
    "\b\f\n\r\t",
    "café 中文 \U0001f600",
    "  ﻿",
]

ACTION_ORDER = list(codec.ACTIONS)


def _canonical_actions(rng: random.Random) -> list[str]:
    # The C side keeps actions as a set, so the round trip writes them in
    # contract order; the bridge already emits them in that order.
    return [a for a in ACTION_ORDER if rng.random() < 0.5]


def random_item(rng: random.Random) -> c.Item:
    return c.Item(
        ref=random_text(rng, 60) or "r",
        kind=rng.choice(codec.ITEM_KINDS),
        color=rng.choice(codec.COLORS),
        short_id=random_text(rng, 28),
        age_s=rng.choice([0, 1, 59, 3600, 2**31 - 1, rng.randint(0, 10**6)]),
        unseen=rng.random() < 0.5,
        home=random_text(rng, 12),
        detail=random_text(rng, 300),
        actions=_canonical_actions(rng),
        pr_url=rng.choice([None, "https://github.com/o/r/pull/%d" % rng.randint(1, 9999), random_text(rng, 20)]),
        checks=rng.choice([None, *codec.CHECKS]),
        project=rng.choice([None, "helm", random_text(rng, 32)]),
        pending=rng.choice([None, *codec.ANSWERS]),
    )


def random_result(rng: random.Random) -> c.Result | None:
    if rng.random() < 0.4:
        return None
    return c.Result(
        request_id=random_text(rng, 20),
        state=rng.choice(codec.RESULT_STATES),
        text=random_text(rng, 80),
        seen=rng.random() < 0.5,
        waited_s=rng.choice([None, 0, 59, 2**31 - 1, rng.randint(0, 10**5)]),
        stalled=rng.random() < 0.5,
    )


def random_usage(rng: random.Random) -> c.Usage:
    def maybe(value: int) -> int | None:
        return value if rng.random() < 0.7 else None

    return c.Usage(
        five_hour_left=maybe(rng.choice([0, 100, rng.randint(0, 100)])),
        five_hour_resets_s=maybe(rng.choice([0, 18000, 2**31 - 1, rng.randint(0, 18000)])),
        week_left=maybe(rng.randint(0, 100)),
        week_resets_s=maybe(rng.randint(0, 604800)),
    )


def random_context(rng: random.Random) -> c.Context:
    if rng.random() < 0.3:
        return c.Context()
    return c.Context(
        top_used=rng.choice([0, 100, rng.randint(0, 100)]),
        top_agent=rng.choice([None, "fm-25m", random_text(rng, 28)]),
        near_limit=rng.choice([0, 1, 2**31 - 1, rng.randint(0, 20)]),
    )


def random_model(rng: random.Random, seq: int) -> c.Model:
    items = [random_item(rng) for _ in range(rng.randint(0, 12))]
    return c.Model(
        seq=seq,
        link=c.Link(
            bridge_ok=rng.random() < 0.8,
            firstmate_can_receive=rng.choice([None, True, False]),
            posture=rng.choice([None, "present", random_text(rng, 10)]),
            stale_reason=rng.choice([None, random_text(rng, 40)]),
            away=rng.random() < 0.3,
            mac_locked=rng.random() < 0.3,
        ),
        attention=rng.choice(codec.ATTENTION),
        unseen=sum(1 for i in items if i.unseen),
        counts=c.Counts(**{name: rng.randint(0, 50) for name in c.Counts.__dataclass_fields__}),
        items=items,
        result=random_result(rng),
        chime=rng.random() < 0.3,
        usage=random_usage(rng),
        context=random_context(rng),
    )


def payload_of(model: c.Model) -> bytes:
    return codec.encode_model(model)[frame.HEADER_BYTES : -frame.CRC_BYTES]


def payload_len(model: c.Model) -> int:
    return len(json.dumps({"t": "model", **asdict(model)}, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


INT32 = range(-(2**31), 2**31)
INT64 = range(-(2**63), 2**63)


def outside_c_range(model: c.Model) -> bool:
    """True when an integer is too big for its C field (int64 seq, int32 elsewhere).

    Python ints are unbounded, so the C parser refuses these where Python
    accepts; the bridge never sends numbers anywhere near that size.
    """
    small = [model.unseen, *asdict(model.counts).values(), *(item.age_s for item in model.items),
             *(v for v in asdict(model.usage).values() if v is not None),
             *(v for v in (model.context.top_used, model.context.near_limit) if v is not None),
             *([model.result.waited_s] if model.result and model.result.waited_s is not None else [])]
    return model.seq not in INT64 or any(v not in INT32 for v in small)


class FirmwareCoreCrossTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _build_tool()

    # Events

    def _event_line(self, event: c.Event) -> str:
        if isinstance(event, c.Hello):
            return " ".join(["event hello", h(event.fw), *(h(cap) for cap in event.caps)])
        if isinstance(event, c.Key):
            ref = "" if event.ref is None else f" {h(event.ref)}"
            return f"event key {event.key} {event.phase}{ref}"
        if isinstance(event, c.Knob):
            return f"event knob {event.delta}"
        if isinstance(event, c.KnobPress):
            return f"event knob_press {int(event.long)}"
        if isinstance(event, c.Select):
            return f"event select {h(event.ref)}"
        return f"event {c.event_type(event)}"

    def test_events_encode_identically(self):
        rng = random.Random(11)
        events: list[c.Event] = [
            c.Hello(fw="helm-0.1", caps=["screen-720", "keys-4", "knob", "lightbar-8", "chime"]),
            c.Hello(fw="", caps=[]),
            c.Hello(fw="café \"v\" \\ 1", caps=EDGE_STRINGS[1:]),
            c.Seen(),
            c.Resync(),
            c.KnobPress(long=False),
            c.KnobPress(long=True),
        ]
        events += [c.Key(key=k, phase=p) for k in codec.ACTIONS for p in codec.KEY_PHASES]
        events += [c.Key(key=k, phase=p, ref="pr:sample-org/gizmo#42") for k in codec.ACTIONS for p in codec.KEY_PHASES]
        events += [c.Key(key="yes", phase="held", ref=s) for s in EDGE_STRINGS]
        events += [c.Key(key="later", phase="held", ref=random_text(rng, 120)) for _ in range(100)]
        events += [c.Knob(delta=d) for d in (0, 1, -1, 7, -128, 2**31 - 1, -(2**31))]
        events += [c.Select(ref=s) for s in EDGE_STRINGS if s]
        events += [c.Select(ref=random_text(rng, 120) or "x") for _ in range(300)]
        events += [c.Hello(fw=random_text(rng, 20), caps=[random_text(rng, 10) for _ in range(rng.randint(0, 5))]) for _ in range(50)]
        got = run_tool([self._event_line(e) for e in events])
        for event, line in zip(events, got):
            with self.subTest(event=event):
                self.assertEqual(line, codec.encode_event(event).hex())

    # Models

    def _round_trip(self, models: list[c.Model]) -> None:
        frames = [codec.encode_model(m) for m in models]
        got = run_tool([f"model {fr.hex()}" for fr in frames])
        for model, line in zip(models, got):
            with self.subTest(seq=model.seq):
                self.assertTrue(line.startswith("ok "), line)
                self.assertEqual(bytes.fromhex(line[3:]), payload_of(model))

    def test_fixture_models_round_trip(self):
        result_queued = fixtures.busy(seq=7)
        result_queued.result = c.Result(request_id="helm-yes-1", state="queued", text="Queued")
        result_failed = fixtures.busy(seq=8)
        result_failed.result = c.Result(request_id="r", state="failed", text="YES does not apply to pane-7")
        self._round_trip([fixtures.calm(), fixtures.busy(), fixtures.stale(), fixtures.projects(), fixtures.away(),
                          fixtures.calm_near_limit(), fixtures.mac_locked(), result_queued, result_failed,
                          fixtures.answered(), fixtures.stalled()])

    def test_random_models_round_trip(self):
        rng = random.Random(5)
        self._round_trip([codec.fit_model(random_model(rng, seq)) for seq in range(400)])

    def test_largest_models_round_trip(self):
        # fit_model shortens and drops items until the payload fits one frame.
        rng = random.Random(9)
        models = []
        for seq in range(5):
            big = random_model(rng, seq)
            big.items = [random_item(rng) for _ in range(200)]
            for item in big.items:
                item.detail = random_text(rng, 2000)
            fitted = codec.fit_model(big)
            self.assertLessEqual(len(payload_of(fitted)), frame.MAX_PAYLOAD)
            models.append(fitted)
        self._round_trip(models)

    def test_item_bound_covers_any_frame(self):
        """HELM_MAX_ITEMS holds as many of the smallest items as fit in one frame."""
        header = (FIRMWARE / "core" / "helm_model.h").read_text()
        max_items = int(re.search(r"#define HELM_MAX_ITEMS (\d+)u", header).group(1))
        tiny = c.Item(ref="", kind="decision", color="red", short_id="", age_s=0, unseen=True, home="", detail="", actions=[])
        model = c.Model(seq=0, link=c.Link(True, None, None, None), attention="calm", unseen=0, counts=c.Counts())
        while payload_len(model) <= frame.MAX_PAYLOAD:
            model.items.append(copy.deepcopy(tiny))
        model.items.pop()
        self.assertLessEqual(len(model.items), max_items)
        self._round_trip([model])

    def test_rejections_match_python(self):
        """Every payload the Python codec refuses, the C parser refuses, and the reverse."""
        base = json.loads(payload_of(fixtures.busy(seq=3)))
        variants: list[object] = []

        def variant(mutate) -> None:
            obj = copy.deepcopy(base)
            mutate(obj)
            variants.append(obj)

        for key in list(base):
            variant(lambda o, k=key: o.pop(k))
            for bad in (None, True, 1, 1.5, "x", [], {}):
                variant(lambda o, k=key, v=bad: o.__setitem__(k, v))
        for section in ("link", "counts", "usage", "context"):
            for key in list(base[section]):
                variant(lambda o, s=section, k=key: o[s].pop(k))
                for bad in (None, True, 1, -1, 2**40, "x", []):
                    variant(lambda o, s=section, k=key, v=bad: o[s].__setitem__(k, v))
        for key in list(base["items"][0]):
            variant(lambda o, k=key: o["items"][0].pop(k))
            for bad in (None, True, 0, -3, 2**31, "x", "red", "yes", [], ["yes"], ["nope"], [None], {}):
                variant(lambda o, k=key, v=bad: o["items"][0].__setitem__(k, v))
        result = {"request_id": "r", "state": "queued", "text": "ok", "seen": True, "waited_s": 200, "stalled": False}
        variant(lambda o: o.__setitem__("result", dict(result)))
        for key in result:
            variant(lambda o, k=key: o.__setitem__("result", {kk: vv for kk, vv in result.items() if kk != k}))
            for bad in (None, True, 3, -1, 2**31, "x", "seen", []):
                variant(lambda o, k=key, v=bad: o.__setitem__("result", {**result, k: v}))
        # An older bridge's result, with none of the fields added since.
        variant(lambda o: o.__setitem__("result", {"request_id": "r", "state": "replied", "text": "ok"}))
        variant(lambda o: o.__setitem__("future", {"deep": [1, 2.5, None, {"x": "y"}]}))
        variant(lambda o: o["items"].append(7))
        variant(lambda o: o["items"][0].__setitem__("future", [True]))
        variant(lambda o: o["usage"].__setitem__("future", {"x": 1}))
        for name in ("five_hour_left", "week_left"):
            for value in (0, 100, 101, -1):
                variant(lambda o, k=name, v=value: o["usage"].__setitem__(k, v))
        variant(lambda o: o["usage"].__setitem__("week_resets_s", 2**31))  # Python takes it, C cannot
        variant(lambda o: o["context"].__setitem__("future", [1, {"x": None}]))
        for value in (0, 100, 101, -1):
            variant(lambda o, v=value: o["context"].__setitem__("top_used", v))
        variant(lambda o: o["context"].__setitem__("near_limit", 2**31))  # Python takes it, C cannot
        variant(lambda o: o["context"].__setitem__("top_agent", "caf\u00e9"))
        variants += [[], "model", 3, None]

        payloads = [json.dumps(v, separators=(",", ":"), ensure_ascii=False).encode("utf-8") for v in variants]
        payloads += [b"", b"{", b'{"t":"model"} trailing', b'{"t":"model",}', b"\xff\xfe"]
        good = payload_of(fixtures.busy(seq=3))
        payloads += [
            good.replace(b'"detail":"', b'"detail":"\x01', 1),  # raw control character
            good.replace(b'"detail":"', b'"detail":"\xc3', 1),  # cut UTF-8 sequence
            good.replace(b'"detail":"', b'"detail":"\\ud83d\\ude00 \\u00e9 \\/', 1),  # escapes Python accepts
            good.replace(b'"seq":3', b'"seq":-0', 1),
            good.replace(b'"seq":3', b'"seq":3.0', 1),
            b" \n" + good + b"\r\t ",
        ]
        got = run_tool([f"model {frame.encode(frame.TYPE_JSON, p).hex()}" for p in payloads])
        accepted = rejected = 0
        for payload, line in zip(payloads, got):
            with self.subTest(payload=payload[:200]):
                try:
                    model = codec.decode_model(payload)
                except codec.DecodeError:
                    self.assertTrue(line.startswith("err "), line)
                    rejected += 1
                    continue
                if outside_c_range(model):
                    self.assertEqual(line, "err range")
                    continue
                self.assertTrue(line.startswith("ok "), line)
                self.assertEqual(bytes.fromhex(line[3:]), payload_of(model))
                accepted += 1
        # Both outcomes are exercised, not just one.
        self.assertGreater(accepted, 10)
        self.assertGreater(rejected, 100)

    # Lights

    def test_project_tints_match_python(self):
        rng = random.Random(13)
        names = ["", "helm", "widget-api", "gizmo", "a", *EDGE_STRINGS[1:]]
        names += [random_text(rng, 32) for _ in range(500)]
        names = [n for n in names if n]  # an empty project is tint 0 on both sides; "-" means empty to the tool
        got = run_tool([f"tint {h(n)}" for n in names])
        for name, line in zip(names, got):
            with self.subTest(name=name):
                self.assertEqual(int(line), render.project_tint(name))

    # Frame decoder

    def test_decoder_matches_python_on_noisy_streams(self):
        rng = random.Random(3)
        streams = []
        for _ in range(300):
            data = bytearray()
            for _ in range(rng.randint(1, 8)):
                kind = rng.random()
                fr = frame.encode(rng.choice([1, 2, 3, 4, 0x7F]), rng.randbytes(rng.choice([0, 1, 5, 40, 300])))
                if kind < 0.4:
                    data += fr
                elif kind < 0.55:
                    bad = bytearray(fr)
                    bad[rng.randrange(len(bad))] ^= 1 << rng.randrange(8)
                    data += bad
                elif kind < 0.65:
                    data += fr[: rng.randrange(1, len(fr))]
                elif kind < 0.75:
                    data += b"\xa5\x48\x01\x01" + rng.randbytes(2) + rng.randbytes(rng.randint(0, 20))
                elif kind < 0.85:
                    data += rng.choice([b"\xa5", b"\xa5\xa5", b"\xa5\x5a", b"\x48"])
                else:
                    data += rng.randbytes(rng.randint(1, 30))
            streams.append(bytes(data))
        got = run_tool([f"stream {s.hex()}" for s in streams])

        def spec(frames: list[frame.Frame]) -> str:
            return ",".join(f"{f.type}:{f.payload.hex()}" for f in frames) or "-"

        for data, line in zip(streams, got):
            d = frame.Decoder()
            fed = d.feed(data)
            expired = d.expire()
            with self.subTest(stream=data.hex()[:80]):
                self.assertEqual(line, f"{spec(fed)} {spec(expired)} {d.discarded_bytes} {d.corrupt_frames}")


if __name__ == "__main__":
    unittest.main()
