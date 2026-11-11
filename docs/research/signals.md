# Signals: what Helm shows, what it may do, and how it talks

Researched 2026-11-09, read only, against a local firstmate checkout and herdr 0.9.5 (socket API protocol 22, cyber-mux 0.9.1). Nothing in either was changed.

Firstmate and herdr are local tools, so sources are file paths, script headers, and CLI commands rather than URLs. Paths are relative to a firstmate home unless they start with `/`. The script header named for each contract owns it; the bridge should re-read it before relying on a field.

## Architecture

```
Helm deck  <-- USB serial, Harness Pro style binary frames -->  helm-bridge (on the Mac)
                                                                  |
  reads (never writes):                                           |  writes (one path):
  state/home-summary.json       state of record, per home         |  bin/fm-inbox.sh note --request-id <id> --json
  state/fleet-ledger.jsonl      event edges, per home             |    (primary home only)
  state/pr-health.json          PR checks and conflicts           |
  bin/fm-inbox.sh ready         is firstmate listening            |  navigation only:
  bin/fm-inbox.sh receipts      firstmate's replies               |  herdr agent focus <pane>   (SHOW ME key)
  herdr agent list              working / blocked, all panes      |
```

Four rules:

1. **Thin device.** Firmware draws what it is told and reports key and knob events. It knows nothing about firstmate or herdr.
2. **Read published records only.** Never `bin/fm-wake-drain.sh`, never a write under any home's `state/` or `data/`.
3. **One write path.** Every acting key becomes one `bin/fm-inbox.sh note` in the primary home. The bridge builds the note text from a closed list of intents, so the device cannot send free text. Firstmate then acts through its own guarded commands (`bin/fm-pr-merge.sh`, `bin/fm-captain-hold.sh answer`, `bin/fm-send.sh`) or declines and says why.
4. **Fail visible.** No heartbeat from the bridge for 10 seconds, or `can_receive` not true, shows as "unknown", never as green.

Why notes and not direct commands:

- `bin/fm-inbox.sh` calls itself "the captain's out-of-band capture surface", and `note` "Writes a durable record and appends ONE `check` wake".
- `AGENTS.md` section 8 tells firstmate to act on "captain inbox notes" and to publish durable answers with `bin/fm-inbox.sh reply <id>`.
- Firstmate's own voice relay already works this way: "The relay reads records and queues work. It never changes a project" (`docs/voice-relay.md`). Helm is its physical sibling.

