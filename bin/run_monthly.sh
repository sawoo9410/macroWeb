#!/usr/bin/env bash
# launchd: com.sawoo.macroweb.monthly (매월 1일 08:00). Track C 학습 루프 (PLAN §12).
. "$(dirname "$0")/_common.sh"
macroweb_lock monthly
MONTH="$(date -v-1d +%Y-%m)"   # 1일 실행 → 지난달
caffeinate -i uv run macroweb monthly --month "$MONTH" || macroweb_fail monthly "bin/run_monthly.sh"
