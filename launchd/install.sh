#!/usr/bin/env bash
# 설치. 인자 없이 = 4개 전부, 인자로 잡 이름(collect daily weekly monthly)을 주면 그것만.
# Phase 1 은 `install.sh collect` 만 (daily 는 extract/verify/digest 가 구현되는 Phase 2 에 설치).
# 사전 조건: make doctor PASS, (키가 필요한 소스는) private/.env, pmset 깨우기(사용자 sudo, QUESTIONS Q6).
set -euo pipefail
cd "$(dirname "$0")/.."
UID_=$(id -u); LA="${HOME:?}/Library/LaunchAgents"; mkdir -p "$LA" logs
jobs=("$@"); [ ${#jobs[@]} -eq 0 ] && jobs=(collect daily weekly monthly)
for job in "${jobs[@]}"; do
  label="com.sawoo.macroweb.$job"; p="launchd/$label.plist"
  [ -f "$p" ] || { echo "no plist for $job"; exit 2; }
  plutil -lint "$p"
  launchctl bootout "gui/$UID_/$label" >/dev/null 2>&1 || true
  cp "$p" "$LA/$label.plist"
  launchctl bootstrap "gui/$UID_" "$LA/$label.plist"
  launchctl print "gui/$UID_/$label" | grep -E "^\s*(state|run interval) =" || true
  echo "installed $label"
done