Why not `bin/fm-captain-hold.sh answers` as a second write path: its key is a captain-held task id, but in the home studied, about half of the open decision rows were `needs-decision` status rows whose `id` is a worker task and whose `key` is a status-log key, which `answers` would skip. The summary also carries no options or recommendation field, so the bridge cannot know what a key press would answer. Structured options are a v2 path (see [README](README.md#beyond-v1)).

## What the deck shows, and where it comes from

| Signal | Source | Notes |
| --- | --- | --- |
| Counts: open decisions, working workers, queued, landed | `state/home-summary.json` `counts` | Poll the file's mtime every 2 seconds; re-read on change. Plain file read. |
| Decision list and text | `decisions_open[]`: `id`, `key`, `verb`, `summary`, `question`, `reason`, `hold_bucket`, `hold_age_days`, `source` | Two row kinds: `verb: captain-hold` (from the backlog) and `verb: needs-decision` (from a status log). Show both; they differ only in the note text the bridge writes. |
| Workers | `active_children[]`: `id`, `kind`, `state`, `repo`, `name`, `doing` | |
| Recently landed | `landed[]`: `title`, `pr_url`, `completion` | Drives the "merged" sweep. |
| New events (the attention edge) | `state/fleet-ledger.jsonl`: `task.status` with `state` in `needs-decision`, `blocked`, `failed`; `task.pr_ready`; `task.merged` | Opt-in per home with `config/fleet-ledger`. Absent in the primary home today; present in all three local second mate homes. Fallback when off: diff successive summaries. |
| PR checks and conflicts | `state/pr-health.json`, schema `fm-pr-health.v1`: `prs` keyed by PR URL, each with `checks` and `conflicts` | On in the primary home (`config/pr-health-monitor` exists). Keeps YES dark when a PR is known red or conflicted. |
| Is firstmate listening | `bin/fm-inbox.sh ready`, schema `fm-primary-ready.v1`: `wake_consumer`, `posture`, `can_receive` | Every 15 seconds. "It never acquires the session lock." |
| Did firstmate handle my key press | `bin/fm-inbox.sh receipts` | Only while an intent is pending. Shows firstmate's reply text. |
| Agents working or waiting, all panes | `herdr agent list` (JSON; `agent_status` is one of `idle`, `working`, `blocked`, `done`, `unknown`) | Poll every 3 seconds. Count `working` and `blocked`. |

### The home summary

`state/home-summary.json` is published by `bin/fm-home-summary-refresh.sh`. Its header: the file is "the exact `fm-fleet-snapshot.sh --secondmate-home-summary` document for this FM_HOME", and "the ledger path holds either the prior complete document or the new complete document, never torn output". Schema `fm-secondmate-home-summary.v1`, hold classifier `fm-captain-hold-buckets.v1`.

Freshness: session start, the watcher, spawn, and teardown refresh it as a side effect. It is republished on events, not on a clock, so during a quiet stretch it can be minutes old while everything is healthy. Do not treat its age as a fault. Liveness comes from `bin/fm-inbox.sh ready`; the summary is the state of record whatever its age. The bridge must not call `bin/fm-home-summary-refresh.sh` itself.

Hold buckets: every captain hold is exactly one of `blocked`, `dated`, `aged`, or `live`, and only `live` means "waiting on the captain now" (`bin/fm-fleet-snapshot.sh` header).

### The fleet ledger

`state/fleet-ledger.jsonl`, documented in `docs/fleet-ledger.md` as "the stable, documented hook for firstmate status". JSON Lines, append-only, `v: 1`, events `task.dispatched`, `task.status` (`state`, `key`, `text`), `task.pr_ready` (`pr`), `task.merged` (`via`, `pr`), `task.cleaned_up`.

Limits that matter: records can repeat ("a reader that must not double-count should tolerate duplicates"), there is no sequence number, the file is never rotated, and status text is copied verbatim from `state/`.

### herdr

- `herdr agent list` returns, per agent: `agent`, `agent_status`, `pane_id`, `tab_id`, `workspace_id`, `cwd`, `terminal_title`, `focused`, `state_change_seq`, `completion_seq`, and `tokens`.
- The herdr skill text (`herdr --skill`): "`blocked` means Herdr recognized an approval or question UI"; "`unknown` ... does not prove completion"; reads do not mark a completion seen, focus commands do.
- The socket API (`herdr api schema --json`) also has `events.subscribe` and `pane.agent_status_changed`; a poll is enough for v1.
- Never read `idle` as "finished". Firstmate's own architecture doc: herdr's native idle "reads idle while a worker blocks on its own long-running foreground tool call", so firstmate trusts a native busy but not a native idle.
- Mapping a firstmate task to its pane for SHOW ME: `state/<id>.meta` records `herdr_session`, `herdr_workspace_id`, `herdr_tab_id`, and `herdr_pane_id` for herdr-backed tasks.

### Second mate homes (decision D19)

The captain decided the bridge also reads second mate homes directly, not only through the primary's summary.

- **Finding them.** Each second mate has a `state/<id>.meta` in the primary home with `kind=secondmate` and `home=<path>`. A remote one also has `remote_host=`; its files live on that host.
- **Local homes.** Each publishes its own `state/home-summary.json` (same schema) and, in the home studied, its own `config/fleet-ledger` and `state/fleet-ledger.jsonl`. In the home studied, every registered second mate was local and every summary was readable.
- **Remote homes.** Read the parent's cached copy under `state/secondmate-summary-cache/`, which `bin/fm-fleet-snapshot.sh` refreshes ("a valid prior copy under FM_SNAPSHOT_CACHE_DIR used when the live read fails"). The bridge never connects to a remote host itself. No remote second mates exist here today, so this path is untested.
- **Duplicates.** The primary's summary already shows second mate questions as `needs-decision` rows whose `id` is the second mate's task id. In the home studied, about half of the primary's rows came from second mates, and some of one second mate's rows had a key of the form `captain-hold-<held task id>-<n>` matching a captain hold in that second mate's own summary. The rest were that second mate's own status lines with no matching row in its home. Rule for the bridge: show each home's own rows under that home, and hide a primary row only when its `id` is a second mate and its key names a hold present in that second mate's summary. This key shape is an observed convention, not a documented contract, so verify it in phase 0.
- **Writing.** Notes still go only to the primary home's inbox, naming the home and task. The primary relays to its second mate. The bridge never writes into a second mate's inbox.

### Privacy

Decision text can name clients and projects. The default screen shows counts and short ids; the full question appears only when the captain presses the knob on an item (D18), the same model as the voice relay's `voice-read-scope`. Over USB nothing leaves the desk.

## Keys and intents

Four keys and one push knob. A key is lit only when its action applies to the selected item.

| Control | Intent | Note the bridge writes (request id in brackets) | What firstmate does |
| --- | --- | --- | --- |
| YES (hold 1 s) | `yes` | "Captain, from the Helm deck, held to confirm: YES on `<home>` / `<task>` / `<key>`. If this is a merge ask, merge `<PR URL>` under your normal checks. Otherwise go with your single recommended option. If neither applies, change nothing and reply." [`helm-yes-<task>-<key>-<day>`] | Runs `bin/fm-pr-merge.sh`, which refuses unless the PR is open, not a draft, mergeable, free of conflicts, and green at the current head; or records the answer with `fm-captain-hold.sh answer`; or replies that it needs the captain in chat. |
| LATER (hold 1 s) | `later` | "Captain, from the Helm deck: defer `<home>` / `<task>` / `<key>` until tomorrow." | Re-holds with `--until`. The captain-hold skill: "When the captain says 'later', that is an answer too". |
| HOLD (hold 1 s) | `hold` | "Captain, from the Helm deck: do not proceed on `<home>` / `<task>` / `<key>`. Raise it with me in chat." | Nothing merges or resumes. |
| SHOW ME (tap) | `focus` | No note. `herdr agent focus <pane>` for the worker's pane, or firstmate's own pane for a decision. | Not involved. herdr marks the pane seen, which is correct. |
| Knob | scroll / press to open or confirm / long press to mute | Device only. Any touch marks new items as seen. | |

Why a generic YES: firstmate wrote the question and knows whether it gave one recommendation; the bridge does not. YES is a request, so the deck shows "queued" and then firstmate's reply.

Note handling: always pass `--request-id` and `--json`. Exit 3 means "saved but the wake failed": repair with `bin/fm-inbox.sh announce <id>` and do not send again.

Merge authority (D14): `AGENTS.md` says "Never merge a PR without the captain's explicit word." For a held YES to count as that word without a second confirmation in chat, firstmate's rules need one added sentence, roughly: a captain inbox note beginning "Captain, from the Helm deck" is a current explicit captain instruction for exactly the merge or answer it names. That is a firstmate change, outside this repo; until it lands, YES works as a request firstmate may confirm in chat.

## The attention model

| State | Light bar and sound | Enters when | Leaves when |
| --- | --- | --- | --- |
| Calm | Steady and dim. Counts on screen. | Nothing unseen. | A new event arrives. |
| New | Pulse, one chime (unless muted). One light per unseen item, colored by kind: red for needs-captain, amber for a blocked or failed worker or a blocked herdr agent, blue for PR ready. | A decision opens, a worker reports `blocked` or `failed`, a PR becomes ready, a herdr agent enters `blocked`. | The captain touches any control. |
| Unknown | Amber, no green anywhere. Screen says which link is down. | No bridge heartbeat for 10 s, or `can_receive` false or unknown. | The link returns. |

Why edge-triggered: a busy home can have a dozen open decisions, some over a month old, so "anything open" would keep the light red forever (D2). Merged work gets a two second green sweep with no chime. Seen state lives only in the bridge. Colors follow firstmate's own display ranks (`needs-captain`, `problem`, `running`, `done`, `docs/herdr-backend.md`), so the deck and the herdr sidebar agree.

## The bridge

- **Where and what:** a Python 3 program in this repo, `pyserial` its only dependency, started at login by a launchd agent (D10).
- **Never called:** `fm-wake-drain.sh`, `fm-inbox.sh drain`, `fm-send.sh`, `fm-control.sh`, `fm-pr-merge.sh`, `fm-teardown.sh`, `fm-home-summary-refresh.sh`, `tasks-axi`, and every herdr command except `agent list` and `agent focus`.
- **Simulator:** the bridge can talk to a terminal program over a pseudo-terminal instead of a serial port. That simulator is phase 0 of the build (D1).

## The device link

Decision D9: USB serial carrying the Harness Pro's binary frame ([harness-pro.md](harness-pro.md#how-it-talks-to-the-computer)).

| Field | Helm's use |
| --- | --- |
| Magic | `0xA5` then a Helm-specific second byte. Not `0x48` ("H", Harness) and not the sibling product's byte, so the Harness daemon and Helm's bridge can never adopt each other's devices. The value is a firmware design choice. |
| Version | `1` |
| Type | `0x01` JSON (with a `"t"` discriminator) and `0x04` log line. Helm sends no PCM. Firmware slices (`0x03`) only if over-the-cable updates are added later. |
| Length | u16, little-endian, payload at most 8192 bytes |
| CRC | CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF; check value 0x29B1 for "123456789") |

Messages:

- Device to bridge: `hello` (firmware version, product, protocol, capability strings), `key` and `knob` events, each intent with a request id.
- Bridge to device: the full screen model (counts, list rows, selected item, light bar state), `ack` for each intent, firstmate's reply text, and a heartbeat.
- The bridge resends the full model every 2 seconds and after any bad frame, so a dropped frame heals by itself. Every intent carries a request id, so a retry is a replay, not a second note.

Why keep the CRC: the Pro's own USB link "loses bytes host to device" ([harness-pro.md](harness-pro.md#how-it-talks-to-the-computer)). Helm talks through the Waveshare board's CH343P USB-to-UART bridge rather than the P4's USB Serial/JTAG ([parts.md](parts.md)), a different path. Whether it drops bytes is unverified, so the design assumes it can. Because the same port also carries boot text and firmware logs, the magic, length, and CRC let the bridge skip non-frame bytes, exactly as the Pro does.

## Not verified

- How firstmate reacts to Helm's notes in practice, and how fast the summary republishes on a busy day (measure in phase 0).
- The second mate duplicate rule above (an observed key shape, not a contract).
- The remote second mate cache path (no remote second mates here).
- Whether the CH343P path drops bytes.
