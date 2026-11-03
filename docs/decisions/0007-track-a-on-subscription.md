# ADR-0007 — Track A(일일 추출·검증 루브릭·감사)도 `claude -p` 구독 경로로

- 상태: 확정(사용자 결정 2026-11-02: "Max 쓰고 있어. 그냥 구독으로 가자") · ADR-0002 를 확장, PLAN §3.2(Track A = Python SDK 직접 호출 + 배치 API)·§0.3 배치 타이밍·§16.4 비용 계산을 대체한다.

## 맥락
PLAN 은 일일 추출을 Anthropic API(배치 50% 할인, JSON 스키마 강제)로, 주간 편집국만 구독으로 두었다(ADR-0002). 사용자는 Claude Max 구독자이고 Console API 계정을 따로 두고 싶지 않다. 질문은 "일일 추출도 지금 launchd 잡처럼 구독으로 돌릴 수 있는가" — 기술적으로 가능하며, 차이는 비용이 아니라 **구독 사용 한도를 자동 호출이 함께 쓴다**는 점이다.

## 측정 (2026-11-02, `claude -p --model haiku --tools "" --max-turns 1`, 최소 프롬프트)
| 변형 | 입력 토큰(캐시 생성+읽기+신규) | 출력 | 소요 |
|---|---|---|---|
| A 기본 하네스 프롬프트 (프로젝트 디렉터리) | 22,935 | 9 | 2.6s |
| B `--system-prompt` 로 대체 | 19,683 | 9 | 5.1s |
| C B + `--setting-sources user` (프로젝트 훅·CLAUDE.md 제외) | 14,790 | 9 | **1.1s** |
| D C + `--json-schema` | 14,913 | 166 | 3.0s |
(첫 측정, 다른 세션 컨텍스트: 기본 11,243.) 결론: 호출당 **약 1.5만 토큰의 하네스 입력이 바닥**이고 대부분 캐시 읽기다. 기사 본문 ~3k 를 더하면 호출당 ~1.8만.
API 경로 대비: 같은 추출이 Haiku 배치로 Story 당 ≈ $0.0003, Track A 전체 월 ≈ $9.7(`make cost`, 2026-11 단가).

## 선택지
| | API 키 (PLAN 기본) | **구독 `claude -p` (채택)** | 혼합 |
|---|---|---|---|
| 청구 | ≈ $10/월 | $0 | ≈ $8/월 |
| 사용자 세션과의 한도 공유 | 없음 | **있음**(Max: 5시간 창·주간 한도) | 일부 |
| 호출당 토큰 | ~4k | ~18k(하네스 1.5만 포함) | — |
| 배치 할인·비동기 | 있음 | 없음(동기, 틱마다 조금씩) | — |
| JSON 보장 | `output_config.format` | `--json-schema`(검증·재시도) | — |
| 운영 복잡도 | 키 관리 | 토큰 갱신·한도 감지 | 둘 다 |

## 결정
1. `config/models.yaml track_a_runner.mode = claude_headless`. `api` 로 바꾸면 ADR-0006 의 `Extractor` 를 Batches API 구현으로 교체하는 것 외에 달라지는 게 없다(인터페이스 동일).
2. 호출 규약(`config/extract.yaml headless`): `--model <haiku|sonnet|opus>`(models.yaml 등급 별칭) · `--system-prompt-file prompts/extract/v<N>.md` · `--setting-sources user` · `--tools ""` · `--max-turns 1` · `--json-schema <ExtractionResult>` · `--output-format json` · `--no-session-persistence`. 자식 환경에서 `ANTHROPIC_API_KEY` 제거(ADR-0002 와 동일). 프로젝트 디렉터리 밖(`data/work/`)에서 실행해 프로젝트 훅이 호출마다 돌지 않게 한다.
3. **분산 처리**: 배치 대신 30분 틱마다 새 Story ≤ 15건(`calls_per_tick`), 하루 ≤ 150호출(`max_calls_per_day`), 동시 2. 사용자가 깨어 있는 낮 시간 창을 덜 먹도록 야간(00:00–07:00 KST)에 상한을 높이는 것은 Phase 2 에서 측정 후 결정.
4. **한도 가드**: `claude -p` 결과가 한도 오류(`rate_limit`/usage limit 문구, `is_error`)면 `logs/claude_limit.stamp` 를 쓰고 `limit_backoff_s`(1시간) 동안 모든 LLM 작업을 건너뛴다. 수집(Track A 의 L1)은 영향받지 않는다. 사용자 세션에서 `/usage` 로 창을 확인할 수 있다.
5. 토큰 회계: `--output-format json` 의 `usage`·`modelUsage` 를 `extraction.tokens_in/out` 과 `run` 에 기록. `cost_usd` 는 클라이언트 추정치(청구 아님)로 적고, `make cost` 는 API $0 + **구독 사용량 추정(호출/일·토큰/일)** 을 보여준다. PLAN §0.3 의 "월 API 하드캡 $45" 는 이제 "일 호출 상한 150·한도 가드" 로 대체된다(API 모드로 되돌리면 캡이 다시 산다).
6. 평가 실험(§6.2.4 Haiku vs Sonnet 층별 비교)은 그대로 — `--model` 만 바꿔 같은 Story 를 두 번 돌린다.
7. 보류: `--bare`(OAuth 불가), Agent SDK(API 키 정책, ADR-0002).

## 결과
- 월 API 청구 **$0**. `make cost` 추정: 구독 약 126호출/일·2.5M 토큰/일(하네스 1.5만/호출 포함, 대부분 캐시 읽기; 주간 편집국 몫을 일 단위로 환산한 값 포함).
- 리스크와 대응: 한도 충돌 → 가드·분산; 토큰 만료 → moat-journal 식 선제 갱신(Phase 2 러너); JSON 불량 → `--json-schema` 검증 + 1회 재시도 후 격리(§6.1).
- QUESTIONS Q19(API 키) 종결. Q9(월 상한) 는 "일 호출 상한" 으로 의미가 바뀐다.

## 보완 (2026-11-03, 첫 실전 호출 뒤)
- 2026-11-03 21:39 KST 의 실패 2건(ECB 성명 4.3k자, sonnet→opus)은 스키마 위반이 아니라 **하네스 쪽 오류**였다(`is_error`, 결과 본문 없음, 출력 4,198토큰에서 끊김 — 세션에서 본 "Server error mid-response" 와 같은 모양). 같은 호출을 그대로 다시 보내자 16.6초 만에 claim 11·entity 12·relation 4 로 성공(`num_turns` 2).
- 따라서 (a) 실패 결과의 원문(`subtype`·`usage`·stderr)을 `logs/extract_failures/`(git 제외)에 남기고, (b) `error_max_structured_output_retries`·`max_turns` 계열만 "schema" 실패로 보아 승급하며, 그 밖의 하네스·네트워크 오류는 **승급하지 않고** 30분 쿨다운 뒤 최대 2회 재선별한다(`extraction.attempts`, 마이그레이션 0005). 스키마 실패는 사다리 끝에서 종결(수동 `macroweb extract --story <id> --force` 로만 재시도).
- `--max-turns` 는 1 → **2**: 턴 1 = 구조화 출력 호출, 턴 2 = 하네스가 스키마 오류를 돌려줬을 때의 정정 1회. 도구가 없으므로 루프 위험은 없고, 실패 호출의 재시도 비용(≈ 캐시 읽기 2만 토큰)만 추가된다.
- 측정값 갱신: 본문 4.3k자 Story 1건 = 입력 19,279(캐시 생성)·출력 2,814 토큰, API 환산 $0.105(sonnet). 하루 150호출 상한은 유지.
