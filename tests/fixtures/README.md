# Test fixtures

Two fixture homes, `primary/` and `mate1/` (a second mate), plus `variants/`.

The `home-summary.json` files are not written by hand.
Each is the output of firstmate's own projections, run over fixed inputs:
`secondmate_home_summary_json` in `bin/fm-fleet-snapshot.sh` (the document `bin/fm-home-summary-refresh.sh` publishes as `state/home-summary.json`), with its `contributions` block from `projected` and `summary` in `bin/fm-contributions.jq`.
They were generated with [firstmate](https://github.com/kunchenguid/firstmate) at commit `1d43f9cb`, so every row is one the real producer can emit.
In particular, `active_children` lists only working tasks; blocked and failed tasks appear in `endpoints[]`, as firstmate publishes them.

The inputs describe this primary home:

| Task | State | Why it is here |
| --- | --- | --- |
| `alpha-fix` | parked, open decision `merge-alpha-12` | A merge ask whose captain row is fresh and green, though `pr-health.json` once reported it failing at the same commit |
| `beta-port` | blocked | A stuck worker, with its `holds[]` row (`source: "child-state"`) |
| `delta-docs` | working | A PR ready for the captain (a captain row with no hold); `pr-health.json` reported it failing only at an earlier commit |
| `omega-ci` | parked, open decision `merge-omega-7` | A merge ask on a red PR: no captain row, failing in `pr-health.json` |
| `theta-cut` | parked, live captain hold | A captain row with `hold` set: it belongs to the hold's decision, not a ready PR |
| `widget-pricing` | queued, live captain hold | A plain captain decision |
| `zeta-later` | queued | Queued work |
| `mate1` | second mate, working | Relays its `gamma-choice` hold as `captain-hold-gamma-choice-1` |

`variants/primary-failed-home-summary.json` adds `eta-sync`, a failed worker.
The producer marks that summary invalid (`terminal_in_flight`), as it does for any in-flight task in a terminal state.

Two values are filled in when a test copies a home (`tests/helpers.py`, `date_summary`): the `TODAY` date on the landed row, and each captain row's `checked_at`, set to now so the row counts as freshly checked.
`pr-health.json`, the `.meta` files, and the `.status` files are hand-written in the shapes `bin/fm-pr-health.sh`, `bin/fm-spawn.sh`, and the worker status protocol use.
