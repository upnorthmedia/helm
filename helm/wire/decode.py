"""Read Helm frames out of captured bytes, for debugging.

    python -m helm.wire.decode capture.bin          raw bytes from a file
    python -m helm.wire.decode --hex 'a5 48 01 ...'  hex on the command line
    xxd -p capture.bin | python -m helm.wire.decode --hex-stdin

Prints one line per frame (type, length, and the decoded message or a reason
it did not decode), then the decoder's discarded-byte and corrupt-frame counts.
It reads captures, not a live port: a second reader on the port would steal
bytes from the bridge.
"""

from __future__ import annotations

import argparse
import json
import sys

from helm.wire import codec, frame

TYPE_NAMES = {frame.TYPE_JSON: "json", 0x02: "pcm", 0x03: "fw", frame.TYPE_LOG: "log"}


def describe(fr: frame.Frame) -> str:
    head = f"type={TYPE_NAMES.get(fr.type, hex(fr.type))} ver={fr.version} len={len(fr.payload)}"
    if fr.type == frame.TYPE_LOG:
        return f"{head} {fr.payload.decode('utf-8', 'replace')!r}"
    if fr.type != frame.TYPE_JSON:
        return f"{head} {fr.payload[:32].hex()}{'...' if len(fr.payload) > 32 else ''}"
    try:
        obj = json.loads(fr.payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return f"{head} not JSON: {fr.payload[:64]!r}"
    tag = obj.get("t") if isinstance(obj, dict) else None
    try:
        message = codec.decode_model(fr.payload) if tag == "model" else codec.decode_event(fr.payload)
        verdict = f"{type(message).__name__}"
    except codec.DecodeError as exc:
        verdict = f"INVALID ({exc})"
    return f"{head} t={tag} {verdict} {json.dumps(obj, separators=(',', ':'), ensure_ascii=False)}"


def decode_bytes(data: bytes) -> tuple[list[str], frame.Decoder]:
    decoder = frame.Decoder()
    frames = decoder.feed(data) + decoder.expire()
    return [describe(fr) for fr in frames], decoder


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m helm.wire.decode", description=__doc__.split("\n\n")[0])
    source = parser.add_mutually_exclusive_group()
    source.add_argument("path", nargs="?", help="file of raw captured bytes (default: stdin)")
    source.add_argument("--hex", help="hex bytes; spaces and colons are ignored")
    parser.add_argument("--hex-stdin", action="store_true", help="read hex text from stdin instead of raw bytes")
    args = parser.parse_args(argv)

    def unhex(text: str) -> bytes:
        return bytes.fromhex("".join(ch for ch in text if ch not in " :\n\r\t"))

    if args.hex is not None:
        data = unhex(args.hex)
    elif args.path:
        with open(args.path, "rb") as fh:
            data = fh.read()
    elif args.hex_stdin:
        data = unhex(sys.stdin.read())
    else:
        data = sys.stdin.buffer.read()

    lines, decoder = decode_bytes(data)
    for i, line in enumerate(lines, 1):
        print(f"#{i} {line}")
    print(f"frames={len(lines)} discarded_bytes={decoder.discarded_bytes} corrupt_frames={decoder.corrupt_frames}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
