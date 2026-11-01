#!/usr/bin/env bash
# Phase 0 DoD: plist 문법 검사 → 임시 bootstrap → launchctl print 로 로드 확인 → 즉시 bootout. 잡을 남기지 않는다.
set -uo pipefail
cd "$(dirname "$0")/.."
UID_=$(id -u); LA="${HOME:?}/Library/LaunchAgents"; mkdir -p "$LA" logs
rc=0
for p in launchd/com.sawoo.macroweb.*.plist; do
  label=$(basename "$p" .plist)
  echo "== $label"
  plutil -lint "$p" || { rc=1; continue; }
  cleanup() { launchctl bootout "gui/$UID_/${label:?}" >/dev/null 2>&1 || true; rm -f "${LA:?}/${label:?}.plist"; }
  trap cleanup EXIT
  cp "$p" "$LA/$label.plist"
  if launchctl bootstrap "gui/$UID_" "$LA/$label.plist"; then
    launchctl print "gui/$UID_/$label" | grep -E "^\s*(state|path|program|run interval|runs) =|StartCalendarInterval|Weekday|Hour|Minute|Day =" | head -8
  else
    echo "bootstrap failed for $label"; rc=1
  fi
  cleanup; trap - EXIT
  if launchctl print "gui/$UID_/$label" >/dev/null 2>&1; then echo "ERROR: $label still loaded"; rc=1; else echo "unloaded ok"; fi
done
exit $rc
