"""A stand-in bridge that plays canned fixture Models.

In-process it backs `python -m sim --fake`. Run on its own, it speaks the real
wire to a simulator over a pty, which checks the frame path end to end without
the real bridge:

    python -m sim.fake_bridge --port /dev/ttysNNN

It behaves just enough like the bridge for the screens to be exercised: a new
batch arrives a few seconds in (with one chime), a touch marks items seen, a
held key gets a queued result and then a reply, and a YES on the PR lands it.
"""

from __future__ import annotations

import argparse
import copy
import time

from helm import contract as c
from helm.wire import transport
from sim import fixtures

RESEND_S = 2.0
ARRIVE_AFTER_S = 3.0
REPLY_AFTER_S = 2.0

REPLIES = {
    "yes": "Firstmate: done. Fixture reply, nothing was changed.",
    "later": "Firstmate: deferred until tomorrow. Fixture reply.",
    "hold": "Firstmate: holding; raise it in chat. Fixture reply.",
}


class FakeBridge:
    def __init__(self, start: float) -> None:
        self.start = start
        self.seq = -1
        self.items: list[c.Item] = []
        self.arrived = False
        self.landed = 3
        self.result: c.Result | None = None
        self._reply_due: tuple[float, str, str] | None = None  # (when, key, ref)
        self._next_send = start
        self._chime_next = False
        self._requests = 0

    def _model(self) -> c.Model:
        self.seq += 1
        chime, self._chime_next = self._chime_next, False
        return fixtures.model(self.seq, self.items, chime=chime, result=self.result, landed_today=self.landed)

    def step(self, now: float) -> c.Model | None:
        changed = False
        if not self.arrived and now - self.start >= ARRIVE_AFTER_S:
            self.arrived = True
            self.items = copy.deepcopy([fixtures.DECISION, fixtures.PR_READY, fixtures.WORKER_PROBLEM, fixtures.HERDR_BLOCKED])
            self._chime_next = True
            changed = True
        if self._reply_due is not None and now >= self._reply_due[0]:
            _, key, ref = self._reply_due
            self._reply_due = None
            assert self.result is not None
            self.result = c.Result(request_id=self.result.request_id, state="replied", text=REPLIES[key])
            if key in ("yes", "later"):
                if key == "yes" and ref == fixtures.PR_READY.ref:
                    self.landed += 1
                self.items = [i for i in self.items if i.ref != ref]
            changed = True
        if changed or now >= self._next_send:
            self._next_send = now + RESEND_S
            return self._model()
        return None

    def handle(self, event: c.Event, now: float) -> c.Model | None:
        if isinstance(event, c.Seen):
            for item in self.items:
                item.unseen = False
            self._next_send = now  # send the calm model right away
        elif isinstance(event, c.Resync):
            self._next_send = now
        elif isinstance(event, c.Key) and event.phase == "held" and event.key != "focus" and event.ref is not None:
            ref = event.ref
            self._requests += 1
            self.result = c.Result(request_id=f"helm-{event.key}-fake-{self._requests}", state="queued", text="Queued for firstmate")
            self._reply_due = (now + REPLY_AFTER_S, event.key, ref)
            self._next_send = now
        return self.step(now)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m sim.fake_bridge", description="Fixture bridge over the real wire.")
    parser.add_argument("--port", required=True, help="serial device or the simulator's pty path")
    args = parser.parse_args(argv)
    link = transport.open_transport(args.port)
    bridge = FakeBridge(time.monotonic())
    print(f"fake bridge on {args.port}: fixture data only", flush=True)
    try:
        while True:
            # Send every model built: each one takes a seq, and skipping one
            # would read as a lost frame on the device.
            model = bridge.step(time.monotonic())
            if model is not None:
                link.send_model(model)
            for event in link.poll_events(0.05):
                if isinstance(event, c.Hello):
                    print(f"hello from {event.product} {event.fw} caps={event.caps}", flush=True)
                model = bridge.handle(event, time.monotonic())
                if model is not None:
                    link.send_model(model)
    except KeyboardInterrupt:
        return 0
    finally:
        link.close()


if __name__ == "__main__":
    raise SystemExit(main())
