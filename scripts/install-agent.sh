#!/usr/bin/env bash
# Install the Helm bridge as a launchd user agent, so it starts at login and
# restarts after a crash.
#
#   scripts/install-agent.sh --port PATH [--home PATH] [--live] [--python PATH] [--no-launchctl]
#
#   --port PATH      the deck's device path: the real board (/dev/cu.usbmodemNNNN)
#                    or a simulator pty (/dev/ttysNNN, printed by `python3 -m sim`)
#   --home PATH      primary firstmate home (default: $FM_HOME)
#   --live           send real inbox notes and focus real herdr panes; without it
#                    the agent always runs --dry-run, even if it was live before
#   --python PATH    Python 3.11+ to run the bridge (default: python3 on PATH now)
#   --no-launchctl   write the plist only; do not load or reload the agent
#
# Writes only ~/Library/LaunchAgents/local.helm.bridge.plist and creates
# ~/Library/Logs/helm/. Running it again with the same options changes nothing;
# with new options it rewrites the plist and reloads the agent.
set -euo pipefail

label="local.helm.bridge"
repo="$(cd "$(dirname "$0")/.." && pwd)"
template="$repo/scripts/launchd/$label.plist.template"
agents_dir="$HOME/Library/LaunchAgents"
plist="$agents_dir/$label.plist"
log_dir="$HOME/Library/Logs/helm"
launchctl_bin="${LAUNCHCTL:-launchctl}"  # overridable so tests never touch the real launchd

port=""
fm_home=""
mode="--dry-run"
python=""
use_launchctl=1

die() { echo "install-agent: $*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --port) [ $# -ge 2 ] || die "--port needs a path"; port="$2"; shift 2 ;;
    --home) [ $# -ge 2 ] || die "--home needs a path"; fm_home="$2"; shift 2 ;;
    --python) [ $# -ge 2 ] || die "--python needs a path"; python="$2"; shift 2 ;;
    --live) mode="--live"; shift ;;
    --dry-run) mode="--dry-run"; shift ;;
    --no-launchctl) use_launchctl=0; shift ;;
    -h|--help) sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown option: $1 (see --help)" ;;
  esac
done

[ -n "$port" ] || die "--port is required: the board's /dev/cu.usbmodemNNNN or the simulator's /dev/ttysNNN"
[ -f "$template" ] || die "missing template: $template"

if [ -z "$python" ]; then
  python="$(command -v python3 || true)"
  [ -n "$python" ] || die "no python3 on PATH; pass --python PATH"
fi
case "$python" in
  /*) ;;
  *) python="$(command -v "$python" || true)"; [ -n "$python" ] || die "--python must name an executable" ;;
esac
"$python" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null \
  || die "$python is not Python 3.11 or newer; pass --python PATH"
(cd "$repo" && "$python" -c 'import helm.bridge') || die "cannot import helm.bridge from $repo with $python"

if [ -z "$fm_home" ]; then
  fm_home="${FM_HOME:-}"
  [ -n "$fm_home" ] || die "no firstmate home: pass --home or set FM_HOME"
fi
# Match a literal tilde the shell left unexpanded (a quoted --home "~/x").
# shellcheck disable=SC2088
case "$fm_home" in
  "~"|"~/"*) fm_home="$HOME${fm_home#\~}" ;;
esac
[ -d "$fm_home/state" ] || die "not a firstmate home (no state/ directory): $fm_home"

[ -e "$port" ] || echo "install-agent: note: $port does not exist yet; the agent retries every 10 s until it does" >&2

# launchd starts agents with a bare PATH. The bridge runs herdr, fm-inbox.sh,
# and quota-axi (a node script, so node too), so put their usual homes first.
agent_path="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
for tool in herdr quota-axi node; do
  tool_bin="$(command -v "$tool" || true)"
  [ -n "$tool_bin" ] || continue
  tool_dir="$(dirname "$tool_bin")"
  case ":$agent_path:" in
    *":$tool_dir:"*) ;;
    *) agent_path="$tool_dir:$agent_path" ;;
  esac
done

mkdir -p "$agents_dir" "$log_dir"
tmp="$(mktemp "$agents_dir/.$label.XXXXXX")"
trap 'rm -f "$tmp"' EXIT

HELM_LABEL="$label" HELM_PYTHON="$python" HELM_MODE="$mode" HELM_PORT="$port" \
HELM_FIRSTMATE_HOME="$fm_home" HELM_CHECKOUT="$repo" HELM_PATH="$agent_path" HELM_LOG_DIR="$log_dir" \
  "$python" - "$template" "$tmp" <<'PY'
import os
import re
import sys
from xml.sax.saxutils import escape

names = ["LABEL", "PYTHON", "MODE", "PORT", "FIRSTMATE_HOME", "CHECKOUT", "PATH", "LOG_DIR"]
with open(sys.argv[1], encoding="utf-8") as f:
    text = f.read()
for name in names:
    text = text.replace("@%s@" % name, escape(os.environ["HELM_" + name]))
body = text.split("-->", 1)[1]
left = re.findall(r"@[A-Z_]+@", body)
if left:
    sys.exit("install-agent: unfilled placeholders: %s" % " ".join(left))
with open(sys.argv[2], "w", encoding="utf-8") as f:
    f.write(text)
PY

if command -v plutil >/dev/null 2>&1; then
  plutil -lint -s "$tmp" || die "the rendered plist failed plutil -lint"
fi

if [ -f "$plist" ] && cmp -s "$tmp" "$plist"; then
  echo "install-agent: $plist is already up to date ($mode, port $port)"
  changed=0
else
  chmod 644 "$tmp"
  mv "$tmp" "$plist"
  echo "install-agent: wrote $plist ($mode, port $port)"
  changed=1
fi

if [ "$mode" = "--live" ]; then
  echo "install-agent: LIVE: deck keys will send real inbox notes and focus real herdr panes" >&2
fi

if [ "$use_launchctl" -eq 0 ]; then
  echo "install-agent: --no-launchctl: not loading; to load it: launchctl bootstrap gui/$(id -u) $plist"
  exit 0
fi

command -v "$launchctl_bin" >/dev/null 2>&1 || die "launchctl not found (macOS only); rerun with --no-launchctl to write the plist only"
domain="gui/$(id -u)"
if "$launchctl_bin" print "$domain/$label" >/dev/null 2>&1; then
  if [ "$changed" -eq 0 ]; then
    echo "install-agent: agent already loaded; logs: $log_dir/bridge.log"
    exit 0
  fi
  "$launchctl_bin" bootout "$domain/$label" || die "could not unload the old agent"
fi
"$launchctl_bin" bootstrap "$domain" "$plist" || die "launchctl bootstrap failed; see $log_dir/bridge.log"
echo "install-agent: loaded $label; logs: $log_dir/bridge.log"
