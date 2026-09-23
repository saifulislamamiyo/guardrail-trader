#!/bin/zsh
# Install / uninstall / show the macOS LaunchAgents that run guardrail-trader unattended.
#   scripts/launchd.sh install | docker-mode | render | uninstall | status
#   render       print the plists that would be installed (review before installing)
#   install      native mode: scheduler + keep-awake + dashboard
#   docker-mode  Docker runs scheduler + dashboard; only keep-awake stays on the host
#   keep-awake runs KEEP_AWAKE_START (default 18:00) local -> 16:00 New York on US trading nights
#   (scripts/keep_awake.py). Change it with e.g.: KEEP_AWAKE_START=19:30 scripts/launchd.sh docker-mode
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
LA="$HOME/Library/LaunchAgents"
AWAKE_START="${KEEP_AWAKE_START:-18:00}"
[[ "$AWAKE_START" =~ ^(1[2-9]|2[0-3]):[0-5][0-9]$ ]] || { echo "KEEP_AWAKE_START must be HH:MM between 12:00 and 23:59" >&2; exit 2; }
AWAKE_HOUR=$((10#${AWAKE_START%%:*})); AWAKE_MIN=$((10#${AWAKE_START##*:}))
[[ "${1:-}" == "render" ]] && LA="$(mktemp -d)"   # render: write to a temp dir, print, install nothing
DOMAIN="gui/$(id -u)"
LABELS=(com.guardrail-trader.scheduler com.guardrail-trader.awake com.guardrail-trader.dashboard com.guardrail-trader.gateway-watchdog)
mkdir -p "$LA" "$ROOT/logs"

plist() {  # label, keepalive(true/false), interval(0=none), args...
  local label=$1 keep=$2 interval=$3; shift 3
  local args=""; for a in "$@"; do args+="    <string>$a</string>"$'\n'; done
  local extra=""
  [[ $interval -gt 0 ]] && extra+="  <key>StartInterval</key><integer>$interval</integer>"$'\n'
  cat > "$LA/$label.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$label</string>
  <key>ProgramArguments</key>
  <array>
$args  </array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><$keep/>
$extra  <key>StandardOutPath</key><string>$ROOT/logs/$label.log</string>
  <key>StandardErrorPath</key><string>$ROOT/logs/$label.log</string>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string></dict>
</dict>
</plist>
EOF
}

awake_plist() {  # keep-awake only for tonight's trading runs (see scripts/keep_awake.py)
  cat > "$LA/com.guardrail-trader.awake.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.guardrail-trader.awake</string>
  <key>ProgramArguments</key>
  <array>
    <string>$ROOT/.venv/bin/python</string>
    <string>$ROOT/scripts/keep_awake.py</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>$AWAKE_HOUR</integer><key>Minute</key><integer>$AWAKE_MIN</integer></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><false/>
  <key>EnvironmentVariables</key>
  <dict><key>KEEP_AWAKE_START</key><string>$AWAKE_START</string></dict>
  <key>StandardOutPath</key><string>$ROOT/logs/com.guardrail-trader.awake.log</string>
  <key>StandardErrorPath</key><string>$ROOT/logs/com.guardrail-trader.awake.log</string>
</dict>
</plist>
EOF
}

case "${1:-status}" in
  install)
    plist com.guardrail-trader.scheduler false 900 "$PY" "$ROOT/scripts/scheduled_run.py"
    awake_plist
    plist com.guardrail-trader.dashboard true 0 "$PY" "$ROOT/scripts/dashboard.py" --no-browser
    for l in $LABELS; do
      launchctl bootout "$DOMAIN/$l" 2>/dev/null || true
      launchctl bootstrap "$DOMAIN" "$LA/$l.plist"
    done
    echo "installed: $LABELS"
    ;;
  docker-mode)
    # Docker runs the scheduler + dashboard; the host keeps keep-awake and the gateway watchdog
    # (Docker control stays on the host: the bot container never gets the Docker socket).
    # (containers can't stop the Mac sleeping).
    for l in com.guardrail-trader.scheduler com.guardrail-trader.dashboard; do
      launchctl bootout "$DOMAIN/$l" 2>/dev/null || true; rm -f "$LA/$l.plist"
    done
    awake_plist
    plist com.guardrail-trader.gateway-watchdog false 300 "$PY" "$ROOT/scripts/gateway_watchdog.py"
    for l in com.guardrail-trader.awake com.guardrail-trader.gateway-watchdog; do
      launchctl bootout "$DOMAIN/$l" 2>/dev/null || true
      launchctl bootstrap "$DOMAIN" "$LA/$l.plist"
    done
    echo "docker-mode: com.guardrail-trader.awake + com.guardrail-trader.gateway-watchdog loaded"
    ;;
  render)
    plist com.guardrail-trader.gateway-watchdog false 300 "$PY" "$ROOT/scripts/gateway_watchdog.py"
    plist com.guardrail-trader.scheduler false 900 "$PY" "$ROOT/scripts/scheduled_run.py"
    plist com.guardrail-trader.dashboard true 0 "$PY" "$ROOT/scripts/dashboard.py" --no-browser
    awake_plist
    for f in "$LA"/*.plist; do echo "===== $(basename "$f") ====="; cat "$f"; done
    rm -rf "$LA"
    ;;
  uninstall)
    for l in $LABELS; do launchctl bootout "$DOMAIN/$l" 2>/dev/null || true; rm -f "$LA/$l.plist"; done
    echo "uninstalled"
    ;;
  status)
    for l in $LABELS; do
      printf "%-34s " "$l"
      launchctl print "$DOMAIN/$l" 2>/dev/null | awk -F'= ' '/^\tstate =/{s=$2} /last exit code =/{e=$2} /^\tpid =/{p=$2} END{print "state=" s " pid=" p " last_exit=" e}' || echo "not loaded"
    done
    ;;
esac
