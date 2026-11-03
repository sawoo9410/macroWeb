# RUNBOOK — 운영 절차 (Phase 7 에 완성, Phase 0 골격)

## 1. 설치
```bash
brew install uv && uv python install 3.12
git clone https://github.com/sawoo9410/macroWeb.git && cd macroWeb
uv sync
cp private/env.example private/.env     # 값 입력 — 이 파일은 읽지도 커밋하지도 않는다
make doctor                             # 전부 PASS/WARN 이어야 한다 (FAIL = exit 1)
```
## 2. 매일 확인하는 것
- `uv run macroweb status` — 최근 run, 24시간 이상 run 이 없으면 잡 누락.
- `logs/<job>.err.log` 첫 3줄 (실패 알림에 그대로 들어온다).
## 3. launchd
- Phase 0: `make launchd-dryrun` (문법 + 임시 로드 + print + 언로드).
- Phase 1+: `make launchd-install` · 상태 `launchctl print gui/$(id -u)/com.sawoo.macroweb.weekly` · 제거 `make launchd-uninstall`.
- 맥 깨우기(sudo, 사용자 직접): `sudo pmset repeat wakeorpoweron MTWRFSU 06:55:00`; 일요일 17:25 는 `pmset schedule` 로 추가.
- 잠든 사이 놓친 캘린더 잡은 깨어나면 1회 실행된다 → 모든 단계 idempotent.
## 3b. 수집 (Phase 1)
- 수동 틱: `uv run macroweb collect` (기한 도래 소스만) · 전부 강제: `--force` · 한 소스: `--source yna_economy --force`.
- 결과: `digests/collect-stats-<KST날짜>.md` (소스별 fetch/new/err/304/interval/health), raw 는 `data/raw/YYYY/MM/DD/`, DB `data/db/macroweb.sqlite` (`article`·`story`·`market`·`fetch_log`).
- 소스가 `degraded`(3회 연속 실패)면 `uv run macroweb source probe <id>` 로 URL 을 보고 `config/sources.yaml` 을 고친 뒤 `--force` 로 재시도. 백오프(최대 1일)는 성공 1회로 풀린다.
- 파서가 바뀌면 `uv run macroweb source golden` 으로 골든 차이를 확인하고 의도된 변화면 `--write --force`.
- 키가 필요한 소스(FRED·ECOS·DART)는 `private/.env` 에 키가 없으면 `skip … not set` 으로 건너뛴다(오류 아님).
- 시장 데이터 확인: `uv run macroweb market latest` (key 별 최신값·보유 일수) · `uv run macroweb market get UST:10Y --limit 10`. 키 없이 들어오는 것은 `UST:*`(재무부)·`ECB:*`·`NAVER:*`·`KRAKEN:XBTUSD` (ADR-0005). `NAVER:KOSPI` 는 장 마감 후 틱에서만 1점 쌓이고, Kraken 은 확정 캔들만 들어온다.

## 3c. 추출 (Phase 2, ADR-0007 — claude -p 구독 경로)
- 30분 틱(`bin/run_collect.sh` → `macroweb tick`)이 수집 뒤 새 Story 를 `calls_per_tick`(extract.yaml) 건까지 추출한다. 하루 상한 `max_calls_per_day`. 끄려면 `headless.tick_extract: false`.
- 수동: `uv run macroweb extract --dry-run` (무엇이 뽑히는지) · `uv run macroweb extract --limit 3` · 특정 Story 재추출 `--story st-… --force` (claim id 는 내용 주소라 중복 없음).
- 확인: `uv run macroweb extractions` (최근 ledger) · `uv run macroweb claim search 금리` · `uv run macroweb claim get <id>`.
- 실패 원문은 `logs/extract_failures/<story>_<tier>_<ts>.json` (`subtype`·usage·stderr). `harness:` 접두 오류(API 끊김 등)는 30분 뒤 자동 재시도(최대 2회), `schema:` 는 승급 사다리 끝에서 종결 → `--force` 로만 재시도.
- 구독 한도: `logs/claude_limit.stamp` 가 있으면 1시간 동안 추출을 건너뛴다(수집은 계속). 사용자 세션에서 `/usage` 로 창을 확인.
- 선별이 이상하면(연예·스포츠 기사 등) `config/themes.yaml` 키워드와 `extract.yaml selection.min_theme_score` 를 보고, 소스 피드가 섹션 전체면 `sources.yaml` 의 URL 을 섹션 피드로 바꾼다.

## 4. 재실행(복구)
모든 단계는 같은 인자로 다시 돌려도 결과가 같다.
```bash
bin/run_collect.sh                 # = uv run macroweb tick --date 2026-11-05 (수집 + 추출 ≤ calls_per_tick)
bin/run_daily.sh                   # uv run macroweb extract --date … ; verify ; graph update ; digest
bin/run_weekly.sh                  # uv run macroweb weekly run --week 2026-W45  (ADR-0002: claude -p)
bin/run_monthly.sh
```
락 디렉터리 `data/.lock-<job>/` 가 남아 있고 pid 가 죽었으면 래퍼가 자동으로 치운다.
## 5. 주간 실행기 인증 (ADR-0002)
- 구독 OAuth(Keychain `Claude Code-credentials`). 자식 환경에서 `ANTHROPIC_API_KEY` 제거.
- 토큰 만료 증상: `logs/weekly.err.log` 에 401/`authentication_failed` → `claude --print -p ping` 한 번(키체인 refreshToken 으로 갱신) 후 재실행. Phase 4 러너가 자동화.
- 구독 한도 소진: `rate_limit` → 알림. `MACROWEB_WEEKLY_AUTH=api bin/run_weekly.sh` 로 수동 API 재실행 가능(비용 발생, Q2).
## 6. 비용
`make cost`(추정) · `uv run macroweb status`(run.cost_usd 실측) · 80% 도달 시 추출 80→50, 100% 시 주간만(`config/models.yaml budget.degrade`).
## 7. 비밀값 사고
키가 출력·커밋됐으면 숨기지 말고 즉시 사용자에게 알리고(어떤 키, 어디에 기록), 해당 키를 교체한다. `logs/hooks.jsonl` 에 차단 기록이 남는다.
