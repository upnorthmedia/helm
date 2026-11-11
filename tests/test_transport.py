import os
import threading
import time
import unittest

from helm import contract as c
from helm.wire import codec, frame, transport
from sim import fixtures


class PtyTransport(unittest.TestCase):
    """Both ends over a real pseudo-terminal, the way run-sim.sh connects them.

    A macOS pty holds about 1 KB each way, less than one model frame, so the
    device end reads on its own thread while the bridge writes, as it does in
    the simulator.
    """

    def setUp(self):
        master, self.slave_path = transport.open_pty()
        self.device = transport.DeviceLink(master)
        self.bridge = transport.open_transport(self.slave_path)
        self._models: list[c.Model] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._reader = threading.Thread(target=self._read_device, daemon=True)
        self._reader.start()

    def tearDown(self):
        self._stop.set()
        self._reader.join(2)
        self.bridge.close()
        self.device.close()

    def _read_device(self):
        while not self._stop.is_set():
            got = self.device.poll_models(0.02)
            with self._lock:
                self._models += got

    def _wait_models(self, want: int, timeout_s: float = 2.0) -> list[c.Model]:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            with self._lock:
                if len(self._models) >= want:
                    return list(self._models)
            time.sleep(0.01)
        with self._lock:
            return list(self._models)

    def _bridge_events(self, want: int, timeout_s: float = 2.0) -> list[c.Event]:
        got: list[c.Event] = []
        deadline = time.monotonic() + timeout_s
        while len(got) < want and time.monotonic() < deadline:
            got += self.bridge.poll_events(0.05)
        return got

    def test_model_reaches_device(self):
        m = fixtures.busy()
        self.assertGreater(len(codec.encode_model(m)), 1024)
        self.bridge.send_model(m)
        self.assertEqual(self._wait_models(1), [m])
        self.assertEqual(self.bridge.dropped_writes, 0)

    def test_events_reach_bridge(self):
        sent = [c.Hello(fw="sim", caps=["chime"]), c.Key(key="yes", phase="held"), c.Seen()]
        for ev in sent:
            self.device.send_event(ev)
        self.assertEqual(self._bridge_events(len(sent)), sent)

    def test_poll_times_out_empty(self):
        start = time.monotonic()
        self.assertEqual(self.bridge.poll_events(0.1), [])
        self.assertGreaterEqual(time.monotonic() - start, 0.09)

    def test_noise_and_partial_frame_heal(self):
        fd = self.bridge.port.fileno()
        os.write(fd, b"ESP-ROM boot chatter\r\n")
        cut = codec.encode_model(fixtures.calm(seq=1))
        os.write(fd, cut[: len(cut) // 2])
        time.sleep(transport.PARTIAL_FRAME_EXPIRY_S + 0.15)
        self.assertEqual(self._wait_models(1, timeout_s=0.1), [])
        good = fixtures.busy(seq=2)
        self.bridge.send_model(good)
        self.assertEqual(self._wait_models(1), [good])
        self.assertEqual(self.device.decoder.corrupt_frames, 1)
        # The lost frame makes the device ask for the model again.
        self.assertEqual(self._bridge_events(1), [c.Resync()])

    def test_seq_gap_asks_for_resync_once_per_window(self):
        for seq in (1, 2, 5, 9):
            self.bridge.send_model(fixtures.calm(seq=seq))
        self.assertEqual([m.seq for m in self._wait_models(4)], [1, 2, 5, 9])
        self.assertEqual(self.device.seq_gaps, 2)
        # Two gaps inside one 2 s window yield one resync now, one pending.
        self.assertEqual(self._bridge_events(2, timeout_s=0.5), [c.Resync()])

    def test_steady_seq_sends_no_resync(self):
        for seq in range(5):
            self.bridge.send_model(fixtures.calm(seq=seq))
        self._wait_models(5)
        self.assertEqual(self.bridge.poll_events(0.2), [])
        self.assertEqual(self.device.seq_gaps, 0)

    def test_bad_message_is_counted_not_raised(self):
        os.write(self.bridge.port.fileno(), frame.encode(frame.TYPE_JSON, b'{"t":"model"}'))
        time.sleep(0.2)
        self.assertEqual(self._wait_models(1, timeout_s=0.1), [])
        self.assertEqual(self.device.bad_messages, 1)


class NoPeer(unittest.TestCase):
    def test_device_write_without_reader_does_not_stall(self):
        master, _ = transport.open_pty()
        device = transport.DeviceLink(master)
        try:
            start = time.monotonic()
            # Send until the pty buffer fills: a few KB on macOS, far more on Linux.
            for _ in range(100_000):
                device.send_event(c.Knob(delta=1))
                if device.dropped_writes:
                    break
            for _ in range(200):
                device.send_event(c.Knob(delta=1))
            # One write waits its budget; after that the port is known stalled.
            self.assertLess(time.monotonic() - start, 3 * transport.WRITE_BUDGET_S)
            self.assertGreater(device.dropped_writes, 0)
        finally:
            device.close()


if __name__ == "__main__":
    unittest.main()
