"""Fixture homes and a fake command runner. Nothing here touches a real firstmate home or herdr."""

from __future__ import annotations

import json
import os
import plistlib
import shutil
import time
from pathlib import Path

from helm.bridge.commands import LAVISH_LIST, LAVISH_OPEN, OPEN_URL, Completed, check_allowed, command_signature

FIXTURES = Path(__file__).parent / "fixtures"

READY_OK = {
    "schema": "fm-primary-ready.v1",
    "home": "fixture/primary",
    "observed_at": "2026-11-09T00:00:00Z",
    "lock": {"state": "held", "pid": 1, "live_harness": True},
    "wake_consumer": {"state": "healthy", "reason": "supervised", "beacon_age_seconds": 3},
    "posture": {"state": "present"},
    "can_receive": True,
}


# Shaped like `quota-axi --provider claude --json` (schema 5): the README example, trimmed.
QUOTA_OK = {
    "generatedAt": "2026-11-09T00:00:00.000Z",
    "schemaVersion": 5,
    "providers": [
        {
            "provider": "claude",
            "accountKeys": ["default"],
            "windows": [
                {"id": "five_hour", "label": "session", "kind": "session", "percentRemaining": 62.7,
                 "resetsAt": "2026-11-09T02:00:00.000Z"},
                {"id": "seven_day", "label": "week", "kind": "weekly", "percentRemaining": 40,
                 "resetsAt": "2026-11-12T00:00:00.000Z"},
                {"id": "model:fable", "label": "Fable week", "kind": "model", "percentRemaining": 71},
            ],
            "state": {"status": "fresh", "stale": False},
        }
    ],
}


def ioreg_root(locked: bool, uid: int | None = None, on_console: bool = True) -> str:
    """`ioreg -n Root -d1 -a` output, trimmed to the keys the lock check reads (plus one it ignores)."""
    session = {"kCGSSessionUserIDKey": os.getuid() if uid is None else uid, "kCGSSessionOnConsoleKey": on_console,
               "kCGSessionLoginDoneKey": True, "kCGSSessionUserNameKey": "fixture"}
    if locked:
        session["CGSSessionScreenIsLocked"] = True
        session["CGSSessionScreenLockedTime"] = 1794292326
    root = {"IOConsoleLocked": locked, "IOConsoleUsers": [session], "IOObjectClass": "IORegistryEntry"}
    return plistlib.dumps(root).decode("utf-8")


def lavish_listing(*rows: tuple[str, str, str]) -> str:
    """`lavish-axi` output, trimmed: the sessions table (file, status, url), then the help it always prints."""
    lines = ["bin: ~/.nvm/versions/node/v24/bin/lavish-axi", 'description: "Lavish Editor helps agents"',
             "sessions[%d]{file,status,url,pending_prompts,listener}:" % len(rows)]
    lines += ['  %s,%s,"%s",0,none' % row for row in rows]
    lines += ["playbooks[1]{id,use_when}:", '  diagram,"Explain relationships, flows"']
    return "\n".join(lines) + "\n"


def make_homes(tmp: Path) -> tuple[Path, Path]:
    """Copy the fixture homes into tmp, date the 'landed today' row, and list the second mate."""
    primary = tmp / "primary"
    mate = tmp / "mate1"
    shutil.copytree(FIXTURES / "primary", primary)
    shutil.copytree(FIXTURES / "mate1", mate)
    summary = primary / "state" / "home-summary.json"
    summary.write_text(summary.read_text().replace("TODAY", time.strftime("%Y-%m-%d")))
    (primary / "data").mkdir(exist_ok=True)
    (primary / "data" / "secondmates.md").write_text(
        "- mate1 - Own the gamma project. Hard rules: none (home: %s; scope: gamma; projects: gamma; added 2026-11-09)\n"
        "- remote1 - A remote mate with no local home listed\n" % mate
    )
    return primary, mate


