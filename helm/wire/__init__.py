"""The Helm wire: the Harness Pro binary frame, message codec, and transports.

The bridge opens the deck with `open_transport(path)`, which returns a
contract.Transport over a serial device or the simulator's pty.
"""

from helm.wire.transport import open_transport

__all__ = ["open_transport"]
