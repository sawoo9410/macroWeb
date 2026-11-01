# ADR-0001 — Claude Code 기능·모델 단가·실행 환경 사실 검증 (PLAN ⚠️ 항목)

- 상태: 확정 · 날짜: 2026-11-01 · Phase 0
- 검증 방법: `https://code.claude.com/docs/en/claude_code_docs_map` 에서 페이지 목록을 받아 `hooks` · `sub-agents` · `skills` · `headless` · `cli-reference` · `authentication` · `costs` · `permissions` · `settings` · `model-config` · `tools-reference` · `agent-sdk/{overview,python,cost-tracking}` 원문(.md)을 내려받아 대조. 단가는 `https://platform.claude.com/docs/en/about-claude/pricing`. Claude Code CLI 버전 2.1.304.

## 맥락
PLAN §13 은 서브에이전트·스킬·훅·헤드리스 플래그·SDK 를 "⚠️ docs 확인" 으로 표시했다. 틀린 가정 위에 레포를 만들면 Phase 4 러너가 깨진다.

## 검증 결과 — PLAN 의 가정 vs 공식 문서

| 항목 | PLAN 가정 | 문서 사실 | 조치 |
|---|---|---|---|
| 훅 이벤트명 | SessionStart · PreToolUse(Bash) · PostToolUse(Write/Edit) · Stop | ✅ 전부 존재. 설정은 `.claude/settings.json` `hooks` 키, matcher 는 `Bash`, `Edit\|Write`. 입력은 stdin JSON(`tool_name`, `tool_input`, `cwd`, `agent_type` …). `$CLAUDE_PROJECT_DIR` 환경변수 제공. 설정 파일 변경은 **세션 중 즉시 적용**됐다(이 세션에서 관찰) | 그대로 구현 |
| PreToolUse 차단 방식 | "차단" | exit 2 + stderr, 또는 exit 0 + JSON `hookSpecificOutput.permissionDecision: deny\|ask\|allow` (+`permissionDecisionReason`). 우선순위 deny > defer > ask > allow. 훅은 **서브에이전트 안에서도** 실행되며 `agent_type` 이 들어온다 | `guard_bash.py` 는 JSON 방식. `agent_type == fact-checker` 이면 쓰기성 Bash 를 deny → "fact-checker 쓰기 금지"를 실제로 강제. heredoc 본문은 데이터로 보고 평가에서 제외(첫 버전이 레포 스캐폴딩 heredoc 을 막았던 교훈) |
| Stop 훅 "체크리스트 출력" | Stop 훅이 출력하면 보인다 | ✏️ Stop 의 stdout 은 **디버그 로그로만** 간다. 사용자에게 보이려면 JSON `systemMessage`; exit 2/`decision: block` 은 Claude 를 계속 일하게 만든다(8회 연속 캡) | `phase_check.py` 는 `{"systemMessage": …}` 만 출력, 절대 block 하지 않음 |
| SessionStart 컨텍스트 | 훅 출력 | ✅ SessionStart 의 plain stdout 은 Claude 컨텍스트에 추가됨(10,000자 캡) | `session_start.py` plain text |
| PostToolUse 린트 피드백 | — | exit 2 의 stderr 를 Claude 가 본다(도구는 이미 실행됨) | `lint_json.py` exit 2 |
| 서브에이전트 frontmatter | name · description · tools · model | ✅ + `disallowedTools` · `permissionMode` · `maxTurns` · `effort` · `skills` · `memory` · `omitClaudeMd` · `color`. `model` 값: `sonnet\|opus\|haiku\|fable\|<full id>\|inherit` | 14개 에이전트에 effort·maxTurns 추가 |
| 에이전트 `tools: [Bash(uv run macroweb claim get *)]` (부록 F) | 패턴으로 도구 제한 | ✏️ `tools` 는 **도구 이름 목록**(쉼표 문자열 또는 YAML 리스트). 패턴은 `permissions.allow/deny`(`Bash(uv run macroweb *)`)로. `disallowedTools` 에 패턴을 쓰면 **도구 전체**가 빠진다 | fact-checker: `tools: Read, Grep, Glob, Bash` + `disallowedTools: Write, Edit, NotebookEdit` + 훅 |
| 스킬 | `.claude/skills/<name>/SKILL.md` | ✅ frontmatter `name`(기본 디렉터리명) · `description` · `argument-hint` · `disable-model-invocation` · `user-invocable` · `allowed-tools` · `context: fork` + `agent` · `$ARGUMENTS`/`$0` 치환 | 9개 스킬. 큰 워크플로(weekly/monthly/quality/debate/launchd)는 `disable-model-invocation: true` 로 수동 트리거만 |
| 헤드리스 플래그 | `claude -p "/weekly-report W" --output-format json`, max-turns, 권한 모드 | ✅ `-p/--print` · `--output-format text\|json\|stream-json` · `--max-turns` · `--max-budget-usd`(클라이언트 추정치) · `--permission-mode acceptEdits\|auto\|dontAsk\|…` · `--allowedTools "Bash(uv run macroweb *),Read"` · `--json-schema` · `--agents` · `--settings` · `--name`. **추가:** `--permission-prompts none`(v2.1.259+) — 아무도 답할 수 없는 프롬프트를 거부하고 계속 진행. `--bare` 는 OAuth/키체인을 **읽지 않으므로** 구독 경로와 양립 불가 | `synth/headless.py` 의 커맨드 빌더에 반영. `--bare` 금지 |
| 헤드리스 종료 | — | 턴이 끝난 뒤 백그라운드 서브에이전트를 기다린다(기본 10분 idle 캡), 예산 도달 시 중단 | 러너 타임아웃 60분은 별도 유지 |
| Agent SDK | Python, 서브에이전트·토론·게이트 코드 통제 | `pip install claude-agent-sdk`, `ClaudeAgentOptions(allowed_tools, permission_mode, max_turns, max_budget_usd, agents, setting_sources, cwd)`. **과금/인증:** docs overview — "Anthropic 은 서드파티가 claude.ai 로그인/한도를 자기 제품에 제공하는 것을 허용하지 않는다(Agent SDK 포함). API 키 인증을 쓰라" | ADR-0002 — 주간 러너는 `claude -p` |
| 모델 별칭·ID | "소/중/대, 실제 값 docs" | 별칭 `haiku`·`sonnet`·`opus`·`fable`; 현행 ID `claude-haiku-5-5` · `claude-sonnet-5-5` · `claude-opus-5-5`(· `claude-fable-5-1`). `CLAUDE_CODE_SUBAGENT_MODEL` 로 서브에이전트 기본 모델 지정 가능 | `config/models.yaml` tiers.small/mid/large |
| 단가 (§16.4) | Haiku $1/$5 · Sonnet $3/$15 · Opus $5/$25 · 배치 50% | ✏️ **Haiku 5.5 $0.10/$0.50**(≤100K 프롬프트) · **Sonnet 5.5 $2/$10** · **Opus 5.5 $4/$20** · 캐시 읽기 0.1×(Opus/Sonnet 5.5 는 0.05×) · 배치 50% ✅ | `make cost` 재계산: T1/T2 추출 $9 → $0.9, 합계 API ≈ $9/월(주간 편집국은 구독). 상한 $45 유지(Q9) |
| 권한 규칙 | 허용 도구 목록 고정 | `permissions.allow/deny/ask`, `Bash(prefix *)`, `Read(./private/**)`, `Edit(./data/raw/**)`. **`Write(path)` 규칙은 매치되지 않는다 → `Edit(path)` 사용.** Read deny 는 cat/head/sed 등 Bash 파일 명령과 리다이렉션에도 적용 | `.claude/settings.json` |
| 프로젝트 `settings.json` 과 `-p` | — | `-p` 세션도 프로젝트 `.claude/settings.json` 의 훅·권한을 읽는다(`--bare` 제외) | 헤드리스 러너가 같은 가드를 받는다 |
| 실행 환경 | Python 3.12 (uv) | ✏️ 머신에 uv 없음·시스템 Python 3.9 → `brew install uv` + `uv python install 3.12`(3.12.16). `claude` 2.1.304 ✅, playwright 없음(Phase 1), pre-commit 없음(`uvx`) | pyproject `requires-python >=3.12` |
| 래퍼 락 `flock -n 9` (부록 H) | flock | ✏️ macOS 에 `flock(1)` 없음 | `bin/_common.sh` mkdir 락 + pid 고아 정리 |
| plist 경로 `/Users/sawoo/macroweb` | — | ✏️ 실제 `/Users/seosang-u/projects/finance/macroWeb`, uid 501 | `launchd/*.plist` |
| 기존 자산 | ping-pong debate 시스템 "기존" | ⚠️ 이 머신의 `~/projects` · `~/.claude` 에서 찾지 못함(오탐만). moat-journal 에 `claude --print` 헤드리스 자동화는 존재 | ping-pong 은 스킬로 신규 작성(§10.3 프로토콜 그대로). 원본 위치를 알려주면 이식(Q15) |
| 맥락 시드 §1.5 | 사실 아님, 검증 대상 | 수집 전이라 검증 불가 | `seed/claims_to_verify.yaml` 에 UNVERIFIABLE 로 등록, Phase 2 첫 검증 대상 |
| 소스 URL 50개 | 첫 세션에서 전부 실제 요청 | 32개 등록(EDGAR 는 Q3 로 비활성), probe 실행 | 결과: `docs/SOURCE_PROBE_2026-11-01.md` |

