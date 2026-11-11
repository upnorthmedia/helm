# Helm research

> **Decision record of 2026-11-09.** This page records the research and decisions as they stood on 2026-11-09, before any firmware, bridge, or CAD existed. It is kept as the record of why Helm is shaped the way it is, not as a description of what is on `main`. What was built is in [docs/architecture.md](../architecture.md); how to set up a firstmate home for it is in [docs/firstmate-setup.md](../firstmate-setup.md).
>
> The main changes since: v2 moved to the 5 inch Waveshare ESP32-P4-WIFI6-Touch-LCD-5, turned landscape, with ESP-IDF and LVGL instead of Arduino (the 4 inch v1 is in git history at commit `b2f7670`); the deck links over the P4's native USB, not the CH343P; the bridge uses only the Python standard library; and the YES rule of D14 lives in each user's own firstmate home, as an opt-in, not in firstmate.

Helm is a desk device for the captain of a firstmate fleet running in herdr, modeled on the Autonomous Harness Pro. It does two jobs:

1. **Glance.** Show, without switching windows, whether anything new needs the captain: a decision opened, a worker blocked or failed, a PR ready, an agent in some herdr pane waiting on an approval.
2. **Answer the common cases.** Give the few most common replies ("merge it", "go with your recommendation", "later", "not yet", "show me") with a key press, routed through firstmate so firstmate's own guards decide what happens.

The Harness Pro does the first job and deliberately not the second: it shows an agent's question but does not answer it on the device. Physical answer keys are Helm's reason to exist.

This is one merged research set, built from two earlier passes and a review of both, all dated 2026-11-09. It was written before any firmware, bridge, schematic, or CAD existed.

| Doc | What it covers |
| --- | --- |
| [harness-pro.md](harness-pro.md) | What the Harness Pro does and what is inside, from its product page and open-source firmware |
| [signals.md](signals.md) | What the deck shows and where each signal comes from, the keys and the notes they send, the attention model, the bridge, and the binary device link |
| [parts.md](parts.md) | The v1 parts list built around the Waveshare ESP32-P4 720 x 720 touch module, its USB ports, Arduino support, and custom keycaps |
| [case.md](case.md) | SendCutSend's design rules, and the Hammond 1595E plan, superseded by F2: the case is now sized to the parts, in [`case/`](../../case/README.md) |

## v1 in one page

- **Device:** a Waveshare ESP32-P4 4 inch 720 x 720 touch module, four MX keys with custom keycaps (YES, LATER, HOLD, SHOW ME), one push knob, an 8-LED light bar, and a buzzer, in a SendCutSend 5052 aluminum case sized to the parts, black anodized, with a 3D printed test version first ([`case/`](../../case/README.md); this replaced the Hammond 1595E plan, see D20).
- **Firmware:** Arduino (C++) on arduino-esp32. Thin: it draws what the bridge sends and reports key and knob events.
- **Link:** USB serial through the board's CH343P port, carrying the Harness Pro's binary frame (magic, version, type, length, payload, CRC-16) with Helm's own magic byte.
- **Bridge:** a Python program on the Mac. It reads each firstmate home's `state/home-summary.json`, the fleet ledger, `state/pr-health.json`, `bin/fm-inbox.sh ready` and `receipts`, and `herdr agent list`. Its only write is `bin/fm-inbox.sh note` in the primary home; its only herdr action is `herdr agent focus` for SHOW ME.
- **Attention:** the light pulses for what is new since the captain last touched the deck, not for everything open.

### Screens

1. **Home.** "N new for you", then open decisions, working workers, PRs ready, a herdr line ("3 working, 1 blocked"), and firstmate's listening state.
2. **List.** One row per item needing the captain, newest first: kind color, home, short id, age.
3. **Detail.** Knob press on a row: the question text, wrapped and scrollable; for a PR, repo, number, and checks.
4. **Confirm.** While a key is held: the exact item and action, with a one second fill bar.
5. **Result.** "Queued", then firstmate's reply from `receipts`.

The 720 x 720 touch screen allows touch scrolling too; the knob stays the primary control so the deck works without looking closely.

### Build order

| Phase | What | Cost (2026-11-09) | Exit |
| --- | --- | --- | --- |
| 0 | Bridge plus a terminal simulator speaking the device frames. Turn on the fleet ledger in the primary home. | $0 | One real merge ask answered from the simulator, and a few days living with the alerts. |
| 1 | Electronics on the bench: P4 module "hello" screen over Arduino first, then the serial link, knob, light bar, keys, hold-to-confirm. | About $85 to $95, plus about $7 of breadboard and wires | A week of daily use on the bench. |
| 2 | Box in hand and measured. Test coupon plus a raw plate from SendCutSend. | Box $16.36; first plate order roughly $40 to $55 **(estimate)** | Everything mounted in the raw plate. |
| 3 | Final anodized plate and module bracket with standoffs. Soldered wiring. Custom keycaps and label strip. | Roughly $40 to $55 for the plates **(estimate)**, plus printed keycaps (price unverified) | A finished deck. |

Total v1, electronics plus case: roughly $185 to $225 before shipping, tax, and printed keycaps **(estimate)**. SendCutSend prices need a file upload, so the case part is not quoted.

