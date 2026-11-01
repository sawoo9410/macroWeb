#!/usr/bin/env bash
# 공통 프롤로그: 절대경로·PATH·.env 로드·mkdir 락(macOS 에 flock 없음)·실패 알림. 각 run_*.sh 가 source 한다.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export HOME="${HOME:-/Users/seosang-u}"
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:/usr/bin:/bin"
export MACROWEB_ENV="${MACROWEB_ENV:-prod}"
mkdir -p logs data
if [ -f private/.env ]; then set -a; . private/.env; set +a; fi   # 값은 어디에도 출력하지 않는다

macroweb_unlock() { rm -f "${LOCKDIR:?}/pid"; rmdir "${LOCKDIR:?}" 2>/dev/null || true; }

macroweb_lock() {
  local job="$1"; LOCKDIR="$ROOT/data/.lock-$job"
  if ! mkdir "$LOCKDIR" 2>/dev/null; then
    local pid; pid="$(cat "$LOCKDIR/pid" 2>/dev/null || echo 0)"
    if [ "$pid" != "0" ] && kill -0 "$pid" 2>/dev/null; then echo "[$job] already running (pid $pid)"; exit 0; fi
    echo "[$job] stale lock (pid $pid) — removing"; macroweb_unlock; mkdir "$LOCKDIR"
  fi
  echo $$ > "$LOCKDIR/pid"
  trap macroweb_unlock EXIT
}

macroweb_fail() {  # job rerun-command — 알림은 잡당 6시간에 1번 (30분 틱이 연속 실패해도 알림 폭주 방지)
  local job="$1" rerun="$2" stamp="logs/$job.last_notify" now
  now=$(date +%s)
  if [ ! -f "$stamp" ] || [ $(( now - $(stat -f %m "$stamp") )) -gt 21600 ]; then
    uv run macroweb notify --level error --job "$job" --tail 3 --rerun "$rerun" || true
    touch "$stamp"
  else
    echo "[$job] failed (notification suppressed; last alert <6h ago)" >&2
  fi
  exit 1
}
