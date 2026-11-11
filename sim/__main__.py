"""Run the Helm deck simulator.

    python -m sim                  create a pty pair and print the bridge's port path
    python -m sim --port PATH      talk to a bridge through an existing serial path
    python -m sim --fake           standalone, with canned fixture models

Controls: Y / L / H hold YES / LATER / HOLD for 1 s, S taps SHOW ME (or click
the keys); arrows or the scroll wheel turn the knob; Enter presses it; M (or
holding the knob 0.6 s) toggles mute.
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
import tkinter as tk
from pathlib import Path

from helm.wire import transport
from sim.app import FakeSource, LinkSource, SimApp


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m sim", description="The Helm deck, simulated on the Mac.")
    where = parser.add_mutually_exclusive_group()
    where.add_argument("--fake", action="store_true", help="run standalone with fixture models")
    where.add_argument("--port", help="serial device or pty path where a bridge is listening")
    parser.add_argument("--port-file", type=Path, help="with the default pty mode, also write the bridge's port path here")
    parser.add_argument("--quit-after", type=float, help="close after this many seconds (smoke tests)")
    args = parser.parse_args(argv)

    if args.fake:
        source = FakeSource(time.monotonic())
        mode = "fake mode: fixture data"
    elif args.port:
        source = LinkSource(transport.DeviceLink(transport.open_port(args.port)))
        mode = f"port {args.port}"
    else:
        master, bridge_path = transport.open_pty()
        source = LinkSource(transport.DeviceLink(master))
        mode = f"pty: bridge port {bridge_path}"
        print(f"bridge port: {bridge_path}", flush=True)
        if args.port_file:
            tmp = args.port_file.with_suffix(".tmp")
            tmp.write_text(bridge_path + "\n")
            tmp.replace(args.port_file)

    root = tk.Tk()
    app = SimApp(root, source, mode)
    if args.quit_after:
        root.after(int(args.quit_after * 1000), app.close)
    # Tk swallows exceptions raised in callbacks, so Ctrl-C and the run
    # script's kill close the window through a handler instead.
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: root.after(0, app.close))
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
