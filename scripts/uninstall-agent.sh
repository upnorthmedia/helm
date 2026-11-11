#!/usr/bin/env bash
# Stop the Helm bridge's launchd user agent and remove its plist.
#
#   scripts/uninstall-agent.sh [--logs] [--no-launchctl]
#
#   --logs           also delete ~/Library/Logs/helm/
#   --no-launchctl   remove the plist only; do not unload the agent
#
# Safe to run when nothing is installed. Touches only
# ~/Library/LaunchAgents/local.helm.bridge.plist and, with --logs, ~/Library/Logs/helm/.
set -euo pipefail

label="local.helm.bridge"
plist="$HOME/Library/LaunchAgents/$label.plist"
log_dir="$HOME/Library/Logs/helm"
launchctl_bin="${LAUNCHCTL:-launchctl}"  # overridable so tests never touch the real launchd

remove_logs=0
use_launchctl=1

die() { echo "uninstall-agent: $*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --logs) remove_logs=1; shift ;;
    --no-launchctl) use_launchctl=0; shift ;;
    -h|--help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown option: $1 (see --help)" ;;
  esac
done

if [ "$use_launchctl" -eq 1 ]; then
  command -v "$launchctl_bin" >/dev/null 2>&1 || die "launchctl not found (macOS only); rerun with --no-launchctl to remove the plist only"
  domain="gui/$(id -u)"
  if "$launchctl_bin" print "$domain/$label" >/dev/null 2>&1; then
    "$launchctl_bin" bootout "$domain/$label" || die "could not unload $label"
    echo "uninstall-agent: unloaded $label"
  else
    echo "uninstall-agent: $label is not loaded"
  fi
fi

if [ -f "$plist" ]; then
  rm -f "$plist"
  echo "uninstall-agent: removed $plist"
else
  echo "uninstall-agent: no plist at $plist"
fi

if [ "$remove_logs" -eq 1 ] && [ -d "$log_dir" ]; then
  rm -rf "$log_dir"
  echo "uninstall-agent: removed $log_dir"
fi
