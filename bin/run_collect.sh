#!/usr/bin/env bash
# launchd: com.sawoo.macroweb.collect (StartCalendarInterval :00/:30). 30분 틱 = 기한 도래 소스 수집 (PLAN §4.4)
# → 추출 ≤ calls_per_tick (ADR-0007/0008, extract.yaml tick_extract 로 끌 수 있음). 수집 실패만 알림 대상.
. "$(dirname "$0")/_common.sh"
macroweb_lock collect
TODAY="$(date +%F)"
uv run macroweb tick --date "$TODAY" || macroweb_fail collect "bin/run_collect.sh"