## 결정
위 표의 "조치" 열을 그대로 레포에 반영한다. PLAN 본문은 수정하지 않고(SSOT 보존) 이 ADR 이 우선한다.

## 결과
- 훅 4개·에이전트 14·스킬 9·settings 가 문서 규격대로 작성됨(`make doctor` 의 claude-settings/hook 검사).
- 비용 모델이 단가 파일 기준으로 재계산 가능(`make cost`).
- 재검증 시점: Claude Code 마이너 업데이트마다 `claude --version` 과 이 표를 대조(특히 `--permission-prompts`, Stop 훅 캡, `tools` 패턴 지원 여부).

## 부록 — 소스 URL probe (2026-11-01, `uv run macroweb source probe --all --include-disabled`)

전체 표: `docs/SOURCE_PROBE_2026-11-01.md`. 결과 **29/32 도달**. 일반 수집기 UA(`Mozilla/5.0 (compatible; macroweb-collector/0.1)`), 키 없이, 도메인당 2초 간격.

| 소스 | 결과 | 조치 |
|---|---|---|
| fred_api · dart_api · ecos_api | 키 없이 400/에러 페이지로 응답 — 서버 도달 확인 | probe 는 `auth_env` 가 있는 소스의 4xx 를 "도달(키 필요)"로 센다 |
| whitehouse_news | `/feed/` 404 → `/news/feed/` 200 | URL 교체 |
| tomshardware · calculated_risk | 리다이렉트 후 200 (`feeds.xml`, feedburner) | Phase 1 어댑터에서 최종 URL 사용 |
| bls_release_schedule | 403 (선언형 UA 차단) | **비활성.** 브라우저 UA 위장은 하지 않는다(PLAN §0.1-7 예절·robots 존중; 세션의 자동 분류기도 UA 위장 시도를 차단했다). Phase 1 대안: FRED `releases/dates`(키) |
| cme_fedwatch | 403 (봇 차단) | 비활성 유지. Phase 1 에서 Playwright + robots.txt 확인 후 결정 |
| reddit_stocks | 403 | 비활성. Reddit 은 고유·설명형 UA 와 API 정책 준수 요구 → UA 정책(Q4) 결정 후 공식 방식으로 |
| sec_edgar_fts | 200 (일반 UA 로 도달) | 비활성 유지 — SEC 는 UA 에 연락처를 요구하므로 수집은 사용자 허락(Q3) 뒤에 |

Phase 1 DoD(소스 20개: T0 8 · T1 6 · T2 3 · T3 3)는 도달 확인된 29개 중에서 고른다.
