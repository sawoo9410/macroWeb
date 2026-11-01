#!/usr/bin/env bash
# launchd: com.sawoo.macroweb.weekly (일 17:30 KST). 품질 검토 Step 0 → claude -p 편집국 (ADR-0002). ≤ 2h.
. "$(dirname "$0")/_common.sh"
macroweb_lock weekly
WEEK="$(date +%G-W%V)"
# 러너(src/macroweb/synth/run_weekly.py, Phase 4)가 자식 claude 프로세스 환경에서 ANTHROPIC_API_KEY 를 제거한다.
caffeinate -i uv run macroweb weekly run --week "$WEEK" || macroweb_fail weekly "bin/run_weekly.sh"
uv run macroweb notify --level info --job weekly -m "거미줄 리포트 $WEEK 발행" >/dev/null || true
