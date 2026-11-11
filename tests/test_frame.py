import random
import unittest
from pathlib import Path

from helm.wire import frame

VECTORS = Path(__file__).parent / "vectors" / "cable_frame.txt"


def _vectors(kind: str) -> list[list[str]]:
    rows = []
    for line in VECTORS.read_text(encoding="utf-8").splitlines():
        if line.startswith(kind + "\t"):
            rows.append(line.split("\t"))
    return rows


def _expected_frames(spec: str) -> list[tuple[int, bytes]]:
    if spec == "-":
        return []
    out = []
    for part in spec.split(","):
        type_s, _, payload_hex = part.partition(":")
        out.append((int(type_s), bytes.fromhex(payload_hex)))
    return out


class VendorVectors(unittest.TestCase):
    """The openharness shared vectors, unchanged (see tests/vectors/NOTICE)."""

    def test_vectors_present(self):
        self.assertGreaterEqual(len(_vectors("encode")), 10)
        self.assertGreaterEqual(len(_vectors("stream")), 17)

    def test_crc_check_value(self):
        self.assertEqual(frame.crc16(b"123456789"), 0x29B1)

    def test_encode(self):
        for _, name, type_s, payload_hex, frame_hex in _vectors("encode"):
            with self.subTest(name):
                self.assertEqual(frame.encode(int(type_s), bytes.fromhex(payload_hex)).hex(), frame_hex)

    def test_stream_whole(self):
        for _, name, input_hex, spec, discarded, corrupt in _vectors("stream"):
            with self.subTest(name):
                d = frame.Decoder()
                got = [(f.type, f.payload) for f in d.feed(bytes.fromhex(input_hex))]
                self.assertEqual(got, _expected_frames(spec))
                self.assertEqual(d.discarded_bytes, int(discarded))
                self.assertEqual(d.corrupt_frames, int(corrupt))

    def test_stream_byte_at_a_time(self):
        for _, name, input_hex, spec, discarded, corrupt in _vectors("stream"):
            with self.subTest(name):
                d = frame.Decoder()
                got = []
                for b in bytes.fromhex(input_hex):
                    got += [(f.type, f.payload) for f in d.feed(bytes([b]))]
                self.assertEqual(got, _expected_frames(spec))
                self.assertEqual(d.discarded_bytes, int(discarded))
                self.assertEqual(d.corrupt_frames, int(corrupt))


class FrameBehavior(unittest.TestCase):
    def test_round_trip_random_payloads(self):
        rng = random.Random(7)
        frames = [(rng.choice([1, 4]), rng.randbytes(rng.randint(0, 600))) for _ in range(50)]
        stream = b"".join(frame.encode(t, p) for t, p in frames)
        d = frame.Decoder()
        got = []
        pos = 0
        while pos < len(stream):
            step = rng.randint(1, 97)
            got += [(f.type, f.payload) for f in d.feed(stream[pos : pos + step])]
            pos += step
        self.assertEqual(got, frames)
        self.assertEqual((d.discarded_bytes, d.corrupt_frames), (0, 0))

    def test_header_fields(self):
        data = frame.encode(frame.TYPE_JSON, b"{}")
        self.assertEqual(data[:2], b"\xa5\x48")
        self.assertEqual(data[2], 1)
        self.assertEqual(data[3], frame.TYPE_JSON)
        self.assertEqual(int.from_bytes(data[4:6], "little"), 2)

    def test_oversize_payload_refused(self):
        frame.encode(frame.TYPE_JSON, b"x" * frame.MAX_PAYLOAD)
        with self.assertRaises(frame.FrameTooLarge):
            frame.encode(frame.TYPE_JSON, b"x" * (frame.MAX_PAYLOAD + 1))

    def test_every_single_bit_flip_is_caught_and_next_frame_survives(self):
        good = frame.encode(frame.TYPE_JSON, b'{"t":"model","seq":1}')
        follow = frame.encode(frame.TYPE_JSON, b'{"t":"model","seq":2}')
        for i in range(len(good) * 8):
            corrupted = bytearray(good)
            corrupted[i // 8] ^= 1 << (i % 8)
            with self.subTest(bit=i):
                d = frame.Decoder()
                got = d.feed(bytes(corrupted) + follow)
                # A flipped length byte can make the decoder wait for more bytes;
                # the quiet-link expiry then resyncs onto the frame behind it.
                got += d.expire()
                self.assertEqual([f.payload for f in got], [b'{"t":"model","seq":2}'])

    def test_truncated_frame_expires_and_resyncs(self):
        first = frame.encode(frame.TYPE_JSON, b'{"t":"a"}')
        second = frame.encode(frame.TYPE_JSON, b'{"t":"b"}')
        d = frame.Decoder()
        self.assertEqual(d.feed(first[:-3]), [])
        self.assertTrue(d.pending)
        self.assertEqual(d.expire(), [])
        self.assertEqual(d.corrupt_frames, 1)
        self.assertFalse(d.pending)
        self.assertEqual([f.payload for f in d.feed(second)], [b'{"t":"b"}'])

    def test_garbage_between_frames(self):
        rng = random.Random(3)
        payloads = [f'{{"n":{i}}}'.encode() for i in range(20)]
        stream = b""
        for p in payloads:
            noise = bytes(b for b in rng.randbytes(rng.randint(0, 40)) if b != 0xA5)
            stream += noise + frame.encode(frame.TYPE_JSON, p)
        d = frame.Decoder()
        self.assertEqual([f.payload for f in d.feed(stream)], payloads)


if __name__ == "__main__":
    unittest.main()
