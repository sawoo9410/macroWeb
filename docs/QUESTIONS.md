# QUESTIONS — 🔒 사람(상우) 결정 필요 항목. 멈추지 않고 **기본값으로 진행**한다 (PLAN §0.1-3). 결정되면 `[x]` 로 바꾸고 ADR 번호를 적는다.

- [ ] **Q1 저장소 공개 범위.** `github.com/sawoo9410/macroWeb` 은 현재 **PUBLIC** 이다. `PLAN.md` 에 재직사(어보브반도체)·통근 경로·포트폴리오 구성·실명이 들어 있다. 기본값: 현 상태 유지(사용자가 만든 설정). 권장: `gh repo edit sawoo9410/macroWeb --visibility private --accept-visibility-change-consequences`. (2026-11-01, ADR-0003)
- [ ] **Q2 주간 편집국 API 폴백.** 구독 경로(`claude -p`)가 사용 한도(5시간/주간 창)에 걸리면 API 키로 재실행할지. 기본값: **안 함**(`models.yaml weekly_runner.api_fallback: false`) — 실패 알림 + 다음 틱 재시도. (ADR-0002)
- [ ] **Q3 SEC EDGAR User-Agent.** SEC 는 UA 에 연락처(이메일)를 요구한다. 개인정보를 외부 요청에 넣기 전 허락 필요. 기본값: `sec_edgar_fts` **비활성**, probe 도 하지 않음. 허락 시 UA 문자열을 지정해 주면 활성화.
- [ ] **Q4 수집기 UA 에 레포 URL/연락처 포함 여부.** 현재 `Mozilla/5.0 (compatible; macroweb-collector/0.1)`. 기본값: 포함 안 함. (`src/macroweb/collect/politeness.py`)
- [ ] **Q5 텔레그램 별도 채팅방.** 기존 봇 토큰 재사용 + 새 `MACROWEB_TELEGRAM_CHAT_ID`. 기본값: 토큰 재사용, chat_id 는 사용자가 `private/.env` 에 기입(Phase 4 전).
- [ ] **Q6 맥 깨우기.** `sudo pmset repeat wakeorpoweron MTWRFSU 06:55:00` 과 일요일 17:25 기상은 sudo 라 사용자가 직접 실행(Phase 1 launchd 설치 전).
- [ ] **Q7 블로그 문체 샘플.** `AI 투자 일기` 최근 5편을 `prompts/style/` 에 넣어 달라(Phase 4 writer-ko 전). 기본값: 샘플 없이 PLAN §10.4 문체 규칙만.
- [ ] **Q8 `private/portfolio.yaml` 작성** (Phase 5 포트폴리오 렌즈 전). 포맷은 Phase 5 에서 제안.
- [ ] **Q9 월 상한 $45 유지 여부.** 2026-11 단가로 API 예상 ≈ $9/월(주간 편집국은 구독). 기본값: $45 유지(여유분은 라우팅 상향 실험에 쓴다).
- [ ] **Q10 raw 보존 정책** — 90일 후 압축, 1년 후 삭제(PLAN §3.3). 기본값 채택 예정, Phase 1 ADR.
- [ ] **Q11 launchd 실제 설치 시점** — Phase 1 "collect 3일 연속 무인 실행" 시작 전. 기본값: Phase 1 첫 세션. Phase 0 은 dry-run 만(잡을 남기지 않음).
- [ ] **Q12 ALFRED(발표 시점별 FRED) 접근 방식** — Phase 6 Q5 지표 수정치용. 조사 후 ADR.
- [ ] **Q13 Alpha Vantage 미사용 확정** — investment-monitor 가 같은 무료 키를 매일 쓴다(PLAN §0.3). 기본값: 사용 안 함. 확인만.
- [ ] **Q14 Phase 4 이전 주간 리포트 수동 생성(Phase 2 DoD)** 은 대화형 세션에서 `/weekly-report` 를 사람이 호출한다. 자동 실행은 Phase 4. 확인만.
- [ ] **Q15 기존 ping-pong debate 시스템 위치.** PLAN 은 "기존 시스템 이식"이라 했지만 이 머신에서 찾지 못했다(ADR-0001). 경로를 알려주면 스킬에 이식; 없으면 현재 스킬(§10.3 프로토콜)로 간다.
- [ ] **Q16 FRED API 키.** 키 없는 경로(fredgraph.csv)가 수집기 UA 에 응답하지 않아 FRED 시리즈 15개(DGS10·CPI·WALCL·VIX·유가 등)는 **키 입력 후** 수집된다. `https://fred.stlouisfed.org/docs/api/api_key.html` 에서 무료 발급 → `private/.env` 의 `FRED_API_KEY`. market-data DoD 가 여기 걸려 있다.
- [ ] **Q17 ECOS·DART 키와 통계 코드.** `ECOS_API_KEY`·`DART_API_KEY` 입력 후 첫 수집에서 `config/sources.yaml` 의 ECOS 통계표(722Y001 기준금리·731Y001 환율) 코드가 맞는지 확인한다(⚠️ 미검증).
- [ ] **Q18 글로벌 지수 백업 경로.** Stooq 가 JS 봇 검사로 막혀 S&P500·SOX·KOSPI 일별 종가는 FRED(SP500·NASDAQCOM 시리즈) 또는 FinanceDataReader 중 택일. 기본값: FRED 시리즈 추가(키 필요) + FDR 은 KRX 전용으로 Phase 1 market-data 단계에서 결정.
