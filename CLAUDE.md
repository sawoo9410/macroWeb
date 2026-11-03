# MacroWeb — 거미줄

목적: 매일 수집·검증·그래프 갱신, 매주 거시 인사이트 리포트 발행. **`PLAN.md`(v0.3)가 단일 진실원(SSOT)**이다.
현재 Phase: **3 거미줄 v1** — ADR-0010 "다 구축하고 손본다" 모드. 이월 항목(Phase 1: 3일 무인 실행·launchd daily / Phase 2: T0 diff·라우팅 실험·첫 수동 리포트·평가셋 라벨)은 `docs/phase_status.json` 의 `carry_over` 가 단일 TODO 다. 사람용 요약은 `docs/PLAN_DIGEST.md`(세션 시작 시 먼저 읽을 것).
PLAN과 ADR(`docs/decisions/`)이 충돌하면 ADR이 이긴다(충돌 사실을 ADR에 명시).

## 명령어

| 하는 일 | 명령 |
|---|---|
| 환경·DB·설정·훅 점검 (네트워크 제외) | `make doctor` (= `uv run macroweb doctor --quick`) |
| 소스 probe 포함 전체 점검 | `make doctor-full` |
| 테스트 / 린트 | `make test` · `make lint` |
| 월 비용 재계산 (config/models.yaml 단가 기준) | `make cost` |
| 설정 파일 스키마 검증 | `uv run macroweb config validate` |
| DB 생성·무결성 | `uv run macroweb db init` · `uv run macroweb db check` |
| 소스 목록 / 실제 요청 검증 | `uv run macroweb source list` · `uv run macroweb source probe --all` |
| Phase DoD 상태 보기/갱신 | `uv run macroweb phase show` · `uv run macroweb phase set 0.make-doctor done` |
| launchd plist 문법+로드 확인(잡을 남기지 않음) | `make launchd-dryrun` |
| **수집 틱 (Phase 1 구현됨)** | `uv run macroweb collect` (`--source <id>` · `--force` · `--no-bodies`) · 통계 재생성 `uv run macroweb stats --date YYYY-MM-DD` |
| 픽스처 캡처 / 골든 갱신·검사 | `uv run macroweb source capture <id>` · `uv run macroweb source golden --write` · `uv run macroweb source golden` |
| 시장 데이터 조회 (ADR-0005 키 없는 UST·ECB·NAVER·KRAKEN) | `uv run macroweb market latest [--like 'UST:%']` · `uv run macroweb market get UST:10Y --limit 10` |
| **30분 틱 (launchd 진입점)** | `uv run macroweb tick` (= collect → extract ≤ `calls_per_tick` → verify → digest; `--no-extract`, `--extract-cap N`) |
| **추출 (Phase 2, ADR-0007 claude -p 구독)** | `uv run macroweb extract` (`--dry-run` 선별만 · `--limit N` · `--story <id> --force` 재추출) · 결과 `uv run macroweb extractions` · `claim search <단어>` · `claim get <id>` |
| **검증 v1 (ADR-0009, 모델 호출 없음)** | `uv run macroweb verify` (`--since-hours 72` · `--all` 재라벨 · `--story <id>`) → `claim.label/confidence`, 고영향·저신뢰는 `review/<날짜>.md` |
| **일일 다이제스트 10줄** | `uv run macroweb digest [--date YYYY-MM-DD] [--json]` → `digests/<날짜>.md` (틱마다 다시 씀; 미구현 엔진은 그렇다고 적힘) |
| **거미줄 (Phase 3 v1)** | `uv run macroweb graph load-seed` · `graph update` (추출 relations→엣지+해소+만료) · `graph propagate <node> --sign ±1 [--as-of]` · `graph path <src> <dst>` · `graph hubs` · `graph diff --week` · `graph stats --pair A B` (r/lag 계산, 자료 부족이면 그렇다고 출력) · `graph export-vault` · `graph html --week` · `graph render --week` · `graph counts` |
| **주간 품질 검토 v1** | `uv run macroweb quality run [--week] [--no-apply]` → Q1·Q2·Q4·Q6 + `reports/quality/<week>.md` (Q3·Q5·Q7 은 Phase 6) |
| 이후 단계 (Phase 4+ 스텁) | `uv run macroweb weekly` · `monthly` |

