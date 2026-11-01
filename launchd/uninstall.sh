#!/usr/bin/env bash
set -uo pipefail
UID_=$(id -u); LA="${HOME:?}/Library/LaunchAgents"
for label in com.sawoo.macroweb.collect com.sawoo.macroweb.daily com.sawoo.macroweb.weekly com.sawoo.macroweb.monthly; do
  launchctl bootout "gui/$UID_/$label" >/dev/null 2>&1 && echo "booted out $label" || echo "$label not loaded"
  rm -f "${LA:?}/${label:?}.plist"
done
