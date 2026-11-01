# ADR-0002 — 주간 편집국 실행기의 과금 경로: `claude -p` 구독 OAuth

- 상태: 확정(폴백 정책은 🔒 QUESTIONS Q2) · 날짜: 2026-11-01 · Phase 0 첫 확인 항목(PLAN §15 2-1)

## 맥락
PLAN §0.3 은 주간 합성 실행기를 "Claude Agent SDK(Python), 구독 경로 확인 시 `claude -p`" 로 두고, 월 비용 $43 중 $22 가 주간 편집국이었다. 어느 쪽이 구독 한도로 과금되고 어느 쪽이 API 키로 과금되는지가 비용 구조를 가른다.

## 확인한 사실 (2026-11-01, code.claude.com/docs)
1. **인증 우선순위**(authentication.md "Authentication precedence"): `ANTHROPIC_AUTH_TOKEN` > `ANTHROPIC_API_KEY`(승인 시) > … > `CLAUDE_CODE_OAUTH_TOKEN`(`claude setup-token` 으로 만든 1년짜리 OAuth, "CI 파이프라인·스크립트용") > `/login` 구독 OAuth(Pro/Max/Ultra 기본). 구독과 API 키가 둘 다 있으면 **API 키가 이긴다**.
2. **구독 과금**(costs.md): "Claude Pro, Max, Ultra 구독자는 사용량이 구독에 포함되어 세션 비용 수치는 청구와 무관". 즉 `claude -p` 를 구독 OAuth 로 돌리면 API 청구 $0, 대신 구독 사용 한도(세션/주간 창)를 쓴다.
3. **Agent SDK**(agent-sdk/overview.md): "사전 승인 없이는 서드파티 개발자가 claude.ai 로그인/한도를 자기 제품에 제공할 수 없다 — Agent SDK 로 만든 에이전트 포함. 퀵스타트의 API 키 인증을 쓰라." 또한 authentication.md: `ANTHROPIC_API_KEY`·`apiKeyHelper` 는 "CLI 와 그것을 감싸는 표면(VS Code 확장, **Agent SDK**, GitHub Actions)" 에 적용.
4. **`--bare`**(headless.md): 스크립트용 권장 모드지만 "OAuth 자격증명이나 시스템 키체인을 절대 읽지 않는다 — `ANTHROPIC_API_KEY` 를 설정하라". 구독 경로에서는 쓸 수 없다.
5. **이 머신의 선례**: `~/projects/finance/moat-journal/automation/cron/*.sh` 가 launchd 아래에서 `claude --print` 를 구독 OAuth(Keychain `Claude Code-credentials`)로 매일 돌리고 있고, 토큰 만료 사고(2026-08-22) 후 `claude --print -p ping` 선제 갱신(잔여 300분 임계) 패턴을 쓴다.

## 선택지
| | A. Agent SDK(Python) + API 키 | **B. `claude -p` 헤드리스 + 구독 OAuth** | C. `claude -p` + API 키 |
|---|---|---|---|
| 과금 | API (주간 ≈ $16/월, 2026-11 단가) | 구독 한도 (API $0) | API ≈ $16/월 |
| 정책 적합성 | ✅ 문서가 요구하는 방식 | ✅ 개인 CLI 사용·`setup-token` 은 문서화된 CI/스크립트 경로 | ✅ |
| 코드 통제 | 턴·토큰·에러를 파이썬에서 직접 | 플래그로 통제(`--max-turns`, `--max-budget-usd`, `--permission-prompts none`, `--output-format json` + `total_cost_usd`) | 동일 |
| 리스크 | 비용 | 일요일 저녁 구독 창 소진, Keychain 접근·토큰 만료, 대화형과 동일 설정 공유 | 비용 |
| 선례 | 없음 | moat-journal 운영 중 | — |

## 결정
**B.** 주간 편집국은 `claude -p "/weekly-report <WEEK>"` 로 실행한다(`src/macroweb/synth/headless.py`). 규칙:
- 러너는 자식 프로세스 환경에서 `ANTHROPIC_API_KEY`·`ANTHROPIC_AUTH_TOKEN` 을 **제거**한다(우선순위 때문에 남겨두면 API 과금으로 넘어간다). `MACROWEB_WEEKLY_AUTH=api` 로만 되돌린다.
- `--bare` 금지. `--permission-prompts none --permission-mode acceptEdits --allowedTools "<고정 목록>" --max-turns 60 --max-budget-usd 8 --output-format json`.
- 토큰 갱신: Phase 4 러너가 실행 전 Keychain 만료 시각을 보고 잔여 < 90분이면 `claude --print -p ping` 으로 갱신(moat-journal 패턴 이식). 실패 시 알림 + 재시도 1회.
- Track A(일일 추출·배치)는 계속 Anthropic Python SDK + `ANTHROPIC_API_KEY`(배치 50% 할인은 API 에만 있다).
- 폴백: 구독 한도 오류(`rate_limit`)가 나면 기본은 **알림 후 중단**(Q2). `models.yaml weekly_runner.api_fallback: true` 일 때만 API 키로 1회 재실행하며 그 비용은 월 상한에 포함.

## 결과
- 월 API 예상 ≈ $9(추출·T0 정독·승급·품질 검토·월간) — PLAN §0.3 의 "구독 헤드리스 경로가 확인되면 월 $20 수준" 보다 낮다(단가 하락 반영). 상한 $45 는 유지(Q9).
- 주간 편집국 설계(서브에이전트 14·스킬·게이트)는 `.claude/` 정의를 그대로 쓰므로 대화형 디버깅과 헤드리스가 같은 코드 경로를 탄다(PLAN §13.5 의도 충족).
- Agent SDK 러너(`run_weekly.py` 의 SDK 버전)는 만들지 않는다. 정책이 바뀌면 이 ADR 을 대체한다.
