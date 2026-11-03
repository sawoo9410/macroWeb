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

## 3d. 검증 v1 (Phase 2, ADR-0009 — 결정론 신호, 모델 호출 없음)
- 틱이 추출 뒤 `verify` 를 돌린다(최근 72시간에 추출·갱신된 claim + 라벨 없는 claim). 수동: `uv run macroweb verify` · 전부 재라벨 `--all`(idempotent) · 한 Story `--story st-…`.
- 라벨 근거는 `uv run macroweb claim get <id>` 의 `signals_json.verify` (prior·독립 출처 수·1차 문서·수치 비교 키/값/오차·재탕 근거·언어 특징·결정적 신호 문장).
- 수치 검증(신호 4)은 `config/verify.yaml numeric_keys` 의 패턴 → `market` 키로만 비교한다. 새 지표가 들어오면 거기에 패턴을 추가. 허용 오차는 `config/tolerances.yaml by_unit`.
- 고영향(≥ 0.7)·저신뢰(< 0.5) claim 은 `review/<KST날짜>.md` 에 쌓인다. 안 읽어도 파이프라인은 돈다. decision 반영 명령(`verify apply`)은 Phase 2 후반.

## 3e. 일일 다이제스트 (Phase 2)
- 틱 끝에 `digests/<KST날짜>.md` 를 다시 쓴다(그날 마지막 틱이 최종본). 수동: `uv run macroweb digest --date 2026-11-03` · 값만 보기 `--json`.
- 줄 1(레짐)·6(시장 정합성)·2 의 diff 수는 Phase 3 엔진이 없어 "미구현" 으로 적힌다 — 숫자를 지어 넣지 않는다. 줄 3–5 는 **그날 추출된** VERIFIED/CORROBORATED claim 중 impact 순, 각주는 claim_id.
- 줄 9 의 비용은 `llm_batch.cost_usd` 합(API 환산 추정, 구독이라 청구 아님). 줄 10 은 `config/calendar.yaml` 의 14일 내 이벤트(미확정 표시).

## 3f. 거미줄 (Phase 3 v1, ADR-0010)
- 처음 한 번: `uv run macroweb graph load-seed` (seed/ → candidate 노드·엣지; 시드 엣지는 evidence 0 으로 시작하고 Story 가 붙으면 채워진다).
- 틱은 그래프를 건드리지 않는다(v1). 하루 한 번 또는 리포트 전: `uv run macroweb graph update` → 추출 relations 를 엣지로(evidence = 그 Story 의 claim), 별칭 병합·Story 3개 이상 승격, 기한 넘긴 엣지 만료(구조 365d·권력/이익 90d·발언 30d).
- 보기: `graph propagate fomc-2026-12-09 --sign 1 --floor 0.01` · `graph path fomc-2026-12-09 sk-hynix` · `graph hubs` · `graph counts`.
- 주간: `graph diff --week 2026-W45` (스냅샷 저장) · `graph html --week` (`charts/graph-<week>.html`, 인터넷 필요: cytoscape CDN) · `graph render --week` (`charts/graph-<week>.png`, 노드 ≤ 25) · `graph export-vault` (`vault/`).
- 통계 엣지: `graph stats --pair UST:10Y NAVER:.SOX` 는 일별 변화의 r/lag 를 **계산**한다(겹치는 일수 60 미만이면 "insufficient history"). `--all --write` 는 시드의 origin=computed 엣지에 기록. 2026-11-03 기준 자료 3일치라 전부 자료 부족.
- v1 한계: 시드는 22노드/17엣지(목표 200/500 — 사람 검수 항목, `seed/*.yaml` 에 추가), 엔티티 해소는 완전 일치 별칭만, 임베딩 없음, 인물 카드는 시드 1장.

## 3g. 주간 품질 검토 (Phase 3 v1)
- `uv run macroweb quality run --week 2026-W45` → Q1 근거 무결성(evidence 없는 추출 엣지·기사 없는 claim 격리), Q2 시효(만기 forecast expired·같은 주어/술어 신값 superseded·엣지 만료), Q4 중복(별칭 병합·4주 넘은 candidate 비활성·소스 쏠림 30%), Q6 커버리지(4주 중앙값 대비 −50%, 침묵 소스, 상위 claim T0 비율). 결과 `reports/quality/<week>.md` + `quality_run` 행. `--no-apply` 는 보고만.
- 스코어카드 한 줄(`데이터 품질: Q1🟢 Q2🟢 Q3⚪ …`)이 주간 리포트 레짐 대시보드 아래에 들어간다. Q3·Q5·Q7 은 Phase 6.

## 3h. 주간 편집국 (Phase 4 v1)
- 자동: `launchd/com.sawoo.macroweb.weekly.plist`(일 17:30 KST) → `bin/run_weekly.sh` → `macroweb weekly run --week <ISO주>`. 설치는 사용자가 `bash launchd/install.sh weekly` (자동 설치는 하네스가 막는다, ADR-0003 메모).
- 수동 확인: `uv run macroweb weekly run --week 2026-W45 --dry-run` (품질 → 팩 → 초안 있으면 게이트; 모델 호출 없음) · 대화형으로는 `/weekly-report 2026-W45`.
- 산출: `data/weekly/<week>/pack.json`·`slices/*.json`·`steps.jsonl`·`draft.md`→`draft_final.md`·`gate.json`; 발행물 `reports/<week>.md`·`drafts/blog-<week>.md`·`vault/weekly/<week>.md`; `report_citation` 행(어느 claim 을 어느 주가 썼나 — Q5 소급 정정용).
- 게이트(FAIL 이면 발행 안 됨): `[F]` 문장마다 `[claim_id]`, 그 claim 이 active VERIFIED/CORROBORATED, 문장 속 숫자가 claim.value 와 `tolerances.yaml` 안, 매수·매도류 표현 없음, DEBUNKED/RECYCLED/SPAM 은 검증 노트에만, 포트폴리오 섹션에 수량·금액 없음. `uv run macroweb weekly gate --week … --json`.
- 알림: `TELEGRAM_BOT_TOKEN`·`MACROWEB_TELEGRAM_CHAT_ID`(private/.env, 별도 채팅방 권장) 가 있으면 텔레그램, 없으면 stdout+macOS 알림만.
- v1 한계: 에이전트 6+4 는 Phase 0 정의 그대로(첫 실전은 일요일 자동 실행 또는 사용자의 `/weekly-report`), 차트 캡션 삽입·토론 로그 채점은 Phase 5.

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
