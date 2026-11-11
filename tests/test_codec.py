import copy
import json
import unittest

from helm import contract as c
from helm.wire import codec, frame
from sim import fixtures


def _payload(data: bytes) -> bytes:
    (fr,) = frame.Decoder().feed(data)
    return fr.payload


class Codec(unittest.TestCase):
    def test_model_round_trip(self):
        for m in (fixtures.calm(), fixtures.busy(), fixtures.stale()):
            with self.subTest(seq=m.seq):
                m.result = c.Result(request_id="helm-yes-x", state="queued", text="Queued")
                self.assertEqual(codec.decode_model(_payload(codec.encode_model(m))), m)

    def test_model_is_compact_json_with_t(self):
        obj = json.loads(_payload(codec.encode_model(fixtures.calm())))
        self.assertEqual(obj["t"], "model")
        self.assertNotIn(b" ", _payload(codec.encode_model(fixtures.calm())))

    def test_event_round_trip(self):
        events = [
            c.Hello(fw="sim-0.1", caps=["screen-720", "chime"]),
            c.Key(key="yes", phase="down"),
            c.Key(key="later", phase="held"),
            c.Key(key="focus", phase="up"),
            c.Key(key="yes", phase="held", ref="decision|main|demo-task|status-key"),
            c.Knob(delta=-3),
            c.KnobPress(long=True),
            c.Select(ref="pr:sample-org/gizmo#42"),
            c.Seen(),
            c.Resync(),
        ]
        for ev in events:
            with self.subTest(ev=ev):
                self.assertEqual(codec.decode_event(_payload(codec.encode_event(ev))), ev)

    def test_event_wire_shape(self):
        self.assertEqual(
            json.loads(_payload(codec.encode_event(c.Key(key="yes", phase="held", ref="pr:o/r#1")))),
            {"t": "key", "key": "yes", "phase": "held", "ref": "pr:o/r#1"},
        )
        self.assertEqual(
            json.loads(_payload(codec.encode_event(c.Key(key="yes", phase="held")))),
            {"t": "key", "key": "yes", "phase": "held", "ref": None},
        )
        # A deck from before Key.ref sends no ref at all; it decodes as None (and the bridge refuses it).
        self.assertEqual(codec.decode_event(b'{"t":"key","key":"yes","phase":"held"}'), c.Key(key="yes", phase="held"))
        self.assertEqual(json.loads(_payload(codec.encode_event(c.Seen()))), {"t": "seen"})
        self.assertEqual(json.loads(_payload(codec.encode_event(c.Resync()))), {"t": "resync"})

    def test_hello_names_helm(self):
        obj = json.loads(_payload(codec.encode_event(c.Hello(fw="sim-0.1"))))
        self.assertEqual(obj["product"], "helm")
        self.assertNotEqual(obj["product"], "harness")

    def test_rejects_bad_messages(self):
        bad = [
            b"not json",
            b"[1,2]",
            b'{"no":"t"}',
            b'{"t":"key","key":"nuke","phase":"down"}',
            b'{"t":"key","key":"yes"}',
            b'{"t":"key","key":"yes","phase":"held","ref":7}',
            b'{"t":"knob","delta":true}',
            b'{"t":"knob","delta":"3"}',
            b'{"t":"launch"}',
        ]
        for payload in bad:
            with self.subTest(payload=payload):
                with self.assertRaises(codec.DecodeError):
                    codec.decode_event(payload)

    def test_rejects_bad_model(self):
        good = json.loads(_payload(codec.encode_model(fixtures.busy())))
        cases = {
            "attention": lambda o: o.__setitem__("attention", "panic"),
            "item color": lambda o: o["items"][0].__setitem__("color", "purple"),
            "action": lambda o: o["items"][0].__setitem__("actions", ["merge_now"]),
            "count type": lambda o: o["counts"].__setitem__("decisions", "2"),
            "missing link": lambda o: o.pop("link"),
        }
        for name, mutate in cases.items():
            with self.subTest(name):
                obj = json.loads(json.dumps(good))
                mutate(obj)
                with self.assertRaises(codec.DecodeError):
                    codec.decode_model(json.dumps(obj).encode())

    def test_payload_from_an_older_bridge_decodes_with_defaults(self):
        obj = json.loads(_payload(codec.encode_model(fixtures.busy())))
        obj.pop("usage")
        obj.pop("context")
        obj["link"].pop("away")
        obj["link"].pop("mac_locked")
        for item in obj["items"]:
            item.pop("project")
        m = codec.decode_model(json.dumps(obj).encode())
        self.assertEqual(m.usage, c.Usage())
        self.assertEqual(m.context, c.Context())
        self.assertFalse(m.link.away)
        self.assertFalse(m.link.mac_locked)
        self.assertTrue(all(i.project is None for i in m.items))

    def test_new_fields_round_trip(self):
        m = fixtures.away()
        m.usage = c.Usage(five_hour_left=0, five_hour_resets_s=0, week_left=100, week_resets_s=2**40)
        m.items[0].project = "helm"
        self.assertEqual(codec.decode_model(_payload(codec.encode_model(m))), m)
        locked = fixtures.mac_locked()
        locked.context = c.Context(top_used=100, top_agent="caf\u00e9 \U0001f600", near_limit=0)
        self.assertEqual(codec.decode_model(_payload(codec.encode_model(locked))), locked)
        self.assertEqual(codec.decode_model(_payload(codec.encode_model(fixtures.stale()))).context, c.Context())

    def test_rejects_bad_context_and_lock(self):
        good = json.loads(_payload(codec.encode_model(fixtures.busy())))
        for name, value in [("top_used", 101), ("top_used", -1), ("top_used", "50"), ("top_used", True),
                            ("top_used", 4.5), ("near_limit", -1), ("near_limit", False), ("top_agent", 3)]:
            with self.subTest(name=name, value=value):
                obj = json.loads(json.dumps(good))
                obj["context"][name] = value
                with self.assertRaises(codec.DecodeError):
                    codec.decode_model(json.dumps(obj).encode())
        for bad in [(("context",), 3), (("context",), []), (("link", "mac_locked"), 1), (("link", "mac_locked"), "yes")]:
            with self.subTest(bad=bad):
                obj = json.loads(json.dumps(good))
                target = obj
                for key in bad[0][:-1]:
                    target = target[key]
                target[bad[0][-1]] = bad[1]
                with self.assertRaises(codec.DecodeError):
                    codec.decode_model(json.dumps(obj).encode())
        obj = json.loads(json.dumps(good))
        obj["context"] = {"top_used": None, "later": {"x": 1}}  # null and unknown keys are fine
        self.assertEqual(codec.decode_model(json.dumps(obj).encode()).context, c.Context())

    def test_rejects_bad_usage(self):
        good = json.loads(_payload(codec.encode_model(fixtures.busy())))
        for name, value in [("five_hour_left", 101), ("week_left", -1), ("five_hour_left", "50"),
                            ("week_left", True), ("week_left", 4.5), ("five_hour_resets_s", -1)]:
            with self.subTest(name=name, value=value):
                obj = json.loads(json.dumps(good))
                obj["usage"][name] = value
                with self.assertRaises(codec.DecodeError):
                    codec.decode_model(json.dumps(obj).encode())
        for usage in (3, "x", [], True):
            with self.subTest(usage=usage):
                obj = json.loads(json.dumps(good))
                obj["usage"] = usage
                with self.assertRaises(codec.DecodeError):
                    codec.decode_model(json.dumps(obj).encode())

    def test_model_over_frame_limit_raises(self):
        m = fixtures.busy()
        m.items[0].detail = "x" * frame.MAX_PAYLOAD
        with self.assertRaises(frame.FrameTooLarge):
            codec.encode_model(m)

    def test_fit_shortens_details_first(self):
        m = fixtures.busy()
        for item in m.items:
            item.detail = "word " * 600  # 3000 bytes each, about 12 KB in all
        fitted = codec.fit_model(m)
        self.assertLessEqual(len(codec.encode_model(fitted)), frame.MAX_FRAME)
        self.assertEqual([i.ref for i in fitted.items], [i.ref for i in m.items])  # nothing dropped
        self.assertTrue(all(i.detail.endswith("...") for i in fitted.items))
        self.assertEqual(fitted.counts, m.counts)
        self.assertEqual(len(m.items[0].detail), 3000)  # the caller's model is untouched

    def test_fit_drops_tail_items_when_details_are_not_enough(self):
        m = fixtures.busy()
        base = m.items[0]
        m.items = []
        for n in range(120):
            item = copy.deepcopy(base)
            item.ref, item.short_id = f"decision:{n}", f"task-{n}"
            m.items.append(item)
        fitted = codec.fit_model(m)
        self.assertLessEqual(len(codec.encode_model(fitted)), frame.MAX_FRAME)
        self.assertGreater(len(fitted.items), 0)
        self.assertEqual([i.ref for i in fitted.items], [i.ref for i in m.items[: len(fitted.items)]])
        self.assertEqual(fitted.counts, m.counts)

    def test_fit_holds_with_projects_and_usage(self):
        m = fixtures.busy()
        m.usage = c.Usage(five_hour_left=55, five_hour_resets_s=17999, week_left=9, week_resets_s=604799)
        m.context = c.Context(top_used=100, top_agent="t" * 28, near_limit=2**31 - 1)
        m.link.mac_locked = True
        base = m.items[0]
        m.items = []
        for n in range(150):
            item = copy.deepcopy(base)
            item.ref, item.short_id, item.project = f"decision|primary|t{n}|k{n}", f"task-{n}", "p" * 32
            m.items.append(item)
        fitted = codec.fit_model(m)
        self.assertLessEqual(len(codec.encode_model(fitted)), frame.MAX_FRAME)
        self.assertEqual(fitted.usage, m.usage)
        self.assertEqual((fitted.context, fitted.link), (m.context, m.link))
        self.assertTrue(all(i.project == "p" * 32 for i in fitted.items))

    def test_fit_leaves_small_models_alone(self):
        m = fixtures.busy()
        self.assertEqual(codec.fit_model(m), m)


if __name__ == "__main__":
    unittest.main()
