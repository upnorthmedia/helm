"""Byte transports for the Helm link: a real serial port and a pseudo-terminal.

Two ends share one framing core:

- BridgeTransport implements contract.Transport for the bridge (send models,
  poll events).
- DeviceLink is the device's side (send events, poll models); the simulator
  uses it, and the firmware will do the same in C++ later.

Writes never block for long. The device sits unplugged or in front of a
stopped bridge for much of its life, and the bridge resends the full model
every 2 s, so a frame that cannot go out now is dropped rather than queued.
"""

from __future__ import annotations

import errno
import logging
import os
import select
import termios
import time
import tty
from typing import Callable, Protocol, TypeVar

from helm import contract as c
from helm.wire import codec, frame

log = logging.getLogger(__name__)

# The vendor reader drops a partial frame after 300 ms with no bytes, so a lost
# tail costs one message instead of swallowing the next frame.
PARTIAL_FRAME_EXPIRY_S = 0.3
WRITE_BUDGET_S = 0.1
DEFAULT_BAUD = 115200


class Port(Protocol):
    def fileno(self) -> int: ...
    def read_available(self) -> bytes: ...
    def write_all(self, data: bytes) -> bool: ...
    def close(self) -> None: ...


class FdPort:
    """A non-blocking file descriptor: a pty master, or a tty opened without pyserial."""

    def __init__(self, fd: int, *, keep_open: tuple[int, ...] = ()) -> None:
        self._fd = fd
        self._keep_open = keep_open
        # Set when a write ran out of time: nobody is draining the other end
        # (a pty holds only about 1 KB each way). Until a write completes
        # again, writes do not wait, so a missing peer cannot stall the caller.
        self._stalled = False
        os.set_blocking(fd, False)

    def fileno(self) -> int:
        return self._fd

    def read_available(self) -> bytes:
        chunks = []
        while True:
            try:
                chunk = os.read(self._fd, 4096)
            except BlockingIOError:
                break
            except OSError as exc:
                # A pty master reads EIO when no slave is open; that is "nothing to read".
                if exc.errno == errno.EIO:
                    break
                raise
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)

    def write_all(self, data: bytes) -> bool:
        deadline = time.monotonic() + (0.0 if self._stalled else WRITE_BUDGET_S)
        view = memoryview(data)
        while view:
            try:
                sent = os.write(self._fd, view)
                view = view[sent:]
                if sent and self._stalled:
                    # The peer is draining again: finish this frame normally.
                    self._stalled = False
                    deadline = time.monotonic() + WRITE_BUDGET_S
                continue
            except BlockingIOError:
                pass
            except OSError as exc:
                if exc.errno in (errno.EIO, errno.ENXIO):
                    return False
                raise
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._stalled = True
                return False
            select.select([], [self._fd], [], remaining)
        self._stalled = False
        return True

    def close(self) -> None:
        for fd in (self._fd, *self._keep_open):
            try:
                os.close(fd)
            except OSError:
                pass


class SerialPort:
    """A real serial device through pyserial."""

    def __init__(self, path: str, baud: int = DEFAULT_BAUD) -> None:
        import serial  # pyserial; imported here so the pty path needs nothing outside the stdlib

        self._serial = serial.Serial(path, baud, timeout=0, write_timeout=WRITE_BUDGET_S, exclusive=True)
        self._timeout_error = serial.SerialTimeoutException
        # Bytes queued before we opened belong to nobody's session.
        self._serial.reset_input_buffer()

    def fileno(self) -> int:
        return self._serial.fileno()

    def read_available(self) -> bytes:
        waiting = self._serial.in_waiting
        return self._serial.read(waiting) if waiting else b""

    def write_all(self, data: bytes) -> bool:
        try:
            self._serial.write(data)
            return True
        except self._timeout_error:
            return False

    def close(self) -> None:
        self._serial.close()


def open_port(path: str, baud: int = DEFAULT_BAUD) -> Port:
    """Open a serial device or a pty slave path.

    Uses pyserial when it is installed. Without it, falls back to a raw termios
    file descriptor, which is enough for a pty and for a USB CDC device.
    """
    try:
        return SerialPort(path, baud)
    except ImportError:
        pass
    fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    tty.setraw(fd)
    speed = getattr(termios, f"B{baud}", None)
    if speed is not None:
        attrs = termios.tcgetattr(fd)
        attrs[4] = attrs[5] = speed
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
    termios.tcflush(fd, termios.TCIFLUSH)
    return FdPort(fd)


