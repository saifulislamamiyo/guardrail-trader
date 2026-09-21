#!/bin/zsh
# Install / uninstall / show the macOS LaunchAgents that run guardrail-trader unattended.
#   scripts/launchd.sh install | docker-mode | uninstall | status
#   install      native mode: scheduler + keep-awake + dashboard
#   docker-mode  Docker runs scheduler + dashboard; only keep-awake stays on the host
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
LA="$HOME/Library/LaunchAgents"
DOMAIN="gui/$(id -u)"
LABELS=(com.guardrail-trader.scheduler com.guardrail-trader.awake com.guardrail-trader.dashboard)
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

case "${1:-status}" in
  install)
    plist com.guardrail-trader.scheduler false 900 "$PY" "$ROOT/scripts/scheduled_run.py"
    plist com.guardrail-trader.awake true 0 /usr/bin/caffeinate -i -s
    plist com.guardrail-trader.dashboard true 0 "$PY" "$ROOT/scripts/dashboard.py" --no-browser
    for l in $LABELS; do
      launchctl bootout "$DOMAIN/$l" 2>/dev/null || true
      launchctl bootstrap "$DOMAIN" "$LA/$l.plist"
    done
    echo "installed: $LABELS"
    ;;
  docker-mode)
    # Docker runs the scheduler + dashboard; keep only the host keep-awake job
    # (containers can't stop the Mac sleeping).
    for l in com.guardrail-trader.scheduler com.guardrail-trader.dashboard; do
      launchctl bootout "$DOMAIN/$l" 2>/dev/null || true; rm -f "$LA/$l.plist"
    done
    plist com.guardrail-trader.awake true 0 /usr/bin/caffeinate -i -s
    launchctl bootout "$DOMAIN/com.guardrail-trader.awake" 2>/dev/null || true
    launchctl bootstrap "$DOMAIN" "$LA/com.guardrail-trader.awake.plist"
    echo "docker-mode: only com.guardrail-trader.awake is loaded"
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
