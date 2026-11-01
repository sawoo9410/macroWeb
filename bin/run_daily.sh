#!/usr/bin/env bash
# launchd: com.sawoo.macroweb.daily (07:00 KST). 배치 회수 → L4·L5 → 다이제스트, 07:30 전 완료 (PLAN §0.3).
. "$(dirname "$0")/_common.sh"
macroweb_lock daily
TODAY="$(date +%F)"
caffeinate -i bash -c "
  uv run macroweb extract --date '$TODAY' &&
  uv run macroweb verify  --date '$TODAY' &&
  uv run macroweb graph update &&
  uv run macroweb digest  --date '$TODAY'
" || macroweb_fail daily "bin/run_daily.sh"
uv run macroweb notify --level info --job daily -m "일일 다이제스트 $TODAY 완료" >/dev/null || true