def open_pty() -> tuple[FdPort, str]:
    """Create a pseudo-terminal pair; return the master end and the slave's path.

    The other program opens the slave path as if it were the deck's serial
    port. The slave is set raw (no echo, no newline translation, which would
    corrupt binary frames), and its fd stays open here so the master never
    reads EIO between the peer's sessions and the raw settings persist.
    """
    master, slave = os.openpty()
    tty.setraw(slave)
    tty.setraw(master)
    return FdPort(master, keep_open=(slave,)), os.ttyname(slave)


T = TypeVar("T")


class _FramedEnd:
    def __init__(self, port: Port) -> None:
        self.port = port
        self.decoder = frame.Decoder()
        self.bad_messages = 0
        self.dropped_writes = 0
        self._last_rx = time.monotonic()

    def _send(self, data: bytes) -> None:
        if not self.port.write_all(data):
            self.dropped_writes += 1

    def _poll(self, timeout_s: float, decode: Callable[[bytes], T]) -> list[T]:
        deadline = time.monotonic() + max(timeout_s, 0.0)
        out: list[T] = []
        while True:
            remaining = deadline - time.monotonic()
            readable, _, _ = select.select([self.port], [], [], max(remaining, 0.0))
            now = time.monotonic()
            frames: list[frame.Frame] = []
            if readable:
                data = self.port.read_available()
                if data:
                    self._last_rx = now
                    frames = self.decoder.feed(data)
            if self.decoder.pending and now - self._last_rx >= PARTIAL_FRAME_EXPIRY_S:
                frames += self.decoder.expire()
            for fr in frames:
                if fr.type != frame.TYPE_JSON:
                    if fr.type == frame.TYPE_LOG:
                        log.debug("device log: %s", fr.payload.decode("utf-8", "replace"))
                    continue
                try:
                    out.append(decode(fr.payload))
                except codec.DecodeError as exc:
                    self.bad_messages += 1
                    log.warning("dropped a bad message: %s", exc)
            if out or remaining <= 0:
                return out

    def close(self) -> None:
        self.port.close()


class BridgeTransport(_FramedEnd, c.Transport):
    def send_model(self, model: c.Model) -> None:
        fitted = codec.fit_model(model)
        if fitted is not model:
            log.debug("model shrunk to fit one frame: %d of %d items", len(fitted.items), len(model.items))
        self._send(codec.encode_model(fitted))

    def poll_events(self, timeout_s: float) -> list[c.Event]:
        return self._poll(timeout_s, codec.decode_event)


RESYNC_MIN_INTERVAL_S = 2.0


class DeviceLink(_FramedEnd):
    """The device's end. Mirrors the Harness Pro's loss handling.

    A model whose seq is not exactly one past the last, or a frame that failed
    its CRC, means something was lost; the device then sends `resync`, at most
    once per 2 s, and keeps it pending inside that window.
    """

    def __init__(self, port: Port) -> None:
        super().__init__(port)
        self.seq_gaps = 0
        self._last_seq: int | None = None
        self._corrupt_seen = 0
        self._resync_pending = False
        self._last_resync = -RESYNC_MIN_INTERVAL_S

    def send_event(self, event: c.Event) -> None:
        self._send(codec.encode_event(event))

    def poll_models(self, timeout_s: float) -> list[c.Model]:
        models = self._poll(timeout_s, codec.decode_model)
        for model in models:
            if self._last_seq is not None and model.seq != self._last_seq + 1:
                self.seq_gaps += 1
                self._resync_pending = True
            self._last_seq = model.seq
        if self.decoder.corrupt_frames != self._corrupt_seen:
            self._corrupt_seen = self.decoder.corrupt_frames
            self._resync_pending = True
        now = time.monotonic()
        if self._resync_pending and now - self._last_resync >= RESYNC_MIN_INTERVAL_S:
            self._resync_pending = False
            self._last_resync = now
            self.send_event(c.Resync())
        return models


def open_transport(path: str, baud: int = DEFAULT_BAUD) -> BridgeTransport:
    """The bridge's entry point: open the deck (or the simulator's pty) at `path`."""
    return BridgeTransport(open_port(path, baud))
