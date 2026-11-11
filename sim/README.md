# Helm deck simulator

A window on the Mac that looks and behaves like the Helm deck: the v2 deck's 1280 x 720 screen (the Waveshare ESP32-P4-WIFI6-Touch-LCD-5 turned landscape), and below it, as on the case's face, four keys, the light bar, and a push knob. It speaks the same wire as the hardware will, so the bridge cannot tell it from a real deck.

The window is 1400 x 940 points: it fits a 16 inch or 15 inch MacBook screen at the default scaling, but on a 14 inch one (982 points tall) the bottom row can sit under the Dock.

## Run it

```sh
scripts/run-sim.sh                 # simulator + python -m helm.bridge --dry-run, over a pty
scripts/run-sim.sh --home PATH     # extra arguments go to the bridge
scripts/run-sim.sh --fake-bridge   # simulator + a fixture bridge, over the real wire
scripts/run-sim.sh --fake          # simulator alone with fixture data
```

Or run the pieces yourself:

```sh
python -m sim                      # makes a pty pair and prints the bridge's port path
python -m helm.bridge --port /dev/ttysNNN
python -m sim --port /dev/cu.usbmodemNNN   # any existing serial path
python -m sim --fake
```

Needs Python 3.11+ with Tk (Homebrew's python 3.14 has Tk 9.0). No other packages; `pyserial` is used for a real serial port when installed, and a plain termios file descriptor otherwise.

## Controls

| Deck | Keyboard | Mouse |
| --- | --- | --- |
| YES / LATER / HOLD (hold 1 s) | Y / L / H (or 1 / 2 / 3), held | press and hold the key |
| SHOW ME (tap) | S (or 4) | click |
| Knob turn (Home: project view; list: move) | arrow keys | scroll wheel over the window |
| Knob press | Enter or Space | click the knob |
| Knob long press (mute) | M | hold the knob 0.6 s |

A key is lit only when its action applies to the selected item. Any control counts as a touch and marks new items seen.

When items name projects, the knob on Home turns through the views: "all" first, then each project in order, and the status strip shows `view: <name>`. A press opens that view's list; turning up past the list's first row goes back to Home. Without projects, a turn on Home opens the list as before. While firstmate is away, the status strip says `firstmate away: keys locked`, YES, LATER, and HOLD stay dark, chimes are off, and SHOW ME still works. In quiet mode the strip says `firstmate quiet` and every key works; the bridge sends no chime. While the Mac is locked, it says `Mac locked: keys locked` and every key stays dark, SHOW ME too; chimes still play.

## Screens

- **Home**: on the left, how many new items, the Claude usage line (`Claude left  5h 62% for 1h  week 40% for 3d`; `?` or `Claude usage unknown` when the bridge has no fresh reading), the context line (`Context  widget-cache 91% used  2 near limit`, amber while any herdr agent is at 80 % or more; `Agent context unknown` when no agent reports one), counts, and the herdr and queued lines; on the right, "Needs you" with up to five of the view's items as compact rows, the selection outlined (the list's rows, smaller; never the full text).
- **List**: one row per item in the view, six at a time: color (tinted by project, as on the light bar), short id, kind and project, age, NEW.
- **Detail**: the full text, only after a knob press on a row (D18).
- **Confirm**: while a key is held, with the 1 s fill bar. Releasing early sends nothing but the key up.
- **Result**: the bridge's answer: queued, replied, or failed. While queued, it reads **Seen** once firstmate has read the note, and beside it how long ago the note went (`sent 40s ago, firstmate has read it`); unread past the bridge's limit, the label turns amber and says `firstmate has not picked this up: sent 4m ago`.

On the list, Home's column, and Detail, an item whose answer is still waiting on firstmate's reply says which (`YES sent`, `LATER sent`, `HOLD sent`) in that key's color.

The light bar shows one light per unseen item in its kind's color, tinted by its project, and pulses while anything is new. A tint only mixes white into the kind's color (none without a project, else 18, 36, or 54 % by a stable hash of the name), so a tinted light is paler, never another kind's color. When calm it is the usage gauge (what is left of the tighter Claude window, out of 8 lights rounded up, over a dim track; no light lit while usage is unknown, so it never reads full), with the last light amber while a herdr agent is near its context limit; all amber when the link is unknown (no model for 10 s, or firstmate not listening), and sweeps green when `landed_today` goes up. One chime plays for each model that carries `chime`, unless muted.

## Files

- `state.py`: the deck's local state (screen, selection, hold, mute, link timeout). No window; tested directly.
- `render.py`: state to a list of shapes for the whole window.
- `app.py`: tkinter painting those shapes, input, the link thread, the chime.
- `snapshot.py`: paints the same shapes to PNG with Pillow (`python -m sim.snapshot DIR`), for docs. Pillow is only needed for this.
- `fake_bridge.py`, `fixtures.py`: invented data for `--fake` and tests.

The screenshots in `docs/sim/` come from `snapshot.py` with fixture data (`python -m sim.snapshot docs/sim`). The firmware draws the same layout (`firmware/idf/main/ui.c`); `firmware/idf/README.md` lists where the two differ (fonts, the on-screen keys). Hello reports `screen-1280x720` among its capabilities, as the firmware does.

## The wire

`helm/wire/` carries the Harness Pro binary frame (`A5 48 | ver | type | len | payload | crc16`, CRC-16/CCITT-FALSE), ported from autonomous-ai/openharness at commit a441303 and checked against that repository's shared vectors (`tests/vectors/`). Every message is a type 0x01 frame holding compact JSON with a `t` field. To read a capture:

```sh
python -m helm.wire.decode capture.bin
python -m helm.wire.decode --hex 'a5 48 01 01 ...'
```
