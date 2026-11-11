import contextlib
import io
import unittest

from helm import contract as c
from helm.wire import codec, decode
from sim import fixtures


class DecodeCommand(unittest.TestCase):
    def _run(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(decode.main(argv), 0)
        return out.getvalue().splitlines()

    def test_decodes_mixed_capture(self):
        data = (
            b"boot text\r\n"
            + codec.encode_event(c.Hello(fw="sim-0.1"))
            + codec.encode_model(fixtures.calm(seq=4))
        )
        lines = self._run(["--hex", data.hex(" ")])
        self.assertEqual(len(lines), 3)
        self.assertIn("t=hello Hello", lines[0])
        self.assertIn('"product":"helm"', lines[0])
        self.assertIn("t=model Model", lines[1])
        self.assertEqual(lines[2], "frames=2 discarded_bytes=11 corrupt_frames=0")

    def test_flags_invalid_message_and_corruption(self):
        bad_crc = bytearray(codec.encode_event(c.Seen()))
        bad_crc[-1] ^= 0xFF
        invalid = codec.frame.encode(codec.frame.TYPE_JSON, b'{"t":"key","key":"nuke","phase":"down"}')
        lines = self._run(["--hex", (bytes(bad_crc) + invalid).hex()])
        self.assertIn("INVALID", lines[0])
        self.assertTrue(lines[-1].endswith("corrupt_frames=1"))


if __name__ == "__main__":
    unittest.main()
