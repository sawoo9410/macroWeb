#!/usr/bin/env bash
# launchd: com.sawoo.macroweb.collect (StartInterval 1800). 스케줄러가 기한 도래 소스만 수집 (PLAN §4.4).
. "$(dirname "$0")/_common.sh"
macroweb_lock collect
TODAY="$(date +%F)"
uv run macroweb collect --date "$TODAY" || macroweb_fail collect "bin/run_collect.sh"
