# Helm host bridge

The program on the Mac that sits between the Helm deck and firstmate and herdr. The deck stays thin: it draws the `Model` the bridge sends and reports key and knob `Event`s (see `helm/contract.py`). Design decisions: [docs/research/README.md](../../docs/research/README.md#decisions).

## Run it

```sh
# One Model as JSON from the firstmate home, read only, then exit
FM_HOME=~/path/to/firstmate python3 -m helm.bridge --once

# Against the deck or the simulator (dry run: note, focus, and open commands are logged, not run)
python3 -m helm.bridge --port /dev/ttys012

# JSON lines on stdin and stdout instead of the serial frame, for poking by hand
python3 -m helm.bridge --port -

# Send real inbox notes, focus real herdr panes, and open boards and reports
python3 -m helm.bridge --port /dev/cu.usbmodem1101 --live
```

Python 3.11 or newer, standard library only. `--port <path>` uses `helm.wire.open_transport(path)`, the serial and pty transport with the Harness Pro binary frame, which comes with the device and wire protocol work. `--home` defaults to `$FM_HOME`; with neither, the bridge exits and says to pass one.

Tests: `python3 -m unittest discover -s tests -t .`

## What it reads (never writes)

| Source | How often |
| --- | --- |
| `state/home-summary.json` and `state/pr-health.json` in each home | mtime check every 2 s |
| `state/fleet-ledger.jsonl` in each home, when present | every loop step, new lines only |
| `bin/fm-inbox.sh ready` (primary) | every 15 s |
| `bin/fm-inbox.sh receipts` (primary) | every 5 s, only while a note is waiting for a reply |
| `herdr agent list` (also the context gauge) | every 3 s |
| `/usr/sbin/ioreg -n Root -d1 -a` (is the Mac locked) | every 3 s, and again right before acting on a key |
| `quota-axi --provider claude --json --no-credential-refresh` | every 5 min, on a thread |
| `state/<id>.meta` and `state/<id>.status` | when items are rebuilt, for the herdr pane and the item age |
| `lavish-axi` (the open Lavish sessions), `state/<id>.status`, and `data/<id>/report.md` | on a SHOW ME tap only |

Homes are the primary plus every second mate listed in its `data/secondmates.md` (D19). Each item carries the label of its home (`primary` or the second mate's id).

## What it runs

Every command goes through one allowlist (`commands.py`): `fm-inbox.sh ready | receipts | note | announce`, `herdr agent list | focus`, `quota-axi --provider claude --json`, `ioreg -n Root -d1 -a`, and SHOW ME's three viewers. Anything else is refused before a process starts, which covers the report's never-call list. `note`, `announce`, `focus`, and the two viewer opens are refused unless the bridge was started with `--live`, on top of the dry-run switch in the intent code.

The viewers match a whole argv, not a prefix, and must be named bare (found on `PATH`):

- `lavish-axi` with no arguments, which lists the open Lavish sessions. A read.
- `open <url>` with exactly one argument: `http://127.0.0.1:<port>/session/<hex id>` (or `localhost`), or `https://github.com/<owner>/<repo>/pull/<n>`. No other host, scheme, path, or flag.
- `lavish-axi <page.html> [--reopen] [--no-gate]`, where the page is an absolute path to an existing `.html` file that, after symlinks, is inside the helm cache or a firstmate home's `data/` directory, and not under a dot directory (so `data/.secrets` is out). No other `lavish-axi` subcommand (`poll`, `share`, `end`, `stop`, ...) passes.

- A held YES, LATER, or HOLD on the selected item becomes exactly one `fm-inbox.sh note --request-id <id> --json -- <text>` in the primary home. The request id is fixed per item, intent, and day, so pressing again is a replay, not a second note. Exit 3 (saved, wake failed) is repaired with `fm-inbox.sh announce`, never by sending again. YES is dark when the PR is known red or conflicted.
- The YES note begins with exactly `Captain, from the Helm deck, held to confirm: YES`, which firstmate treats as the captain's word for the one task, key, or PR it names (D14). It asks firstmate to merge under its normal checks if it is a merge ask, and otherwise to go with its single recommended option only if it gave exactly one (D15).
- SHOW ME (tap) runs `herdr agent focus <pane>`: the worker's pane from `state/<id>.meta`, or firstmate's own pane for a decision (D17). Then, when the item has one, it opens the item's Lavish board, report, or PR in the browser (`show.py`). Focus goes first because it is instant; listing the Lavish sessions takes about 1.5 s. Resolution only reads, and the first match wins:
  1. **A live board.** A session `lavish-axi` lists whose id a board URL in the item's text names (its detail, which carries the hold or decision text, or the task's newest 20 status lines), or whose file is a report path the item names, or the newest session whose file sits in the task's own `data/<task>/` directory. It opens with `open` on `127.0.0.1` and the session's port, whatever host the text or the listing names, so a URL in a status line never sends the browser anywhere else. A board URL whose session is no longer listed is skipped.
  2. **The report**, in the item's own home: a `data/...` `.md` or `.html` path the item names, else `data/<task>/report.md`. Paths outside that home's `data/`, through a symlink out of it, or under a dot directory are ignored. An HTML report opens with `lavish-axi` as it is. Markdown is rendered (`report_html.py`, standard library only, every piece of text escaped) to one self-contained page per home, task, and report in the helm cache (`~/Library/Caches/helm/reports/`, or `$XDG_CACHE_HOME/helm` off macOS), re-rendered on every tap, and opened with `lavish-axi <page> --reopen --no-gate`: a tap is an explicit ask, so it reopens a board the captain ended and skips Lavish's layout curtain. Images beside the report are embedded (up to 8 MB each, 24 MB in all); others show as a labelled placeholder. The bridge refuses to write a page under a firstmate home.
  3. **The PR**, `open https://github.com/...`, for an item with a PR and no board or report.
  4. Otherwise focus only, as before. herdr items always only focus.

  In a dry run the Lavish listing still runs (it is a read), the open command is logged, and no page is written. The result says what happened, for example `opening board for widget-pricing` or `dry run: report for widget-pricing logged`. The deck shows no result screen for SHOW ME today, so the contract is unchanged: the result text is for the bridge log and any later screen. SHOW ME stays dark on an item without a herdr pane, as before, even when it has a PR.

## Attention

The light means something new since the captain last touched the deck (D2). Everything open when the bridge starts is the baseline and counts as seen. A new decision, a blocked or failed worker, a PR waiting on the captain, or a blocked herdr agent makes the deck `new` and sets `chime` on the next Model only. Any touch (key, knob, select, seen) marks everything seen. The deck is `unknown` whenever firstmate's `can_receive` is not true. Seen state lives in the bridge only.

With the fleet ledger on, a `needs-decision`, `blocked`, `failed`, or `pr_ready` record shows its item right away, before the summary republishes; the summary takes over once it is published after the event. Turning the ledger on backfills history, so the bridge starts at the end of the file and ignores records older than 10 minutes. Without the ledger, new items come from diffing successive summaries.

A green sweep on merge has no field of its own in the contract: the device can sweep when `counts.landed_today` goes up.

## Usage gauge, away mode, projects

These three need no firstmate change and add fields with defaults (`Model.usage`, `Link.away`, `Item.project`), so an older deck ignores them and a newer deck reads an older bridge's models as "unknown", "not away", and "no project".

- **Usage gauge.** `usage` carries what is left of the Claude 5 hour and weekly windows (`five_hour_left`, `week_left`, percent, rounded down) and the seconds until each resets, from `quota-axi`. Only a `fresh` reading counts: quota-axi missing, failing, timed out, not signed in, or serving a cached (`stale`) reading leaves every value null, which the deck shows as unknown, never full. The deck shows the gauge as a line on Home and on the calm light bar (lights for what is left of the tighter window, none lit while unknown). A reading older than 15 minutes is dropped too. quota-axi asks the vendor and can take seconds, so it runs on a thread and models keep flowing. `--no-credential-refresh` keeps the bridge from renewing a session itself. On macOS, quota-axi reads Claude's credentials from the Keychain only after `quota-axi --allow-keychain-prompt` has been run once by hand (approve with "Always Allow"); until then the bridge logs `claude quota auth_required (keychain_prompt_required)` and the gauge reads unknown.
- **Follow away mode.** While `fm-inbox.sh ready` reports posture `away` or `quiet`, `link.away` is true: the bridge drops YES, LATER, and HOLD from every item (so even an older deck keeps those keys dark), refuses a held one with "keys locked: firstmate is away", and sends no chime. SHOW ME still works, and the light bar still shows new items. A chime suppressed while away does not ring on return. Posture `unknown` is not away.
- **Projects.** `project` names the repo an item belongs to: the active child's `repo` for its task, else the basename of the `project` path in the task's meta (not for a second mate, whose meta names its own checkout), else the repository in its PR URL. Captain holds and herdr agents usually have none. The deck's knob filters the list by it.

## Context gauge, Mac lock, project tints

The same rule holds here: new fields have defaults (`Model.context`, `Link.mac_locked`), both decoders treat them as optional, and the 8192-byte frame still fits (tested).

- **Context gauge.** herdr itself does not count tokens: each agent's `tokens` is a map of short strings that herdr integrations report for the sidebar. The usagebar plugin (senna-lang/herdr-agent-usage) writes `tokens.context` as `⛁ 49% (492k)` (percent of the window used, then tokens), with `⚠️` from 80 %, narrower `49% (492k)` or `49%`, or `5h 72% · ⛁ 14% (136k)` with several Claude accounts. `context.py` reads the percent from those forms only; `compacted (31k)`, a bare token count, no token, or no usagebar is unknown. `context` carries the fullest agent's percent (`top_used`) and name (`top_agent`, its title token, else its terminal title, else its pane), and how many agents are at 80 % or more (`near_limit`, usagebar's own warning threshold). No reading at all, or herdr unavailable, leaves all three null: unknown, never empty. The deck shows a line on Home, amber while any agent is near, and turns the last light of the calm bar amber.
- **Lock keys when the Mac is locked.** `lock.py` reads `ioreg -n Root -d1 -a` (read only, in every macOS install; about 22 ms with the plist parse) every 3 s: the session counts as locked when the registry root's `IOConsoleLocked` is true, or this user's session in `IOConsoleUsers` has `CGSSessionScreenIsLocked` true or `kCGSSessionOnConsoleKey` false (another user has the console). The user id and on-console keys are public (CoreGraphics `CGSession.h`); `IOConsoleLocked` and `CGSSessionScreenIsLocked` are not documented by Apple. While locked, `link.mac_locked` is true, the bridge drops every action from every item (SHOW ME too, so even an older deck keeps every key dark), and refuses a held key or a SHOW ME tap with "keys locked: the Mac is locked", reading the lock again first so a lock since the last poll still counts. Chimes still ring and new items still light: the deck still tells you something is waiting. Limits: a display that sleeps without locking is not detected (Apple silicon has no `IODisplayWrangler`); set "Require password after screen saver begins or display is turned off" to immediately so a display sleep locks. Unknown (no ioreg, as off macOS, or output it cannot read) leaves the keys unlocked, as before, and is logged once.
- **Project tints.** The deck tints each unseen item's light, and its list row's color strip, by project. The rule that keeps firstmate's kind colors readable: a tint never changes the hue, it only mixes white into the kind's color (0 % with no project, else 18, 36, or 54 % from a 32-bit FNV-1a hash of the name), so red, amber, blue, and green always read as themselves. Hue tints were tried and dropped: red and amber are 38 degrees apart, and every hue but cyan pulls one toward the other. The bridge sends nothing new for this; the deck derives it from `Item.project`. See `firmware/core/helm_lights.h`.
