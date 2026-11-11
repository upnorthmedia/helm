"""Canned Models for --fake mode, tests, and screenshots.

Every name and sentence here is invented. Nothing comes from a real firstmate
home.
"""

from __future__ import annotations

import copy

from helm import contract as c

LINK_OK = c.Link(bridge_ok=True, firstmate_can_receive=True, posture="present", stale_reason=None)
LINK_AWAY = c.Link(bridge_ok=True, firstmate_can_receive=True, posture="away", stale_reason=None, away=True)
LINK_LOCKED = c.Link(bridge_ok=True, firstmate_can_receive=True, posture="present", stale_reason=None, mac_locked=True)
USAGE = c.Usage(five_hour_left=62, five_hour_resets_s=6300, week_left=40, week_resets_s=270000)
CONTEXT = c.Context(top_used=64, top_agent="gizmo-retry", near_limit=0)
CONTEXT_NEAR = c.Context(top_used=91, top_agent="widget-cache", near_limit=2)

DECISION = c.Item(
    ref="decision:demo-widget-api:pick-cache",
    kind="decision",
    color="red",
    short_id="widget-api",
    age_s=95,
    unseen=True,
    home="main",
    detail=(
        "demo-widget-api asks: the widget cache can live in process memory or in the shared "
        "key value store. In process is simpler and faster for one instance; the store survives "
        "restarts and works across instances. Recommendation: in process memory for now, "
        "revisit when a second instance ships."
    ),
    actions=["yes", "later", "hold", "focus"],
)

PR_READY = c.Item(
    ref="pr:sample-org/gizmo#42",
    kind="pr_ready",
    color="blue",
    short_id="gizmo#42",
    age_s=1260,
    unseen=True,
    home="main",
    detail=(
        "sample-org/gizmo PR 42: add retry with backoff to the gizmo uploader. Checks green at the "
        "current head, no conflicts. Merge ask from the gizmo-retry worker."
    ),
    actions=["yes", "later", "hold", "focus"],
    pr_url="https://example.invalid/sample-org/gizmo/pull/42",
    checks="green",
)

WORKER_PROBLEM = c.Item(
    ref="task:demo-docs-sweep",
    kind="worker_problem",
    color="amber",
    short_id="docs-sweep",
    age_s=3700,
    unseen=False,
    home="second",
    detail="demo-docs-sweep reported blocked: the link checker needs a network allowance it does not have.",
    actions=["later", "hold", "focus"],
)

HERDR_BLOCKED = c.Item(
    ref="herdr:pane-7",
    kind="herdr_blocked",
    color="amber",
    short_id="pane-7",
    age_s=40,
    unseen=False,
    home="herdr",
    detail="A herdr agent in pane 7 is waiting for input.",
    actions=["focus"],
)


def model(
    seq: int,
    items: list[c.Item],
    *,
    attention: c.Attention | None = None,
    chime: bool = False,
    result: c.Result | None = None,
    link: c.Link = LINK_OK,
    landed_today: int = 3,
    usage: c.Usage = USAGE,
    context: c.Context = CONTEXT,
) -> c.Model:
    items = copy.deepcopy(items)
    unseen = sum(1 for item in items if item.unseen)
    if attention is None:
        attention = "new" if unseen else "calm"
    return c.Model(
        seq=seq,
        link=copy.deepcopy(link),
        attention=attention,
        unseen=unseen,
        counts=c.Counts(
            decisions=sum(1 for i in items if i.kind == "decision"),
            working=4,
            queued=1,
            prs_ready=sum(1 for i in items if i.kind == "pr_ready"),
            landed_today=landed_today,
            herdr_working=3,
            herdr_blocked=sum(1 for i in items if i.kind == "herdr_blocked"),
        ),
        items=items,
        result=result,
        chime=chime,
        usage=copy.deepcopy(usage),
        context=copy.deepcopy(context),
    )


def calm(seq: int = 1) -> c.Model:
    return model(seq, [])


def calm_near_limit(seq: int = 1) -> c.Model:
    """Calm, with two herdr agents near their context limit: the last calm light turns amber."""
    return model(seq, [], context=CONTEXT_NEAR)


def busy(seq: int = 2) -> c.Model:
    """Two new items and two seen ones: the usual screenshot state."""
    return model(seq, [DECISION, PR_READY, WORKER_PROBLEM, HERDR_BLOCKED], chime=True)


def stale(seq: int = 3) -> c.Model:
    return model(
        seq,
        [WORKER_PROBLEM],
        attention="unknown",
        link=c.Link(bridge_ok=True, firstmate_can_receive=False, posture="unknown", stale_reason="firstmate is not listening"),
        usage=c.Usage(),
        context=c.Context(),
    )


# Projects for the fixture items, as the bridge derives them (herdr items have none).
PROJECTS = {DECISION.ref: "widget-api", PR_READY.ref: "gizmo", WORKER_PROBLEM.ref: "widget-api"}


def with_projects(m: c.Model) -> c.Model:
    m = copy.deepcopy(m)
    for item in m.items:
        item.project = PROJECTS.get(item.ref)
    return m


def projects(seq: int = 5) -> c.Model:
    """The busy model with projects: the knob on Home turns through all, gizmo, widget-api."""
    return with_projects(busy(seq))


def away(seq: int = 4) -> c.Model:
    """Firstmate away: the bridge has dropped every acting key, leaving SHOW ME."""
    items = copy.deepcopy([DECISION, PR_READY, WORKER_PROBLEM, HERDR_BLOCKED])
    for item in items:
        item.actions = [a for a in item.actions if a == "focus"]
    return with_projects(model(seq, items, link=LINK_AWAY, usage=c.Usage(five_hour_left=8, five_hour_resets_s=2400, week_left=None)))


def answered(seq: int = 8) -> c.Model:
    """YES held on the widget-api decision 40 s ago: firstmate has read it and not replied yet."""
    m = model(seq, [DECISION, PR_READY, WORKER_PROBLEM, HERDR_BLOCKED])
    m.items[0].pending = "yes"
    m.items[1].pending = "hold"
    m.result = c.Result(request_id="helm-yes-fixture", state="queued", text="queued YES on widget-api",
                        seen=True, waited_s=40)
    return m


def stalled(seq: int = 9) -> c.Model:
    """HOLD held on gizmo#42 four minutes ago, and firstmate has not read it."""
    m = model(seq, [DECISION, PR_READY, WORKER_PROBLEM, HERDR_BLOCKED])
    m.items[1].pending = "hold"
    m.result = c.Result(request_id="helm-hold-fixture", state="queued", text="queued HOLD on gizmo#42",
                        waited_s=250, stalled=True)
    return m


def mac_locked(seq: int = 7) -> c.Model:
    """The Mac is locked: the bridge has dropped every action, SHOW ME included."""
    items = copy.deepcopy([DECISION, PR_READY, WORKER_PROBLEM, HERDR_BLOCKED])
    for item in items:
        item.actions = []
    return with_projects(model(seq, items, link=LINK_LOCKED))