Phases 2 and 3 above assume the superseded 1595E box. After F2 the case is printed for fit tests first, then ordered from SendCutSend, following the order plan in [`case/README.md`](../../case/README.md#order-plan).

## Decisions

All decided on 2026-11-09. D3, D7, D9, D19, and D21 are the captain's recorded answers; the rest follow the review's recommendation.

### Approach

- **D1. What to build first:** the bridge and a software simulator, then parts. The risky part is whether a key-press note gets a useful, prompt reaction from firstmate and whether the alerts feel right, and that can be tested for $0.
- **D2. What the light means:** something new since the captain last touched the deck. A busy home can have a dozen open decisions, some over a month old, so "anything open" would be permanently red.

### Hardware

- **D3. Build style:** an ESP32-P4 720 x 720 touch board, the Waveshare ESP32-P4-WIFI6-Touch-LCD-4B (captain's choice). The Feather plus 2.0 inch screen stays the fallback if the display bring-up under Arduino stalls. See [parts.md](parts.md).
- **D4. Keys:** 4 action keys and 1 push knob.
- **D5. Key hardware:** MX switches on single NeoKey socket breakouts wired to header pins. The NeoKey 1x4 I2C board is out of stock.
- **D6. Sound:** a buzzer with one chime per new item; mute on a knob long press.
- **D7. Firmware:** Arduino (C++) (captain's choice). arduino-esp32 supports the ESP32-P4; Waveshare still recommends ESP-IDF and there is no ready Arduino display preset for this board, so the first firmware milestone is a working screen.
- **D8. Power:** USB only, no battery.

### Host and firstmate

- **D9. Link:** USB serial with the Harness Pro's binary frame (captain's choice), with a Helm-specific second magic byte and only the JSON and log frame types. See [signals.md](signals.md#the-device-link).
- **D10. Bridge:** Python 3 in this repo, started at login.
- **D11. What the bridge reads:** each home's summary for state and its fleet ledger for event edges, plus `pr-health.json`, `fm-inbox.sh ready` and `receipts`.
- **D12. Fleet ledger:** create `config/fleet-ledger` in the primary home when the bridge is built (the local second mate homes already have it). Costs: the file is never rotated and carries status text unscrubbed.
- **D13. How a key press reaches firstmate:** captain notes only, through `bin/fm-inbox.sh note` in the primary home.
- **D14. Held YES as the captain's word to merge:** yes, with a one second hold, the exact PR on screen, the key dark when the PR is known red or conflicted, and one sentence added to firstmate's rules saying a note beginning "Captain, from the Helm deck" is a current explicit captain instruction for exactly what it names. As built, that sentence is not a firstmate change: firstmate's default is that a note from an outside bridge does not approve a merge or answer a decision. It is a rule each user adds to their own firstmate home as an opt-in, now also pinning the commit the deck showed; its text is in [docs/firstmate-setup.md](../firstmate-setup.md). Without it, YES is a request firstmate confirms in chat.
- **D15. YES on a decision that is not a merge:** sends "go with your recommendation"; firstmate acts only if it gave exactly one.
- **D16. herdr state:** poll `herdr agent list` and count `working` and `blocked` across all panes.
- **D17. SHOW ME:** may focus a herdr pane (`herdr agent focus`); typing into panes stays forbidden.
- **D18. Default screen:** counts and short ids; full question text on a knob press.
- **D19. Which homes:** the primary home and every second mate home read directly (captain's choice): local homes through their own summary and ledger files, remote homes through the primary's cached summaries. Notes still go only to the primary. See [signals.md](signals.md#second-mate-homes-decision-d19) for the duplicate-row rule.

### Case

- **D20. Case (superseded by F2):** the captain's F2 answer replaced this with no stock box, a SendCutSend case sized to the parts with a 3D printed test version first; see [`case/`](../../case/README.md). The plan before F2: a Hammond 1595 sloped console with a SendCutSend 5052 face plate. Because of D3, the size is the **1595E** (209.98 x 124.98 mm panel); the 1595C the review named is too small for the 86.5 mm module. See [case.md](case.md).
- **D21. Finish and keys:** black anodized plate, custom keycaps (captain's choice), and a printed label strip. Prototype with relegendable keycaps; the printed-legend vendor is open. "Custom keys" is read as custom-legend keycaps; correct this if the captain meant something else.

### The research sets

- **D22. The two research sets:** this PR now holds the one merged set; the duplicate is to be deleted.

## Beyond v1

| Feature | Value | Cost |
| --- | --- | --- |
| Option keys (A / B / C) | Answer multi-option decisions by name | Firstmate publishes its Bearings decision payload (`fm-bearings-board.v1`) as a file; Helm becomes a bound source for `fm-captain-hold.sh answers` |
| Push to talk | Hold a key, say a note to firstmate | `fm-inbox.sh say` exists; needs its speech config and a microphone |
| Usage gauge | Light bar shows what is left of the Claude usage windows | `quota-axi --json` |
| Per-project view | Knob cycles projects; lights tinted by project | `active_children[].repo` |
| Context gauge | See an agent nearing its context limit | herdr agent `tokens` field |
| Follow away mode | Chimes off and keys locked while firstmate is away | `posture` in `fm-inbox.sh ready` |
| Lock keys when the Mac is locked | Nobody else can press YES | Mechanism not researched |
| Native USB link | Use the P4's own USB-C port with TinyUSB | Board already has the port |
| All-stop key | Ask firstmate to pause every worker | A note plus a firstmate rule |
| Wireless | Deck away from the Mac | Wi-Fi (the board has an ESP32-C6), token, encryption, battery |
| Bent metal shell | Product look | 3D sheet-metal model; about $55 or more |

## Main risks

- A held YES on a green PR merges it. Guards: the hold, the exact item on screen, firstmate's own merge checks.
- YES is a request: firstmate reads notes on its next turn, so the deck shows "queued" while it is busy.
- Arduino display bring-up on the P4 module has no ready preset.
- Key fit depends on a laser tolerance wider than the switch's; the coupon covers it.
- The second mate duplicate rule rests on an observed key shape, not a documented contract. (Since then, firstmate's `bin/fm-captain-hold.sh` header documents the `captain-hold-<task>-<n>` key.)
