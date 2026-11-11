"""Edge-triggered attention (decision D2 in docs/research/README.md).

The light means "something new since the captain last touched the deck", not
"anything open": with a dozen long-standing decisions a level-triggered light
would never go dark. Seen state lives here only and is never written to firstmate.
"""

from __future__ import annotations

from typing import Iterable, Optional


class Attention:
    def __init__(self) -> None:
        self._first_seen: dict[str, float] = {}
        self._unseen: set[str] = set()
        self._baselined = False
        self._chime_pending = False

    def observe(self, refs: Iterable[str], now: float, edges: Iterable[str] = ()) -> None:
        """Record the refs currently needing the captain.

        A ref is new when it was not present on the previous call. `edges` are refs
        that a ledger event says just (re)entered an attention state, which makes them
        new even if the item was already listed. Everything present on the first call
        is the baseline and counts as seen, so starting the bridge does not light up
        every standing decision.
        """
        current = set(refs)
        if not self._baselined:
            self._first_seen = {ref: now for ref in current}
            self._baselined = True
            return
        fresh = False
        for ref in current - self._first_seen.keys():
            self._first_seen[ref] = now
            self._unseen.add(ref)
            fresh = True
        for ref in set(edges) & current:
            if ref not in self._unseen:
                self._unseen.add(ref)
                fresh = True
        for ref in list(self._first_seen):
            if ref not in current:
                del self._first_seen[ref]
                self._unseen.discard(ref)
        if fresh:
            self._chime_pending = True

    def mark_all_seen(self) -> None:
        self._unseen.clear()
        self._chime_pending = False

    def is_unseen(self, ref: str) -> bool:
        return ref in self._unseen

    @property
    def unseen_count(self) -> int:
        return len(self._unseen)

    def first_seen(self, ref: str) -> Optional[float]:
        return self._first_seen.get(ref)

    def take_chime(self) -> bool:
        """True once after new items arrive; the next model carries chime=true."""
        chime, self._chime_pending = self._chime_pending, False
        return chime

    def state(self, link_ok: bool) -> str:
        if not link_ok:
            return "unknown"
        return "new" if self._unseen else "calm"
