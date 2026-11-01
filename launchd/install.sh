#!/usr/bin/env bash
# Phase 1+: 실제 설치. 사전 조건: private/.env, make doctor PASS, pmset 깨우기(사용자 sudo).
set -euo pipefail
cd "$(dirname "$0")/.."
UID_=$(id -u); LA="${HOME:?}/Library/LaunchAgents"; mkdir -p "$LA" logs
for p in launchd/com.sawoo.macroweb.*.plist; do
  label=$(basename "$p" .plist)
  plutil -lint "$p"
  launchctl bootout "gui/$UID_/$label" >/dev/null 2>&1 || true
  cp "$p" "$LA/$label.plist"
  launchctl bootstrap "gui/$UID_" "$LA/$label.plist"
  launchctl print "gui/$UID_/$label" | grep -E "^\s*state =" || true
  echo "installed $label"
done
