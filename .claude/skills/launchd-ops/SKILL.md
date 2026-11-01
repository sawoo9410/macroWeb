---
name: launchd-ops
description: launchd 잡(collect 30분·daily 07:00·weekly 일 17:30·monthly 1일 08:00) 설치·dry-run·상태·로그·복구 절차. "launchd 설치", "잡 상태", "로그 봐줘", "/launchd-ops status".
argument-hint: "[install|dryrun|status|logs|uninstall]"
disable-model-invocation: true
---
# 절차 (PLAN §4.4, 부록 H, docs/RUNBOOK.md)
- **dryrun** (Phase 0 DoD): `make launchd-dryrun` — `plutil -lint` → 임시 bootstrap → `launchctl print gui/$(id -u)/<label>` → 즉시 bootout. 잡을 남기지 않는다.
- **install** (Phase 1 부터): `make launchd-install` = `cp launchd/*.plist ~/Library/LaunchAgents/ && launchctl bootstrap gui/$(id -u) <plist>`. 사전 조건: `private/.env` 존재, `make doctor` PASS, `sudo pmset repeat wakeorpoweron MTWRFSU 06:55:00`(사용자가 직접 — sudo).
- **status**: `launchctl print gui/$(id -u)/com.sawoo.macroweb.<job>` 의 `state`·`last exit code`; `uv run macroweb status`(최근 run, 24h 이상 run 없으면 누락 경보).
- **logs**: `logs/<job>.out.log`, `logs/<job>.err.log`, `logs/hooks.jsonl`. 실패 알림에는 첫 에러 3줄 + 재실행 명령어가 들어간다.
- **복구**: 모든 단계는 idempotent — `bin/run_<job>.sh` 를 그대로 다시 실행. 잠든 사이 놓친 캘린더 잡은 깨어난 직후 1회 자동 실행된다(그래서 idempotent 필수). 락은 `data/.lock-<job>/`(mkdir 락, macOS 엔 flock 이 없다); 고아 락은 pid 가 죽었으면 래퍼가 치운다.
- **uninstall**: `make launchd-uninstall` (bootout + plist 삭제).
- 주간 잡 인증: 구독 OAuth(Keychain `Claude Code-credentials`). `ANTHROPIC_API_KEY` 는 claude 프로세스 환경에서 제거된다(ADR-0002). 토큰 만료 대비는 Phase 4 러너가 `claude --print -p ping` 으로 선제 갱신(moat-journal 패턴).
launchctl bootstrap/bootout·sudo·pmset 은 사용자 확인 후 실행한다(훅이 ask 로 막는다).
