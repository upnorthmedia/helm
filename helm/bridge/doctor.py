"""`python -m helm.bridge --doctor`: what a firstmate home is missing for Helm, one line per check.

Read only. It runs only the bridge's own read commands (`fm-inbox.sh ready`,
`herdr agent list`, and the usage gauge's `quota-axi` read) through a runner
that refuses every write, reads files, and looks programs up on PATH. It never
creates, changes, or deletes a file anywhere, and it never runs `lavish-axi`.

Each line is `ok`, `warn`, or `missing`, with the fix after a warn or missing.
`missing` is kept for the pieces the bridge cannot work without: a firstmate
home with `state/` and `bin/fm-inbox.sh`, a readable `fm-inbox.sh ready`, and
the primary home's summary. Everything else is optional and shows as `warn`,
so the exit status is nonzero only when a required piece is missing.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, TextIO

from helm.bridge.context import context_percent
from helm.bridge.intents import YES_PREFIX
from helm.bridge.sources import HomeRef, discover_homes, parse_herdr_agents
from helm.bridge.usage import USAGE_ARGV, USAGE_TIMEOUT_S, parse_quota

READY_SCHEMA = "fm-primary-ready.v1"
SUMMARY_SCHEMA = "fm-secondmate-home-summary.v1"
SETUP_GUIDE = "docs/firstmate-setup.md"
# firstmate never rotates the ledger; past this size the doctor suggests truncating it.
LEDGER_LARGE_BYTES = 50 * 1024 * 1024
# Where the YES rule may live: the home's own captain preferences, or the primary's shared ones.
RULE_FILES = ("data/captain.md", "data/captain-shared.md")
PIN_FLAG = "--expected-head"

OK, WARN, MISSING = "ok", "warn", "missing"


@dataclass(frozen=True)
class Check:
    status: str  # ok, warn, or missing
    name: str
    detail: str
    fix: str = ""

    def line(self) -> str:
        text = "%-8s%s: %s" % (self.status, self.name, self.detail)
        return "%s Fix: %s" % (text, self.fix) if self.fix else text


def check_home(home: Path) -> Check:
    if not home.is_dir():
        return Check(MISSING, "home", "%s is not a directory" % home,
                     "pass --home <firstmate home> or set FM_HOME to the checkout firstmate runs from.")
    inbox = home / "bin" / "fm-inbox.sh"
    lacking = []
    if not (home / "state").is_dir():
        lacking.append("state/")
    if not (inbox.is_file() and os.access(inbox, os.X_OK)):
        lacking.append("executable bin/fm-inbox.sh")
    if lacking:
        return Check(MISSING, "home", "%s has no %s" % (home, " and no ".join(lacking)),
                     "point --home at the firstmate checkout firstmate runs from, after it has started there once.")
    extras = [d for d in ("data", "config") if not (home / d).is_dir()]
    detail = "%s has bin/fm-inbox.sh and state/" % home
    if extras:
        # Both are local and created on first use, so their absence is not a fault on its own.
        detail += " (no %s/ yet)" % "/ or ".join(extras)
    return Check(OK, "home", detail)


def check_ready(home: Path, runner) -> Check:
    done = runner.run([str(home / "bin" / "fm-inbox.sh"), "ready"], env={"FM_HOME": str(home)}, timeout=10)
    try:
        data = json.loads(done.stdout)
    except (TypeError, ValueError):
        data = None
    if not isinstance(data, dict):
        why = done.stderr.strip()[:120] or "exit %d, no JSON" % done.returncode
        return Check(MISSING, "ready", "fm-inbox.sh ready failed: %s" % why,
                     "update firstmate: Helm needs `fm-inbox.sh ready` (%s)." % READY_SCHEMA)
    if data.get("schema") != READY_SCHEMA:
        return Check(MISSING, "ready", "fm-inbox.sh ready printed schema %r, Helm reads %s" % (data.get("schema"), READY_SCHEMA),
                     "update firstmate or Helm so both speak %s." % READY_SCHEMA)
    if data.get("can_receive") is True:
        return Check(OK, "ready", "%s, can_receive true, posture %s" % (READY_SCHEMA, _state(data, "posture")))
    return Check(WARN, "ready", "%s, can_receive %s (lock %s, wake consumer %s)" % (
        READY_SCHEMA, json.dumps(data.get("can_receive")), _state(data, "lock"), _state(data, "wake_consumer")),
        "start firstmate in this home. Until it can receive, the deck shows its link as unknown.")


def _state(data: dict, part: str) -> str:
    """The `state` of one part of a ready record, such as its posture, or "unknown"."""
    value = data.get(part)
    state = value.get("state") if isinstance(value, dict) else None
    return state if isinstance(state, str) else "unknown"


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def check_yes_rule(home: Path) -> Check:
    prefix = _normalized(YES_PREFIX)
    for name in RULE_FILES:
        try:
            text = _normalized((home / name).read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if prefix not in text:
            continue
        if PIN_FLAG not in text:
            return Check(WARN, "YES rule", "found in %s, but it never mentions %s, and a YES on a PR now names a commit" % (name, PIN_FLAG),
                         "replace it with the rule in %s, which passes the commit to fm-pr-merge.sh." % SETUP_GUIDE)
        return Check(OK, "YES rule", "found in %s, with the commit pin" % name)
    return Check(WARN, "YES rule", "the deck's YES opening words are not in data/captain.md: a held YES is a plain note, "
                 "not your approval, so firstmate asks you in chat",
                 "if you want a held YES to count as your word, paste the rule from %s into data/captain.md." % SETUP_GUIDE)


def check_summary(ref: HomeRef, now: float) -> Check:
    name = "summary %s" % ref.label
    bad = MISSING if ref.primary else WARN
    path = ref.path / "state" / "home-summary.json"
    fix = "start firstmate in that home: it publishes state/home-summary.json (bin/fm-home-summary-refresh.sh) on every event."
    if not (ref.path / "state").is_dir():
        return Check(bad, name, "%s has no state/ (listed in data/secondmates.md)" % ref.path,
                     "fix the home path in the primary's data/secondmates.md, or start that second mate.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Check(bad, name, "state/home-summary.json not found", fix)
    except (OSError, ValueError) as exc:
        return Check(bad, name, "state/home-summary.json unreadable: %s" % str(exc)[:80], fix)
    schema = data.get("schema") if isinstance(data, dict) else None
    if schema != SUMMARY_SCHEMA:
        return Check(bad, name, "schema %r, Helm reads %s" % (schema, SUMMARY_SCHEMA),
                     "update firstmate or Helm so both speak %s." % SUMMARY_SCHEMA)
    epoch = data.get("generated_epoch")
    age = ", published %s ago" % _age(now - epoch) if isinstance(epoch, (int, float)) and not isinstance(epoch, bool) else ""
    if data.get("valid") is not True:
        reason = data.get("reason") if isinstance(data.get("reason"), str) else "no reason given"
        return Check(WARN, name, "%s, valid false: %s%s" % (SUMMARY_SCHEMA, reason[:120], age),
                     "none in setup: firstmate marks its summary invalid while its own records disagree and "
                     "republishes once they agree; if it stays invalid, ask firstmate why.")
    return Check(OK, name, "%s, valid%s" % (SUMMARY_SCHEMA, age))


def check_ledger(ref: HomeRef) -> Check:
    name = "fleet ledger %s" % ref.label
    if not (ref.path / "config" / "fleet-ledger").exists():
        return Check(WARN, name, "off: a new item shows only when the summary republishes",
                     "create config/fleet-ledger in that home (each home needs its own flag).")
    try:
        size = (ref.path / "state" / "fleet-ledger.jsonl").stat().st_size
    except OSError:
        return Check(OK, name, "on, no state/fleet-ledger.jsonl yet")
    if size > LEDGER_LARGE_BYTES:
        return Check(WARN, name, "on, state/fleet-ledger.jsonl is %s and firstmate never rotates it" % _size(size),
                     "truncate it now and then with `: > state/fleet-ledger.jsonl` in that home.")
    return Check(OK, name, "on, state/fleet-ledger.jsonl is %s" % _size(size))


def check_pr_health(ref: HomeRef) -> Check:
    name = "pr health %s" % ref.label
    if (ref.path / "config" / "pr-health-monitor").exists():
        return Check(OK, name, "on")
    return Check(WARN, name, "off: the deck cannot tell a PR has failing checks or conflicts, so YES is not dimmed for it "
                 "(firstmate's merge guards still refuse it)",
                 "create config/pr-health-monitor in that home; it takes effect at firstmate's next session start.")


def check_herdr(runner, which) -> tuple[Check, Optional[list[dict]]]:
    if which("herdr") is None:
        return Check(WARN, "herdr", "not on PATH: SHOW ME cannot focus panes, and there is no herdr line or context gauge",
                     "optional; install herdr if you run your agents in it."), None
    done = runner.run(["herdr", "agent", "list"], timeout=5)
    agents = parse_herdr_agents(done.stdout) if done.returncode == 0 else None
    if agents is None:
        why = done.stderr.strip()[:120] or "exit %d" % done.returncode
        return Check(WARN, "herdr", "`herdr agent list` failed: %s" % why, "start herdr, then run the doctor again."), None
    return Check(OK, "herdr", "reachable, %d agent(s)" % len(agents)), agents


def check_context(agents: Optional[list[dict]]) -> Check:
    if agents is None:
        return Check(WARN, "context tokens", "not checked: herdr is not reachable")
    if not agents:
        return Check(WARN, "context tokens", "no herdr agents running to check", "run the doctor again while an agent runs.")
    reporting = sum(1 for agent in agents
                    if isinstance(agent.get("tokens"), dict) and context_percent(agent["tokens"].get("context")) is not None)
    if reporting:
        return Check(OK, "context tokens", "%d of %d agent(s) report tokens.context" % (reporting, len(agents)))
    return Check(WARN, "context tokens", "no agent reports a context percent in tokens.context, so the context gauge reads unknown",
                 "install the usagebar plugin for herdr (senna-lang/herdr-agent-usage).")


def check_quota(runner, which) -> Check:
    if which("quota-axi") is None:
        return Check(WARN, "quota-axi", "not on PATH: the usage gauge reads unknown", "optional; install quota-axi.")
    done = runner.run(USAGE_ARGV, timeout=USAGE_TIMEOUT_S)
    # Exit 1 means every provider failed, and quota-axi still prints a report saying why.
    if done.returncode in (0, 1) and done.stdout.strip().startswith("{"):
        windows, reason = parse_quota(done.stdout)
    else:
        windows, reason = {}, "quota-axi failed: %s" % (done.stderr.strip()[:120] or "exit %d" % done.returncode)
    if reason is None:
        return Check(OK, "quota-axi", "fresh: %s" % ", ".join("%s %d%% left" % (n.replace("_", " "), w.left) for n, w in windows.items()))
    if "keychain_prompt_required" in reason or "auth_required" in reason:
        return Check(WARN, "quota-axi", reason,
                     "run `quota-axi --allow-keychain-prompt` once by hand and choose Always Allow.")
    return Check(WARN, "quota-axi", reason, "run `quota-axi --provider claude` by hand to see why.")


def check_lavish(which) -> Check:
    if which("lavish-axi") is None:
        return Check(WARN, "lavish-axi", "not on PATH: SHOW ME opens a PR, but no review board or report",
                     "optional; install lavish-axi.")
    return Check(OK, "lavish-axi", "on PATH")


def run_checks(home: Path, runner, which: Optional[Callable[[str], Optional[str]]] = None,
               clock: Callable[[], float] = time.time) -> list[Check]:
    which = which or shutil.which
    checks = [check_home(home)]
    if checks[0].status == OK:
        checks.append(check_ready(home, runner))
        checks.append(check_yes_rule(home))
        now = clock()
        for ref in discover_homes(home):
            checks.append(check_summary(ref, now))
            checks.append(check_ledger(ref))
            checks.append(check_pr_health(ref))
    herdr, agents = check_herdr(runner, which)
    checks += [herdr, check_context(agents), check_quota(runner, which), check_lavish(which)]
    return checks


def main(home: Path, runner, out: Optional[TextIO] = None, which: Optional[Callable[[str], Optional[str]]] = None,
         clock: Callable[[], float] = time.time) -> int:
    """Print every check and a tally. 1 when a required piece is missing, else 0."""
    out = out or sys.stdout
    out.write("helm doctor, read only: %s\n" % home)
    checks = run_checks(home, runner, which, clock)
    for check in checks:
        out.write(check.line() + "\n")
    tally = {status: sum(1 for c in checks if c.status == status) for status in (OK, WARN, MISSING)}
    out.write("%d ok, %d warn, %d missing. Setup guide: %s\n" % (tally[OK], tally[WARN], tally[MISSING], SETUP_GUIDE))
    return 1 if tally[MISSING] else 0


def _age(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 120:
        return "%ds" % seconds
    if seconds < 7200:
        return "%dm" % (seconds // 60)
    if seconds < 172800:
        return "%dh" % (seconds // 3600)
    return "%dd" % (seconds // 86400)


def _size(size: int) -> str:
    if size < 1024:
        return "%d B" % size
    if size < 1024 * 1024:
        return "%.1f KB" % (size / 1024)
    return "%.1f MB" % (size / (1024 * 1024))