def herdr_agents(primary: Path, blocked: bool = True) -> list[dict]:
    agents = [
        {"agent": "claude", "agent_status": "working", "cwd": str(primary), "pane_id": "w0:p1",
         "terminal_title_stripped": "firstmate", "tokens": {"title": "firstmate"}},
        {"agent": "claude", "agent_status": "idle", "cwd": "/tmp/idle", "pane_id": "wI:p1",
         "terminal_title_stripped": "idle agent"},
    ]
    if blocked:
        agents.append({"agent": "codex", "agent_status": "blocked", "cwd": "/tmp/scratch", "pane_id": "wC:p3",
                       "terminal_title_stripped": "Approve command?", "tokens": {"title": "scratch-agent"}})
    return agents


class FakeRunner:
    """Answers the allowlisted commands from canned data and records every call.

    It applies the real allowlist, so a test fails if the bridge tries anything else.
    """

    def __init__(self, primary: Path, allow_writes: bool = False, page_roots=()):
        self.primary = primary
        self.allow_writes = allow_writes
        self.page_roots = list(page_roots)
        self.calls: list[list[str]] = []
        self.envs: list[dict] = []
        self.ready: dict | None = dict(READY_OK)
        self.agents: list[dict] | None = herdr_agents(primary)
        self.note_rc = 0
        self.note_outcome = "created"
        self.note_path = "/x"
        self.announce_rc = 0
        self.receipts: dict | None = {"schema": "fm-inbox-receipts.v1", "pending": [], "handled": [], "replies": []}
        self.quota: dict | None = json.loads(json.dumps(QUOTA_OK))
        self.ioreg: str | None = ioreg_root(locked=False)
        self.lavish: str | None = lavish_listing()
        self.open_rc = 0

    def calls_for(self, *signature: str) -> list[list[str]]:
        return [c for c in self.calls if command_signature(c) == signature]

    def run(self, argv, env=None, timeout=10.0) -> Completed:
        check_allowed(argv, self.allow_writes, self.page_roots)
        self.calls.append(list(argv))
        self.envs.append(dict(env or {}))
        sig = command_signature(argv)
        if sig == ("fm-inbox.sh", "ready"):
            return Completed(0, json.dumps(self.ready), "") if self.ready else Completed(1, "", "boom")
        if sig == ("herdr", "agent", "list"):
            if self.agents is None:
                return Completed(1, "", "no herdr")
            return Completed(0, json.dumps({"id": "cli:agent:list", "result": {"agents": self.agents}}), "")
        if sig == ("fm-inbox.sh", "note"):
            rid = argv[argv.index("--request-id") + 1]
            out = {"schema": "fm-inbox-note.v1", "outcome": self.note_outcome, "id": "note-1", "request_id": rid,
                   "saved": True, "announced": self.note_rc == 0, "acknowledged": False, "path": self.note_path}
            return Completed(self.note_rc, json.dumps(out), "" if self.note_rc == 0 else "wake failed")
        if sig == ("fm-inbox.sh", "announce"):
            return Completed(self.announce_rc, "{}", "")
        if sig == ("fm-inbox.sh", "receipts"):
            if self.receipts is None:
                return Completed(1, "", "boom")
            out = dict(self.receipts)
            if "--after" in argv:  # like fm-inbox.sh: only replies past the cursor
                after = argv[argv.index("--after") + 1]
                out["replies"] = [r for r in out.get("replies") or [] if r.get("cursor", "") > after]
            return Completed(0, json.dumps(out), "")
        if sig == ("herdr", "agent", "focus"):
            return Completed(0, "", "")
        if sig == ("quota-axi", "--provider", "claude", "--json"):
            return Completed(0, json.dumps(self.quota), "") if self.quota else Completed(127, "", "quota-axi: not found")
        if sig == ("ioreg", "-n", "Root", "-d1", "-a"):
            return Completed(0, self.ioreg, "") if self.ioreg is not None else Completed(127, "", "ioreg: not found")
        if sig == LAVISH_LIST:
            return Completed(0, self.lavish, "") if self.lavish is not None else Completed(127, "", "lavish-axi: not found")
        if sig in (LAVISH_OPEN, OPEN_URL):
            return Completed(self.open_rc, "", "" if self.open_rc == 0 else "could not open")
        raise AssertionError("unexpected command %s" % argv)
