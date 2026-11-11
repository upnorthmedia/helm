# helm

A physical interface device for herdr and firstmate: shows worker state, decisions waiting, and ready PRs, with buttons to approve and steer.

## Build the hardware

These guides are for v2: the 5 inch Waveshare LCD-5 in the option C sheet-metal case, the build the firmware on main targets. v1, the 4 inch board in the first case, is at commit `b2f7670`.

- [Bill of materials](docs/build/bom.md) ([CSV](docs/build/bom.csv)): every part for v2 with vendor, price, and stock, and totals by phase.
- [Wiring](docs/build/wiring.md): each part to the LCD-5's 40-pin header as the firmware's defaults name them, and what to check on the real board.
- [Assembly](docs/build/assembly.md): phase 1 on the breadboard (flashing and the bridge included), phase 2 the printed parts and bench measurements, phase 3 the SendCutSend order and the logo engraving.

## Controls

- **Knob:** turn to move through the project views and items; press to open a list or an item's full text; long press to mute the chime.
- **YES, LATER, HOLD:** hold for 1 s on the selected item to send firstmate one note: YES (merge it, or go with your single recommendation), LATER (defer until tomorrow), HOLD (do not proceed, raise it in chat). Firstmate acts through its own checks.
- **SHOW ME:** tap to bring the item's herdr pane into focus and, when the item has one, open its live Lavish review board, its report (rendered as a styled page in Lavish), or its PR in the browser. Details in [the bridge README](helm/bridge/README.md#what-it-runs).

Every key goes dark while the Mac is locked; YES, LATER, and HOLD also go dark while firstmate is away.

## Run it

Python 3.11 or newer, standard library only (the simulator also needs Tk).

```sh
# The deck simulator and the bridge (dry run), connected through a pty
scripts/run-sim.sh

# The bridge alone: one Model as JSON from the firstmate home, then exit
FM_HOME=~/path/to/firstmate python3 -m helm.bridge --once

# Tests
python3 -m unittest discover -s tests -t .

# The C device core (firmware/core): unit tests and cross-tests against helm/wire (needs cmake)
scripts/test-firmware.sh

# The deck firmware (firmware/idf): build for the Waveshare board (needs ESP-IDF v5.5.6, see firmware/idf/README.md)
idf.py -C firmware/idf build

# The case (case/): rebuild the DXF, STEP, STL, and renders (needs CadQuery, see case/README.md)
case/.venv/bin/python case/build.py
```

### Start the bridge at login

`scripts/install-agent.sh` installs a launchd user agent (`local.helm.bridge`) that runs `python3 -m helm.bridge --dry-run --port <device>` from this checkout, restarts it after a crash or a nonzero exit (every 10 s while the device is missing), and logs to `~/Library/Logs/helm/bridge.log`. Install from a checkout that stays put, since the agent runs the code in place.

```sh
scripts/install-agent.sh --port /dev/cu.usbmodem1101          # the real board (dry run)
scripts/install-agent.sh --port /dev/cu.usbmodem1101 --live   # send real notes, focus real panes, open boards and reports
scripts/uninstall-agent.sh                                    # stop it and remove the plist (--logs also deletes the logs)
```

The device path is the `--port` value. For the real board it is the USB serial device (`ls /dev/cu.usbmodem*`). For the simulator, run `python3 -m sim`, which prints `bridge port: /dev/ttysNNN`, and install with that path; the pty is new each time the simulator starts, so reinstall with the new path after restarting it. Do not run `scripts/run-sim.sh` while the agent is loaded: it starts its own bridge.

Dry run is always the default: rerunning the installer without `--live` switches a live agent back to dry run. Rerunning with the same options changes nothing; with new options it rewrites the plist and reloads the agent. Other options: `--home PATH` (firstmate home; default `$FM_HOME`), `--python PATH` (default: `python3` on your PATH at install time), `--no-launchctl` (write the plist without loading it). The installer touches only `~/Library/LaunchAgents/local.helm.bridge.plist` and `~/Library/Logs/helm/`. launchd does not rotate the log.

## License

Software is licensed under the [Apache License 2.0](LICENSE). The case design (`case/`) and build guides (`docs/build/`) are licensed under [CERN-OHL-W-2.0](LICENSES/CERN-OHL-W-2.0.txt), and other documentation and images under [CC BY 4.0](LICENSES/CC-BY-4.0.txt). The Helm logo is not under an open license: [all rights reserved](LICENSES/LicenseRef-Helm-Logo.txt). Images and renders here that show the logo are licensed for their content, but that grants no right to use the logo itself. [`REUSE.toml`](REUSE.toml) maps every path to its license, and [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) lists third-party material.
