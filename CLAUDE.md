# MacroWeb — 거미줄

목적: 매일 수집·검증·그래프 갱신, 매주 거시 인사이트 리포트 발행. **`PLAN.md`(v0.3)가 단일 진실원(SSOT)**이다.
현재 Phase: **0 스캐폴딩** → 기계용 상태는 `docs/phase_status.json`, 사람용 요약은 `docs/PLAN_DIGEST.md`(세션 시작 시 먼저 읽을 것).
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
| 파이프라인 단계 (Phase별로 구현) | `uv run macroweb collect --date YYYY-MM-DD` · `normalize` · `extract` · `verify` · `graph` · `digest` · `weekly` · `monthly` |

## 세션 운영 규칙 (PLAN §0.1 요약)

1. **Phase 순서를 지킨다.** `docs/phase_status.json`의 현재 Phase DoD를 전부 통과하기 전에는 다음 Phase 코드를 쓰지 않는다(스키마·인터페이스 정의는 예외).
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

`src/macroweb/` (cli·doctor·cost·config·db·llm·collect/…/publish) · `config/` (sources·models·quality·aliases·traps·themes·calendar·key_persons·tolerances·glossary·cost_workload) · `prompts/` (버전·CHANGELOG) · `seed/` (시드 그래프·검증 대상 claim) · `.claude/` (agents 14·skills 9·hooks 4·settings) · `launchd/`·`bin/` (잡) · `reports/`·`digests/`·`charts/`·`drafts/`·`review/`·`vault/` (산출물) · `data/`·`logs/`·`private/` (git 제외)
