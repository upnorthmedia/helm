"""python -m helm.bridge --port <path> [--home <firstmate home>] [--live]

The home defaults to $FM_HOME, the variable firstmate itself uses.

Dry run is the default: the exact note, focus, and SHOW ME open commands are logged, not run.
`--doctor` checks what the home is missing for Helm, read only, and exits.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

from helm.contract import model_to_dict
from helm.bridge.bridge import Bridge
from helm.bridge import doctor
from helm.bridge.commands import Runner
from helm.bridge.intents import IntentExecutor
from helm.bridge.show import default_cache_dir
from helm.bridge.sources import discover_homes
from helm.bridge.transports import MemoryTransport, StdioTransport
from helm.bridge.usage import UsagePoller


def open_port_transport(port: str):
    """The device link. `-` is JSON lines on stdin and stdout; anything else is helm.wire's serial or pty transport."""
    if port == "-":
        return StdioTransport()
    try:
        from helm.wire import open_transport  # provided by the device and wire protocol work
    except ImportError as exc:
        raise SystemExit("helm.wire is not available (%s); use --port - for JSON lines on stdio" % exc)
    return open_transport(port)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m helm.bridge", description=__doc__.splitlines()[0])
    parser.add_argument("--port", help="serial device or pty path for the deck, or - for JSON lines on stdio")
    parser.add_argument("--home", default=os.environ.get("FM_HOME"), help="primary firstmate home (default: $FM_HOME)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", dest="live", action="store_false", help="log note, focus, and open commands instead of running them (default)")
    mode.add_argument("--live", dest="live", action="store_true", help="send real inbox notes, focus herdr panes, and open boards and reports")
    parser.add_argument("--once", action="store_true", help="read everything once, print one Model as JSON, and exit")
    parser.add_argument("--doctor", action="store_true",
                        help="check what the firstmate home is missing for Helm, read only; exit 1 if a required piece is missing")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.set_defaults(live=False)
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    if not args.home:
        parser.error("no firstmate home: pass --home or set FM_HOME")
    home = Path(args.home).expanduser()
    if args.doctor:
        # Never live: the doctor's runner refuses every write command.
        return doctor.main(home, Runner(allow_writes=False))
    if not (home / "state").is_dir():
        parser.error("not a firstmate home (no state/ directory): %s" % home)

    cache_dir = default_cache_dir()
    # `lavish-axi <page>` may open only the helm cache's pages and files in a firstmate home's data/.
    runner = Runner(allow_writes=args.live,
                    page_roots=lambda: [cache_dir] + [ref.path / "data" for ref in discover_homes(home)])
    executor = IntentExecutor(home, runner, dry_run=not args.live, cache_dir=cache_dir)

    if args.once:
        transport = MemoryTransport()
        # Read usage inline so the one Model printed includes it.
        bridge = Bridge(transport, home, runner, executor, usage=UsagePoller(runner, background=False))
        bridge.tick(time.time())
        json.dump(model_to_dict(transport.sent[-1]), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if not args.port:
        parser.error("--port is required (or use --once)")
    bridge = Bridge(open_port_transport(args.port), home, runner, executor)
    try:
        bridge.run_forever()
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