## 세션 운영 규칙 (PLAN §0.1 요약)

1. **Phase 순서 — ADR-0010 으로 완화.** 각 Phase 는 MVP 로 구현하고 넘어가되, 미완 DoD 는 `phase_status.json carry_over` 에 남기고 "다음 가자" 는 가장 앞 Phase 의 이월 항목부터 본다. 불변 규칙은 그대로.
2. **설계 결정은 ADR로.** `docs/decisions/NNNN-제목.md` (맥락/선택지/결정/결과).
3. **🔒 항목은 멈추지 않는다.** `docs/QUESTIONS.md`에 적고 PLAN §0.3 기본값으로 진행.
4. **가짜 데이터 금지.** 출처 없는 숫자·인용·URL을 만들지 않는다. 테스트는 `tests/fixtures/`의 실제 스냅샷으로.
5. **Phase 끝마다 `make doctor` 통과.**
6. **모든 단계는 CLI로 독립 실행·재실행 가능(idempotent).**
7. **스크래핑 예절:** robots.txt, 도메인당 동시 1연결, 간격 ≥ 2s, 유료 벽 본문 수집 금지.
8. **"다음 가자"** = 현재 Phase의 다음 미완료 DoD 항목을 이어간다. 파일은 완전한 파일로 쓴다.

## 불변 규칙

1) 출처 없는 숫자·인용·URL 생성 금지 2) 리포트 `[F]` 문장은 VERIFIED/CORROBORATED claim_id 각주 필수 3) 매수·매도·비중 조절·헤지 지시 금지
4) 유료 벽 뒤 본문 수집 금지(제목·요약·링크만) 5) 모델명·단가는 `config/models.yaml`에만(코드 하드코딩 금지) 6) 모든 단계 idempotent
7) **`private/`·`.env*`(`.env.example` 제외)·토큰 파일은 어떤 방법으로도 읽거나 출력하지 않는다** — cat/grep/sed/source 후 echo/env/printenv, Read 도구, 스크립트 전부. 변수 이름은 `private/env.example`에서 본다. 서브에이전트 프롬프트에도 이 문장을 넣는다. (`.claude/settings.json` deny 규칙 + `guard_bash.py` 훅이 이중으로 막는다)
8) git: 자기 변경만 `git add <파일>`. `git add -A`·`commit -a`·`push --force` 금지. 자기가 만들지 않은 미커밋 변경을 되돌리지 않는다.
9) 외부 요청(HTTP 헤더·URL·페이로드)에 이메일·이름 등 개인정보를 넣기 전엔 사용자에게 묻는다(SEC EDGAR User-Agent 포함).

## 데이터 규칙

- `data/raw/` 스냅샷은 수정·삭제 금지(보존 정책은 ADR로). DB 스키마 변경은 `src/macroweb/db/migrations/NNNN_*.sql`로만.
- 수치는 `market` 테이블·데이터 API에서 온 값만 `[F]`. 추정 r/lag 금지(계산해서 넣는다).
- 어보브반도체(102120)는 `conflict_of_interest=1`, 리포트에서는 공시 사실만.

## 스타일

완전한 파일로 쓰기 · 커밋 제목은 영문 1줄(트레일러 허용) · 리포트는 한국어·용어 괄호 풀이·투자 공부 1년차 눈높이 · 표보다 문장.

## 레포 지도

`src/macroweb/` (cli·doctor·cost·config·db·llm·collect/…/publish) · `config/` (sources·models·quality·verify·extract·aliases·traps·themes·calendar·key_persons·tolerances·glossary·cost_workload) · `prompts/` (버전·CHANGELOG) · `seed/` (시드 그래프·검증 대상 claim) · `.claude/` (agents 14·skills 9·hooks 4·settings) · `launchd/`·`bin/` (잡) · `reports/`·`digests/`·`charts/`·`drafts/`·`review/`·`vault/` (산출물) · `data/`·`logs/`·`private/` (git 제외)
