# SPDX-License-Identifier: MIT
# Derived from autonomous-ai/openharness (MIT, Copyright (c) 2026 Autonomous, Inc.); see THIRD_PARTY_NOTICES.md.
"""The Harness Pro binary frame (D9), byte for byte.

Ported from autonomous-ai/openharness at commit
a441303f550cd8c15fc34d64f453f662d113b635:
devices/harness-pro/firmware/main/cable/cable_frame.h and cable_frame.c.

Wire format, little-endian throughout:

    A5 48 | ver:u8 | type:u8 | len:u16 | payload[len] | crc16:u16

The CRC is CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF, no reflection, no
final xor) over ver..payload; the magic is not covered. The decoder mirrors the
vendor's resync rules: scan for the magic, treat an impossible length as noise
and step one byte, and on a bad CRC drop one byte (not the whole frame) because
a real frame may start inside what looked like one.
"""

from __future__ import annotations

from dataclasses import dataclass

MAGIC = b"\xa5\x48"  # 0x48 is 'H', the Harness product byte
FRAME_VERSION = 1
HEADER_BYTES = 6  # magic(2) + ver(1) + type(1) + len(2)
CRC_BYTES = 2
MAX_PAYLOAD = 8192
MAX_FRAME = HEADER_BYTES + MAX_PAYLOAD + CRC_BYTES

TYPE_JSON = 0x01  # UTF-8 JSON object with a "t" discriminator
TYPE_LOG = 0x04  # one log line, device to host, raw bytes


class FrameTooLarge(ValueError):
    pass


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return crc


def encode(frame_type: int, payload: bytes) -> bytes:
    if len(payload) > MAX_PAYLOAD:
        raise FrameTooLarge(f"payload is {len(payload)} bytes, limit {MAX_PAYLOAD}")
    body = bytes([FRAME_VERSION, frame_type]) + len(payload).to_bytes(2, "little") + payload
    return MAGIC + body + crc16(body).to_bytes(2, "little")


@dataclass(frozen=True)
class Frame:
    version: int
    type: int
    payload: bytes


class Decoder:
    """Reassembles frames from a byte stream that may start anywhere."""

    def __init__(self) -> None:
        self._buf = bytearray()
        self.corrupt_frames = 0
        self.discarded_bytes = 0

    @property
    def pending(self) -> bool:
        return bool(self._buf)

    def reset(self) -> None:
        """Forget a partial frame; counters survive (they show a trend)."""
        self._buf.clear()

    def feed(self, data: bytes) -> list[Frame]:
        out: list[Frame] = []
        self._buf.extend(data)
        # _take_front leaves at most one partial frame (bounded by MAX_FRAME)
        # or a lone trailing A5, so the buffer cannot grow without limit.
        while self._take_front(out):
            pass
        return out

    def expire(self) -> list[Frame]:
        """The link went quiet mid-frame: drop the partial and resync now."""
        out: list[Frame] = []
        if not self._buf:
            return out
        if self._buf[:2] == MAGIC:
            self.corrupt_frames += 1
            self._discard(1)
        while self._take_front(out):
            pass
        if self._buf:
            self._discard(len(self._buf))
        return out

    def _discard(self, count: int) -> None:
        count = min(count, len(self._buf))
        del self._buf[:count]
        self.discarded_bytes += count

    def _take_front(self, out: list[Frame]) -> bool:
        while True:
            buf = self._buf
            if buf[:2] != MAGIC:
                at = buf.find(MAGIC)
                if at < 0:
                    # Keep a trailing A5: its second byte may not have arrived yet.
                    keep = 1 if buf and buf[-1] == MAGIC[0] else 0
                    self._discard(len(buf) - keep)
                    return False
                self._discard(at)
                continue
            if len(buf) < HEADER_BYTES:
                return False
            payload_len = buf[4] | (buf[5] << 8)
            if payload_len > MAX_PAYLOAD:
                self._discard(1)
                continue
            total = HEADER_BYTES + payload_len + CRC_BYTES
            if len(buf) < total:
                return False
            expected = buf[total - 2] | (buf[total - 1] << 8)
            if crc16(bytes(buf[2 : total - 2])) != expected:
                self.corrupt_frames += 1
                self._discard(1)
                continue
            out.append(Frame(buf[2], buf[3], bytes(buf[HEADER_BYTES : total - 2])))
            del buf[:total]
            return True
