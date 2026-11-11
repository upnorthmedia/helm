"""Transports the bridge ships itself. The serial and pty transport with the binary frame lives in helm.wire."""

from __future__ import annotations

import json
import logging
import select
import sys
from collections import deque
from typing import TextIO

from helm.contract import Event, Model, Transport, event_from_dict, model_to_dict

log = logging.getLogger(__name__)


class MemoryTransport(Transport):
    """In-memory test double: models sent are kept, events are queued by the test."""

    def __init__(self) -> None:
        self.sent: list[Model] = []
        self.inbound: deque = deque()

    def push(self, *events: Event) -> None:
        self.inbound.extend(events)

    def send_model(self, model: Model) -> None:
        self.sent.append(model)

    def poll_events(self, timeout_s: float) -> list[Event]:
        events = list(self.inbound)
        self.inbound.clear()
        return events


class StdioTransport(Transport):
    """One JSON object per line: models out on stdout, events in on stdin. For poking the bridge by hand."""

    def __init__(self, stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> None:
        self.stdin = stdin
        self.stdout = stdout
        self.closed = False

    def send_model(self, model: Model) -> None:
        self.stdout.write(json.dumps(model_to_dict(model), separators=(",", ":")) + "\n")
        self.stdout.flush()

    def poll_events(self, timeout_s: float) -> list[Event]:
        if self.closed:
            return []
        ready, _, _ = select.select([self.stdin], [], [], timeout_s)
        if not ready:
            return []
        line = self.stdin.readline()
        if not line:
            self.closed = True
            return []
        try:
            return [event_from_dict(json.loads(line))]
        except (ValueError, KeyError, TypeError) as exc:
            log.warning("ignoring bad event line: %s", exc)
            return []
