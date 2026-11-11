"""The context gauge: how full each herdr agent's context window is.

`herdr agent list` gives every agent a `tokens` map: short strings that herdr
integrations report for the sidebar (herdr's schema allows up to 32 string
values, keys matching [A-Za-z0-9_-]{1,32}). herdr itself does not count
tokens. The usagebar plugin (senna-lang/herdr-agent-usage) writes
`tokens.context`, in these forms (internal/core/format.go there):

    "⛁ 49% (492k)"          percent of the window used, and the token count
    "⚠️ 85% (850k)"          the same, with a warning icon from 80 %
    "49% (492k)", "49%"     narrower forms when the sidebar is tight
    "5h 72% · ⛁ 14% (136k)" with several Claude accounts, the account's limit first
    "compacted (31k)"       after a compaction: an estimate, no percent
    "⛁ 31k"                 window size unknown: no percent

Only a percent of the window counts as a reading. Anything else, a missing
token, or no usagebar at all is unknown, never empty.
"""

from __future__ import annotations

import re
from typing import Optional

from helm.contract import Context

# usagebar's own warning threshold (warningThresholdPercent), so the deck and
# the herdr sidebar agree on "near the limit".
NEAR_LIMIT_PERCENT = 80

# One segment of tokens.context: an optional icon, then "N%", then optionally "(Nk)".
_PERCENT_OF_WINDOW = re.compile(r"^(?:⛁|⚠️?)?\s*(\d{1,3})%(?:\s*\([^()]*\))?$")


def context_percent(text) -> Optional[int]:
    """Percent of its window an agent uses, from its tokens.context, or None when unknown."""
    if not isinstance(text, str):
        return None
    # The context status is the last segment; an account limit ("5h 72%") may come first.
    match = _PERCENT_OF_WINDOW.match(text.split(" · ")[-1].strip())
    if not match:
        return None
    value = int(match.group(1))
    return value if value <= 100 else None


def context_gauge(agents: list[dict], title) -> Context:
    """The fullest agent and how many are near their limit. `title(agent)` names an agent."""
    readings = []
    for agent in agents:
        tokens = agent.get("tokens")
        percent = context_percent(tokens.get("context") if isinstance(tokens, dict) else None)
        if percent is not None:
            readings.append((percent, agent))
    if not readings:
        return Context()
    top, agent = max(readings, key=lambda reading: reading[0])  # the first of equals, in herdr's order
    return Context(
        top_used=top,
        top_agent=title(agent),
        near_limit=sum(1 for percent, _ in readings if percent >= NEAR_LIMIT_PERCENT),
    )
