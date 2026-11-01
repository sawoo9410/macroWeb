# 거미줄 (MacroWeb) — 주간 거시·자금흐름 인사이트 자동화 파이프라인 마스터플랜

| 항목 | 내용 |
|---|---|
| 버전 | v0.3 — 2026-11-01 (일) · v0.2 대비: §6.2 소스·위험 기반 모델 라우팅(승급 규칙·감사 샘플·측정 실험), §10.5 주간 데이터 품질 검토 신설, 정정(Errata) 체계, 비용 재계산 |
| 용도 | **Claude Code 하네스 세션에 투입하는 실행 계획서.** 레포 루트에 `PLAN.md`로 보관하고, 세션은 이 문서를 단일 진실원(SSOT)으로 삼는다 |
| 현재 상태 | 코드 0줄. 이 문서가 유일한 산출물 |
| 실행 환경 | macOS (M1 Max) · VS Code · Claude Code · launchd · Python 3.12 (uv) |
| 소유자 | 상우 (sawoo9410) |
| 관련 자산 | 블로그 `AI 투자 일기` (월간 자산 추적), 기존 `investment-monitor` (GitHub Actions, Alpha Vantage + FDR, 텔레그램/이메일), `ping-pong debate` 시스템 (Claude Code) |

> 표기 규칙: ✅ 확인됨 · ⚠️ 하네스가 첫 세션에서 검증할 것 · 🔒 사람(상우) 결정 필요(기본값 있음) · 🚫 금지

---

## 0. 이 문서를 하네스에 던지는 법

### 0.1 세션 운영 규칙 (CLAUDE.md에 그대로 복사)

1. **Phase 순서를 지킨다.** §14의 Phase N DoD(Definition of Done)를 전부 통과하기 전에는 Phase N+1 코드를 쓰지 않는다. 단, 스키마·인터페이스 정의는 미리 해도 된다.
2. **모든 설계 결정은 ADR로 남긴다.** `docs/decisions/NNNN-제목.md` (맥락 / 선택지 / 결정 / 결과). 이 문서(§)와 충돌하면 ADR이 이긴다. 단, 충돌 사실을 ADR에 명시한다.
3. **사람 확인이 필요한 항목(🔒)은 멈추지 않는다.** `docs/QUESTIONS.md`에 질문을 적고 **기본값으로 진행**한다. 기본값은 §0.3.
4. **가짜 데이터 금지.** 출처 없는 숫자·인용·URL을 만들지 않는다. 테스트는 `tests/fixtures/`에 저장된 실제 HTML 스냅샷으로 한다.
5. **매 Phase 끝에 `make doctor`가 통과해야 한다.** (환경, DB 무결성, 소스 헬스체크, 비용 집계)
6. **모든 단계는 CLI로 독립 실행·재실행 가능(idempotent)**해야 한다. `macroweb collect --date 2026-11-01`을 두 번 돌려도 결과가 같아야 한다.
7. **스크래핑 예절:** robots.txt 준수, 도메인당 동시 1연결, 요청 간격 ≥ 2s, 유료 벽 뒤 본문은 수집하지 않는다(제목·요약·링크만).
8. **작업 스타일:** 지시가 짧아도("다음 가자") 현재 Phase의 다음 미완료 DoD 항목을 이어간다. 파일은 부분 스니펫이 아닌 완전한 파일로 쓴다. 커밋 메시지는 영문 1줄.

### 0.2 첫 세션이 해야 할 일 (순서대로)

1. 이 문서 전체를 읽고 `docs/PLAN_DIGEST.md`에 300줄 이내 요약을 쓴다 (세션 재시작 시 이 요약을 먼저 읽는다).
2. ⚠️ 항목을 모두 검증한다 — 특히 §13의 Claude Code 기능(서브에이전트·스킬·훅·헤드리스 플래그)은 공식 docs map(`https://code.claude.com/docs/en/claude_code_docs_map`)을 fetch해서 확인하고, 틀린 부분을 ADR-0001에 기록한다.
3. §13.1 레포 구조를 생성하고 `CLAUDE.md`, `.claude/agents/`, `.claude/skills/`, `.claude/settings.json`(훅)을 만든다.
4. Phase 0을 시작한다.

### 0.3 확정값과 근거

"기본값"이 아니라 근거를 갖고 정한 값이다. 근거가 바뀌면 값도 바꾼다(ADR).

| 결정 | 값 | 근거 |
|---|---|---|
| 주간 발행 | **일 17:30 KST 시작**(품질 검토 Step 0 ≤ 20분 → 편집국 17:50~), 19:30까지 완료 | 미국 금요일 마감 = 토 06:00 KST(서머타임 해제 후). 주말 정치 뉴스(일요일 시사 프로그램·주말 정상회담)까지 담고, 월요일 한국장(09:00)·미국 선물 재개(월 08:00 KST) 전날 저녁에 읽을 시간을 준다. 주간 잡 최대 60분 + fact-check 재시도 1회 여유를 더해 19:30 완료 목표. v0.3에서 품질 검토(§10.5)를 앞에 붙이면서 시작만 30분 당김. 맥은 `pmset`으로 17:25 기상 |
| 일일 처리 | **07:00 KST** | 미 정규장 마감 16:00 ET = 06:00 KST(11월~3월), 05:00 KST(서머타임). 대형 기술주 실적은 대부분 마감 직후(16:05–16:30 ET) 나오므로 07:00이면 겨울에도 30분 이상 여유. 다이제스트를 출근길(구리→대치)에 읽을 수 있게 07:30 전 발행이 목표 |
| 수집 주기 | **스케줄러 30분 틱 + 소스별 적응 주기(15분–6시간) + 이벤트 모드 10분** | 고정 4시간은 근거가 없었다. RSS는 최근 N개만 보여주므로, 피드가 한 바퀴 도는 시간(창)보다 자주 가져와야 누락이 없다. 규칙: `주기 = clamp(0.5 × 피드 창, 15분, 6시간)`, 창은 Phase 1에서 소스별로 측정. 예정 이벤트(FOMC 04:00 KST, 미 CPI 22:30 KST 겨울 기준) ±2시간 동안 T0 소스는 10분. LLM 호출은 0이라 비용 영향 없음 |
| 일일 LLM 처리량 | **T1/T2 Story 하루 80개 정밀 추출 + T0 1차 문서는 별도 전량**, 나머지는 제목·임베딩만 | 50개 소스 → 중복 제거 후 Story 300–400개/일 예상. 주간 리포트가 쓰는 건 영향도 상위 claim 100개 수준이고 Story당 claim이 3–5개라, 주 560 Story면 충분. v0.2의 120개에서 줄인 몫은 T0 정독과 품질 검토로 옮겼다(T1은 같은 사건을 여러 매체가 써서 줄여도 손실이 작다). 선별 = 테마 임베딩 유사도 × 출처 tier. 놓친 Story도 독립 출처가 3개 이상 붙으면 자동 승격되므로 중요한 건 늦게라도 잡힌다 |
| 배치 타이밍 | **수집 틱마다 롤링 배치 제출, 06:30 마지막 배치, 07:20까지 미완료분만 실시간 호출** | 배치 API는 50% 할인이지만 결과가 최대 24시간 걸릴 수 있다. v0.1처럼 07:00에 몰아 제출하면 다이제스트가 늦어진다. 밤새 나눠 제출하면 대부분 07:00 전에 끝나고, 미국 마감 직후 Story만 실시간(정가)으로 처리 |
| 월 비용 상한 | **API 하드캡 $45/월(약 6.1만원)**, 예상 $43 | §16.4 계산: T1/T2 추출 ≈ $9 + T0 정독 ≈ $3.5 + 승급 재추출 ≈ $2.2 + 주간 편집국 ≈ $22 + 주간 품질 검토 ≈ $4.3 + 월간 회고 ≈ $2. v0.2($40) 대비 증가분은 T0 1차 문서 정독과 품질 검토 — 이 시스템의 신뢰도를 만드는 부분이라 줄이지 않는다. 80%($36) 도달 시 T1/T2 추출 50개로 축소, 100%면 주간 리포트만 실행. 구독 헤드리스 경로가 확인되면 주간 몫이 빠져 월 $20 수준 |
| 주간 합성 실행기 | **Claude Agent SDK (Python)**, 구독 경로 확인 시 `claude -p` | launchd 비대화형 환경에서 턴 수·토큰·에러 처리를 코드로 통제하기 쉽다. 단 비용 구조가 둘 사이에서 갈리므로(위) Phase 0의 첫 확인 항목 |
| 시장 데이터 | **FRED·Stooq·FDR·ECOS 사용, Alpha Vantage는 쓰지 않음** | investment-monitor가 이미 AV 무료 키를 매일 쓰고 있고 무료 일일 한도가 작다(⚠️ 현재 한도 확인). 두 시스템이 같은 키를 쓰면 기존 리포트가 먼저 깨진다 |
| 그래프 뷰어 | **자체 생성 HTML (cytoscape.js)** | 거미줄의 핵심은 엣지 종류·부호(이득/손해)·가중치·시간이다. Obsidian 그래프 뷰는 링크 유무만 보여줘서 `hurt_by`와 `supplies_to`를 구분하지 못한다. 색 = 부호, 굵기 = 가중치, 시간 슬라이더. Obsidian vault는 Phase 8 선택 사항으로 강등 |
| 알림 | **기존 텔레그램 봇, 별도 채팅방** | 봇 재사용은 설정 비용 0. 단 환율 알림과 같은 방이면 리포트가 묻히므로 방을 나눈다. 텔레그램 메시지는 4,096자 제한이라 한 줄 요약 + 논제 3개 + 파일 경로만 보낸다 |
| 리포트 언어 | **한국어, 용어 괄호 풀이, 투자 공부 1년차 눈높이** | 기존 시장 브리프와 같은 독자·같은 규칙. 두 산출물의 톤을 맞춰야 월간 투자일기에 합칠 때 손이 안 간다 |
| 블로그 | **초안 md만 생성, 게시는 수동** | 티스토리 Open API가 종료되어 공식 자동 게시 경로가 없다. 로그인 세션을 자동화하면 계정 위험만 늘고 얻는 건 클릭 몇 번 |
| 포트폴리오 렌즈 | **`private/portfolio.yaml`, gitignore, 블로그 초안에서 제외** | 이 시스템의 존재 이유가 "내 자산에 걸린 엣지"를 보는 것이라 끌 수 없다. 대신 수량·금액은 리포트에 쓰지 않고 비중·노출 방향만 쓴다 |

### 0.4 지금 정할 수 없는 값 — 측정해서 정한다

아래는 숫자를 머리로 고르면 오히려 틀린다. 시작값을 두고, **언제 무엇으로 보정하는지**를 고정한다.

| 값 | 시작값 | 보정 방법 | 시점 |
|---|---|---|---|
| 같은 Story 판정(SimHash 거리, 임베딩 코사인) | ≤3, ≥0.92 | 기사 쌍 200개 수동 라벨 → "같은 Story" 정밀도 ≥ 0.95가 되는 최저 임계값 | Phase 1 끝 |
| 검증 신호 가중치(§7.2) | 수식의 초기값 | eval/verify 200개로 로지스틱 회귀, 월 1회 재학습, F1 하락 시 롤백 | Phase 6, 이후 매월 |
| 출처 신뢰도 prior | Tier별 0.15–0.95 | 소스별 claim 적중/반박 누적으로 베이지안 갱신(prior 강도 20건) | 매월 |
| 루머 유예 시간 | **2 영업일** (v0.1의 48시간에서 변경) | 금요일 저녁 루머가 주말 때문에 억울하게 감점되지 않도록 영업일 기준. 실제 "루머 → 공식 확인" 소요 시간 분포를 쌓아 90퍼센타일로 교체 | Phase 6 |
| 엣지 만료 | 종류별: 구조(공급·지분) 365일 · 권력·이익 90일 · 발언(argues/predicts) 30일 | 일괄 90일은 공급망 관계까지 지워버린다. 엣지 종류별 "재확인 간격" 분포로 보정 | Phase 7 |
| 통계 엣지 r, lag | 없음(계산 전 0) | 최근 2년 일별 수익률, lag −5~+30일 탐색, |r| ≥ 0.3 & 롤링 안정성 통과한 것만 | Phase 3 |
| 논제 정확도 목표 | 아래 §1.4-2 | 시장 대비 벤치마크 | 매월 |
| 소스 유형별 추출 모델 (§6.2) | 표의 가설 배정 | 유형별 Story 20개를 Haiku·Sonnet 둘 다로 추출해 라벨과 비교. claim F1 격차 ≥ 0.10 또는 수치 오류율 격차 ≥ 5%p인 유형만 상위 모델 | Phase 2 끝, 이후 매월 감사 결과로 재판정 |
| 일일 승급 상한 | 8건/일 | 실제 승급 발생률 4주 관찰 후 95퍼센타일로 | Phase 3 |
| 품질 검토 경보 임계값 (§10.5) | 표의 시작값 | 8주 분포를 쌓은 뒤 하위 5% / 상위 5% 지점으로 교체 | Phase 7 |

---

## 1. 목표 — "감각"을 만드는 기계

### 1.1 문제 정의

- 블로그 `AI 투자 일기`는 **월간 결과 기록**이다: 총 평가금액·손익·환율·USD 비중·현금 비중·포지션 변화(ISA S&P500 ETF, JEPQ·SPYI·SCHD·리얼티인컴 등 인컴 ETF, 어보브반도체). "무엇을 했는가"는 남지만 **"그 달 세상이 왜 그렇게 흘렀는가"**는 기록되지 않는다.
- 뉴스는 매일 흐르지만 개별 기사는 점(point)이다. 투자 감각은 점이 아니라 **선과 망(網)** — 사건 → 경로 → 결과, 누가 이득·누가 손해, 결정권자의 인센티브 — 에서 나온다.
- 지금(2026-11) 딱 그런 국면이다: AI 반도체 조정, 중간선거와 금리의 긴장, 연준 의장 교체 후 인물 성향이 시장을 흔드는 시기.

### 1.2 산출물

| 주기 | 산출물 | 소비자 |
|---|---|---|
| 30분 틱(소스별 적응) | 수집 스냅샷 (raw) | 시스템 |
| 매일 07:00 | **일일 다이제스트** (내부용 md, 10줄) + 검증 큐 | 상우 (선택적으로 읽음), 주간 합성의 입력 |
| 매주 일 17:30 시작(19:30 완료) | **거미줄 리포트** + 데이터 품질 스코어카드 (md + 차트 + 그래프 스냅샷) | 상우, 블로그 초안 |
| 매월 1일 | **월간 회고** (논제 채점, 출처 신뢰도 갱신, 투자일기용 '거시 배경' 요약) | 상우, 투자일기 |

### 1.3 비목표 (🚫)

- 매수·매도 지시, 종목 추천, 환헤지/환노출 권고 → **하지 않는다.** 판단 재료(고평가/적정/저평가의 근거)와 "무엇을 확인해야 하는가"만 제공한다.
- 초단기 속보 경쟁, 틱 단위 가격 추적 → 하지 않는다. 기존 `investment-monitor`가 가격·환율 알림을 담당한다.
- 모든 뉴스를 다 읽는 것 → 하지 않는다. **거미줄에 걸리는 뉴스**(엔티티·관계·논제에 연결되는 뉴스)만 깊게 본다.

### 1.4 성공 기준 (12주 후 측정)

1. 주간 리포트 12회 **무중단 자동 발행** (launchd 실패 0회 또는 자동 복구).
2. 논제 원장(Thesis Ledger): **예측시장·FedWatch 가격이 있는 논제는 시장 내재확률의 Brier 대비 +0.02 이내**(시장을 이기는 건 비현실적이고, 시장만큼 보정됐는지가 진짜 기준), 시장 가격이 없는 논제는 Brier ≤ 0.20. (0.25는 매번 50%라고 말하는 것과 같은 점수라 목표가 될 수 없다.)
3. 가짜·과장 뉴스 평가셋 F1 ≥ 0.85.
4. 지식 그래프 노드 ≥ 1,000 / 엣지 ≥ 5,000, **엣지의 근거(evidence) 링크 100%**.
5. 월간 투자일기에 "이달의 거시 배경"(주간 리포트 4개 압축)이 자동 삽입됨.
6. 상우가 리포트를 읽고 "왜"를 설명할 수 있는 사건의 비율 ↑ (주관 점수, `review/feedback.yaml`에 주 1회 기록).

### 1.5 지금 이 순간의 맥락 시드 (2026-11-01 기준 — 전부 ⚠️, 첫 리포트의 재료)

하네스는 아래를 **사실로 쓰지 말고 검증 대상 claim으로 등록**한다. 이것이 검증 레이어의 첫 번째 실전 테스트다.

| 영역 | 2026-11-01 기준 관찰 (출처 재확인 필요) | 거미줄에서 볼 연결 |
|---|---|---|
| 연준 | 의장 **케빈 워시(Kevin Warsh)**. 9/16 FOMC 25bp **인상**(3.75–4.00%), 워시 "인플레 너무 높고 너무 오래". 10/28 FOMC **동결**, 10:2 (쿡·해맥 인상 주장). 9월 의사록 "연내 추가 인상". 시장은 12/9 인상 가능성 저울질. 트럼프의 인하 압박을 워시가 공개 거부 | 워시 성향(매파·독립성 과시) ↔ 트럼프 인센티브(중간선거·재정) ↔ 장기금리 ↔ 성장주 밸류에이션 ↔ AI 반도체 |
| 물가 | 10/15 PPI 4년래 최대 상승. 이란 전쟁·호르무즈 리스크가 유가 경로에 걸림 | 유가 → 헤드라인 물가 → 연준 → 달러 → 원화 |
| 중간선거 | **11/3(화) 미국 현지, 한국은 11/4 오전 개표.** 하원 민주당 우세, 상원은 공화 수성 여부(7대 경합주). 현재 상원 53:47, 하원 218:214 공화. 트럼프 "상하원 모두 어렵다" 인정. 한국은행이 10/16 중간선거 쟁점 보고서 발간 | 의회 구도 → 재정(감세·관세·부채한도) → 국채 발행 → 장기금리; 연준 독립성 공방; 대한국 통상·파병 요청 |
| 지정학 | 이란 전쟁 진행 중. 트럼프 "중간선거 전엔 이란 공격 안 한다", 선거 직후 종전 공언. 한국에 파병 요청 | 선거 후 군사 행동 재개 가능성 → 유가·방산·원화 |
| AI 반도체 | 연중 반복 조정: 6월 브로드컴 AI 매출 가이던스 쇼크(SOX 하루 −10%대) → 6월 마이크론·샌디스크 −13% → 7월 알파벳 capex↑/FCF↓ 재평가, 문샷 Kimi K3 저비용 오픈웨이트, 모건스탠리 "데이터센터 지연·취소" → 구글 TurboQuant(KV캐시 압축)로 메모리 수요 우려 → 10/16–17 나스닥 이틀 −2.85%, 'W' 반등 분기점 논쟁. 삼성·하이닉스 10%대 급락일 존재 | AI capex 지속성(하이퍼스케일러 FCF) → HBM/DRAM 가격 → SK하이닉스·삼성 → KOSPI → 외국인 수급 → 원화. 효율화 기술(저비용 모델, KV캐시 압축)은 메모리 수요의 반대 세력 |
| 한국 | KOSPI 6000대 국면(증권사 밴드 6300–7300 언급 사례). 반도체 비중 극단. 외국인 수급이 지수 방향 | 미국 장기금리·달러 → 외국인 → KOSPI; 반도체 피크아웃 논쟁 |
| 크립토 | BTC 8만 달러대 (고점 대비 조정) | 유동성·위험선호 온도계로만 사용 |

---

## 2. 설계 원칙 10가지

1. **스크래핑이 뿌리다.** 모든 정보는 URL + 수집시각 + 원문 해시 + raw 스냅샷을 가진다. 재현 불가능한 정보는 없는 정보다.
2. **사실 / 해석 / 추측 3단 분리.** 리포트의 모든 문장은 `[F]`(검증된 사실) `[I]`(해석) `[S]`(추측) 태그를 내부적으로 가진다. 발행본에서는 추측 문장에 "~일 가능성" 류의 명시적 헤지 + 확률.
3. **1차 출처가 2차를 이긴다.** 연준 성명·공시·통계 원문 > 통신사·주요지 > 전문 블로그 > 커뮤니티·SNS. 하위 출처가 상위 출처와 충돌하면 상위가 맞다고 가정하되 **충돌 자체를 기록**한다.
4. **반증 가능해야 인사이트다.** 모든 논제는 (기간, 확률, 틀렸을 때 보일 신호)를 가진다. 채점 불가능한 문장은 논제가 아니다.
5. **뉴스는 노드가 아니라 엣지다.** 기사 하나를 저장하는 게 목적이 아니라 "누가 → 무엇을 → 누구에게 → 왜"의 관계를 갱신하는 게 목적이다. 이익관계(benefits_from / hurt_by)가 핵심 엣지.
6. **인물에는 인센티브가 있다.** 발언을 해석할 때 직책·임기·재임명·선거·후원자·과거 트랙레코드를 같이 본다. "매파 발언"이 아니라 "임기 1년차 의장이 독립성을 증명해야 하는 국면의 매파 발언".
7. **한국 투자자의 렌즈.** 원화 환산, 환헤지 비용, 한미 금리차, 외국인 수급, 반도체 비중, 미국 장과의 시차(한국 아침 = 미국 마감)를 기본값으로 둔다.
8. **싸게 많이, 비싸게 적게.** 추출·분류는 소형 모델(배치), 종합·토론은 대형 모델. 임베딩·번역은 로컬(M1 Max).
9. **하네스 우선.** 사람이 손으로 하는 단계가 0이어야 자동화다. 검토 큐는 "읽으면 좋은 것"이지 "읽어야 돌아가는 것"이 아니다.
10. **점진 구축, 2주 내 첫 리포트.** Phase 1~2에서 조악해도 돌아가는 주간 리포트를 낸다. 거미줄은 그 위에서 자란다.

---

## 3. 전체 아키텍처

### 3.1 파이프라인 (한 장 요약)

```
                 ┌──────────────── launchd (macOS) ────────────────┐
                 │  */30m: collect-tick   07:00: daily   Sun 17:30: weekly   1st: monthly  │
                 └──────────────────────────────────────────────────┘
                                          │
  ┌───────────── TRACK A: 결정론적 Python 파이프라인 (매일, 저비용) ─────────────┐
  │                                                                              │
  │  L1 수집  →  L2 정규화/중복제거  →  L3 추출(claims/entities/relations)      │
  │  (RSS/HTML/API/Playwright)   (Story 클러스터, 번역, 임베딩)   (소형 모델·배치)  │
  │        │                                                                     │
  │        ▼                                                                     │
  │  L4 검증 (신뢰도·교차검증·1차출처 역추적·수치검증·루머 생명주기·언어신호)       │
  │        │  → claim.confidence / label, 격리(quarantine), 검토 큐(review/)       │
  │        ▼                                                                     │
  │  L5 거미줄 갱신 (엔티티 해소, 엣지 추가/강화/만료, evidence 링크)               │
  │        ▼                                                                     │
  │  일일 다이제스트 (10줄) + 그래프 스냅샷 + 지표 수집(가격·금리·환율·DRAM)         │
  └──────────────────────────────────────────────────────────────────────────────┘
                                          │  (주 1회)
  ┌───────────── TRACK B: 에이전트 하네스 (매주, 고품질) ────────────────────────┐
  │  L6 분석 엔진 (테마 모멘텀·레짐·캘린더·충격 전파·교차자산 정합성·역사 유사)    │
  │        ▼                                                                     │
  │  멀티에이전트 합성:                                                            │
  │    analysts(macro/policy/semis/korea) ∥ cartographer ∥ historian              │
  │        → chief-editor 논제 초안 → ping-pong 레드팀 3라운드 → judge            │
  │        → writer-ko → fact-checker GATE (실패 시 발행 차단) → chart-maker       │
  │        ▼                                                                     │
  │  L7 발행: reports/YYYY-WW.md + charts/ + vault/weekly/ + 텔레그램 + 블로그 초안 │
  └──────────────────────────────────────────────────────────────────────────────┘
                                          │  (월 1회)
  ┌───────────── TRACK C: 학습 루프 ─────────────────────────────────────────────┐
  │  L8 평가: 논제 Brier 채점 · 출처 적중률 → credibility 갱신 · 검증기 eval      │
  │          · 그래프 정리(만료 엣지) · 투자일기용 '거시 배경' 생성                 │
  └──────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 왜 두 트랙인가

- **Track A(매일)**는 launchd 아래에서 **에이전트 없이** 돌아야 한다. 에이전트가 매일 헤매면 비용·신뢰성 둘 다 무너진다. Python + Anthropic SDK 직접 호출(JSON 스키마 강제), 배치 API로 추출.
- **Track B(매주)**는 판단이 필요한 구간이라 **에이전트가 맞다.** 서브에이전트 분업, 토론, 게이트. 주 1회라 비용을 감당할 수 있다.
- **Track C(매월)**는 시스템이 스스로 나아지는 유일한 길. 생략하면 6개월 뒤 똑같은 실수를 반복하는 기계가 된다.

### 3.3 저장소

| 저장 | 기술 | 내용 |
|---|---|---|
| 관계형 | SQLite (WAL) `data/db/macroweb.sqlite` | articles, stories, claims, entities, relations, evidence, theses, runs, source_stats |
| 벡터 | sqlite-vec 또는 FAISS `data/vectors/` | story 임베딩(bge-m3, 로컬), 엔티티 설명 임베딩, 과거 리포트 임베딩 |
| 전문검색 | SQLite FTS5 | 기사·claim 본문 |
| 원문 | `data/raw/YYYY/MM/DD/<sha256>.html.gz` (+ `.meta.json`) | 스냅샷. 90일 후 압축 보관, 1년 후 삭제(ADR) |
| 그래프 뷰 | `vault/` (Obsidian 호환 md) | 엔티티 1노드 = 1파일, wikilink = 엣지, 주간 스냅샷 |
| 산출물 | `reports/`, `charts/`, `digests/` | git 추적 |
| 비공개 | `private/` (gitignore) | portfolio.yaml, API 키(.env), 텔레그램 토큰 |

---

## 4. L1 수집 (Collection)

### 4.1 소스 계층과 신뢰도 prior

| Tier | 정의 | prior | 수집 방식 | 예 |
|---|---|---|---|---|
| T0 | 1차 출처: 발표 주체 본인 | 0.95 | API/RSS/PDF | 연준·BLS·BEA·재무부·SEC EDGAR·한은 ECOS·DART·KRX·기업 IR·중앙은행 |
| T1 | 통신사·주요 경제지 | 0.80 | RSS/HTML(제목·리드) | Reuters(구글뉴스 경유)·AP·Bloomberg(헤드라인)·FT·WSJ·Nikkei Asia·연합뉴스·한경·매경·조선비즈 |
| T2 | 전문 분석·업계지 | 0.65 | HTML/RSS | SemiAnalysis·TrendForce·Digitimes·Tom's Hardware·Calculated Risk·증권사 리서치 요약 |
| T3 | 예측시장·데이터 집계 | 0.70 (가격은 사실, 해석은 아님) | API | Polymarket·Kalshi·CME FedWatch·CFTC COT |
| T4 | 커뮤니티·SNS·개인 블로그 | 0.30 | JSON/HTML | Reddit·HN·네이버 종토방(심리 온도계만) |
| T5 | 미분류·신규 도메인 | 0.15 | — | 자동 격리 |

prior는 §12의 학습 루프로 **소스별로 갱신**된다(적중 시 +, 정정·반박 시 −).

### 4.2 초기 소스 레지스트리 (`config/sources.yaml`) — 1차 50개

⚠️ URL은 하네스가 첫 세션에서 모두 실제 요청으로 검증하고 죽은 것은 교체한다.

**미국 거시·정책 (T0)**
- 연준 보도자료/성명/연설 RSS (`federalreserve.gov/feeds/*`), FOMC 캘린더 페이지, 의사록 PDF
- FRED API (키 무료): DFF, DGS2, DGS10, T10Y2Y, CPIAUCSL, PCEPILFE, PAYEMS, UNRATE, DTWEXBGS(달러지수), WALCL(연준 자산), RRPONTSYD, WTREGEN(TGA), BAMLH0A0HYM2(HY 스프레드), VIXCLS
- BLS/BEA 발표 일정 페이지, 재무부 FiscalData API(국채 발행·TIC), Treasury 입찰 결과
- SEC EDGAR: 8-K/10-Q 전문검색 API(User-Agent 필수) — NVDA, AMD, AVGO, MU, TSM, ASML, MSFT, GOOGL, AMZN, META, ORCL
- White House 성명, Congress.gov(법안), CBO 전망, FEC(정치자금 — 인물 카드용)
- 예측시장: Polymarket Gamma API, Kalshi API(중간선거·금리·관세 시장), CME FedWatch(Playwright)
- CFTC COT(주간 포지션)

**한국 (T0)**
- 한국은행 ECOS API(기준금리·환율·금통위 일정), 금통위 의사록, 기재부 보도자료
- DART Open API(삼성전자·SK하이닉스·어보브반도체 등 공시), KRX 투자자별 매매동향(외국인), KOSIS
- 산업부·관세청 수출입(반도체 수출)

**글로벌 중앙은행·기관 (T0)**: ECB, BOJ, PBoC, IMF(WEO/연례총회), BIS, OPEC

**기업 IR (T0)**: NVIDIA·AMD·Broadcom·Micron·TSMC(월매출!)·ASML·삼성전자·SK하이닉스·Microsoft·Alphabet·Amazon·Meta·Oracle — 실적 PDF, 컨퍼런스콜 트랜스크립트(IR 페이지 또는 Motley Fool HTML)

**언론 (T1)**: Google News RSS 토픽 검색(`news.google.com/rss/search?q=…`)으로 Reuters/Bloomberg/FT/WSJ 헤드라인 확보 · 연합뉴스 경제 RSS · 한국경제 RSS · 매일경제 RSS · 조선비즈 RSS · Nikkei Asia(헤드라인) · CNBC RSS · MarketWatch RSS

**전문 (T2)**: SemiAnalysis(무료 공개분) · TrendForce 프레스센터(DRAM/NAND 계약가) · DRAMeXchange 스팟(공개 부분) · Digitimes(헤드라인) · Tom's Hardware RSS · The Register RSS · Ars Technica RSS · Calculated Risk · 증권사 리서치 공개 요약(한경 컨센서스 등)

**심리 (T4)**: Reddit JSON(r/stocks, r/wallstreetbets, r/semiconductors), HN Algolia API, 네이버 종목토론(삼성전자·하이닉스 — 게시글 수·감성만 집계, 본문 저장 안 함)

**가격·지표 (T3, 수치)**: FinanceDataReader(국내), Stooq CSV(글로벌 지수 백업), KRX, 환율(ECOS), 금·유가(FRED/Stooq), BTC(공개 API)

### 4.3 수집기 설계

```
src/macroweb/collect/
  registry.py        # sources.yaml 로드/검증(pydantic)
  fetchers/
    rss.py           # feedparser + ETag/Last-Modified 캐시
    html.py          # httpx + selectolax; trafilatura로 본문 추출
    api.py           # FRED/ECOS/DART/EDGAR/Polymarket 어댑터
    playwright_.py   # JS 렌더 페이지(CME FedWatch 등), 헤드리스 Chromium
    pdf.py           # 연준 의사록/IR PDF → 텍스트(pdfplumber)
  politeness.py      # robots.txt, 도메인별 토큰버킷, 백오프, UA 정책
  snapshot.py        # raw 저장(gzip) + meta(url, status, fetched_at, sha256, etag)
  dedupe.py          # URL 정규화(utm 제거, AMP→canonical), SimHash, 임베딩 유사도
```

규칙:
- 소스 1개 = 어댑터 1개 + 픽스처 1개 + 골든 테스트 1개. 어댑터 없이 소스를 추가하지 않는다.
- 실패는 **격리**된다: 소스 A가 죽어도 B~Z는 수집된다. 3회 연속 실패 소스는 `source_stats.health=degraded`로 표시하고 일일 다이제스트에 한 줄 보고.
- 유료 벽: 제목·리드·발행시각·URL만 저장. 본문 추출 시도 금지(🚫).
- 언어: `lang` 자동 감지(langdetect/fasttext). 한/영 외 언어는 제목만.
- 중복: ① URL 정규화 ② 제목 SimHash 해밍거리 ≤ 3 ③ 본문 임베딩 코사인 ≥ 0.92 → 같은 **Story**로 묶는다. 통신사 전재(연합→각 매체)는 Story는 같되 **독립 출처로 세지 않는다**(§7.2).

### 4.4 수집 주기와 launchd

| 잡 | 라벨 | 주기 | 내용 | 예산 |
|---|---|---|---|---|
| collect-tick | `com.sawoo.macroweb.collect` | StartInterval 1800 (30분) | 스케줄러가 기한 도래 소스만 수집(§0.3 적응 주기), 신규 Story는 롤링 배치 제출 | ~1분 |
| daily | `com.sawoo.macroweb.daily` | StartCalendarInterval 07:00 | 배치 회수 + 미완료분 실시간 처리 → L4·L5 + 다이제스트 | ~15분, 07:30 전 완료 |
| weekly | `com.sawoo.macroweb.weekly` | 일 17:30 | 품질 검토 Step 0 → Track B | ≤ 2시간, 19:30 전 완료 |
| monthly | `com.sawoo.macroweb.monthly` | 매월 1일 08:00 | Track C | ~20분 |

launchd 주의점(부록 H에 plist):
- `~/Library/LaunchAgents/`에 설치, `launchctl bootstrap gui/$(id -u) <plist>`.
- 잠자는 Mac은 launchd가 깨우지 못한다 → `sudo pmset repeat wakeorpoweron MTWRFSU 06:55:00` 또는 "전원 연결 시 잠들지 않음" 설정. 잠든 사이 놓친 `StartCalendarInterval` 잡은 깨어난 직후 1회 실행되므로 **idempotent**가 필수.
- 래퍼 스크립트에서 `caffeinate -i` 로 실행 중 잠듦 방지, 절대경로·PATH 명시, 로그는 `logs/<job>.{out,err}.log`, 종료코드 ≠ 0이면 `osascript` macOS 알림 + 텔레그램.
- Playwright 브라우저는 로그인 세션 없이, 헤드리스로만.

### 4.5 소스 추가 절차 (스킬 `add-source`)

1. `sources.yaml`에 항목 추가(§부록 B 스키마) → 2. `macroweb source probe <id>`로 실제 요청·파싱 확인 → 3. 응답을 `tests/fixtures/<id>/`에 저장 → 4. 골든 테스트 작성 → 5. `make doctor` 통과 → 6. 커밋.

---

## 5. L2 정규화·저장

### 5.1 핵심 스키마 (요약 — 전체 DDL은 부록 A)

- `article(id, url, canonical_url, source_id, title, author, published_at, fetched_at, lang, text, text_ko, text_en, raw_path, sha256, paywalled, status)`
- `story(id, first_seen, last_seen, title_rep, n_articles, n_independent_sources, theme_ids[], embedding_id)`
- `story_article(story_id, article_id, is_syndicated_copy)`
- `claim(id, story_id, text, type{numeric,event,quote,forecast,attribution}, subject_eid, predicate, object_eid, value, unit, time_ref, confidence, label, first_seen, last_updated)`
- `evidence(id, claim_id, article_id, span_start, span_end, kind{supports,contradicts,primary_doc,data_api})`
- `entity(id, type, canonical_name, aliases[], wikidata_qid, country, sector, profile_json, valid_from, valid_to)`
- `relation(id, src_eid, dst_eid, type, sign{+1,-1,0}, weight, confidence, valid_from, valid_to, evidence_ids[], last_reinforced)`
- `thesis(id, week, text, horizon_date, probability, falsifier, status, outcome, brier)`
- `run(id, job, started_at, ended_at, status, stats_json, cost_tokens_in, cost_tokens_out)`
- `source_stats(source_id, credibility, n_claims, n_confirmed, n_refuted, health, updated_at)`

### 5.2 번역·임베딩 (로컬, M1 Max)

- 임베딩: `bge-m3`(다국어) — sentence-transformers, MPS. Story당 1벡터(제목+리드), 엔티티 설명 벡터, 주간 리포트 벡터(역사 유사 검색용).
- 번역: 영문 기사 → 한국어 요약은 LLM 추출 단계에서 함께 생성(별도 번역 호출 없음). 원문 보존.
- FTS5: 한국어는 trigram 토크나이저 사용.

---

## 6. L3 추출 (Claims · Entities · Relations)

### 6.1 추출 계약 (Story 1개 → JSON 1개)

입력: Story의 대표 기사 본문(≤ 6k 토큰) + 출처 메타. 출력(JSON 스키마 강제, pydantic 검증, 실패 시 1회 재시도 후 격리):

```json
{
  "summary_ko": "3문장 이내",
  "claims": [
    {"text": "...", "type": "numeric|event|quote|forecast|attribution",
     "subject": "Kevin Warsh", "predicate": "stated", "object": "inflation too high",
     "value": null, "unit": null, "time_ref": "2026-09-16",
     "cited_primary_doc": "FOMC statement 2026-09-16" , "anonymous_source": false}
  ],
  "entities": [{"name": "Kevin Warsh", "type": "person", "role_hint": "Fed Chair"}],
  "relations": [
    {"src": "Trump", "dst": "Fed", "type": "pressures", "sign": -1, "quote_span": "..."},
    {"src": "rate hike", "dst": "growth stocks", "type": "hurts", "sign": -1}
  ],
  "cui_bono": [{"entity": "...", "effect": "benefits|hurt", "why": "..."}],
  "sentiment": {"market": -0.4, "policy_hawkish": 0.7},
  "novelty_hint": "new|update|recycled",
  "red_flags": ["sensational_headline", "no_named_author"]
}
```

### 6.2 모델 라우팅 — 소스는 출발점, 기준은 "잘못 읽었을 때의 비용"

모델 선택의 기준은 소스 이름이 아니라 **그 문서를 잘못 읽었을 때 리포트가 입는 피해**다. 소스 유형은 그 피해를 미리 짐작하는 첫 단서로 쓰고, 문서 내용이 위험 신호를 보이면 위로 올린다(승급). 가장 큰 절약은 "LLM을 아예 안 쓰는 경로"를 넓히는 데서 나온다.

#### 6.2.1 기본 배정 (가설 — §6.2.4 실험으로 확정)

| 층(stratum) | 소스 예 | 어려움의 성격 | 기본 처리 |
|---|---|---|---|
| S-DATA | FRED·ECOS·KRX·Polymarket·Kalshi·CFTC | 이미 구조화된 숫자 | **LLM 없음.** 파서 → `market`/`claim(type=numeric, label=VERIFIED)` |
| S-T0-STMT | FOMC 성명, 금통위 의결문, 기업 가이던스 문구 | 직전 문서 대비 단어 변화가 곧 뉴스 | **diff 우선**(§6.2.3) → 바뀐 문장만 Sonnet급 |
| S-T0-LONG | FOMC 의사록, 연준·한은 인사 연설, 실적 콜 트랜스크립트, 10-Q/8-K, CBO | 길고, 헤지 표현·조건문이 많음 | **Sonnet급 배치.** 월 4–6건(의사록, 하이퍼스케일러·엔비디아·하이닉스 실적 콜)만 Opus급 |
| S-T1 | 통신사·경제지 (영문) | 짧고 정형화, 같은 사건을 여러 곳이 씀 | **Haiku급 배치** |
| S-T1-KO | 한국 경제지 | 억/조 단위, '외신 종합'(원출처 누락), 증권가 인용 | **Haiku급 배치**, 측정 결과 약하면 Sonnet급 (가장 의심되는 층) |
| S-T2 | TrendForce·SemiAnalysis·Digitimes | 수치 밀도 높음, 계약가/현물가·QoQ/YoY 혼동 | Haiku급 + 수치 검증 실패 시 승급 |
| S-T4 | Reddit·HN·종토방 | 내용보다 "얼마나 떠드는가" | **LLM 없음.** 건수·키워드·임베딩. 루머가 고영향 테마에 걸릴 때만 Haiku급 |
| S-ER | 엔티티 해소 애매 케이스 | 동명이인·역할 변경 | Sonnet급 배치, 일 ≤ 20건 |

#### 6.2.2 승급 규칙 (한 단계 위 모델로 재추출)

1. JSON 스키마 검증 실패(1회 재시도 후에도)
2. 수치 claim이 데이터 API 값과 허용 오차 밖 — 모델이 잘못 읽었는지 기사가 틀렸는지 가르기 위해 재추출. 재추출도 같은 값이면 **기사 쪽 문제**로 판정(검증 신호 4로 넘김)
3. 영향도(impact) ≥ 0.7 이면서 출처 간 충돌(DISPUTED)
4. 인물 카드의 핵심 인물(`config/key_persons.yaml`: 연준 의장·FOMC 투표권자, 미 대통령·재무장관, 한은 총재, 빅테크·메모리 3사 CEO 등) **직접 발언**
5. T4 루머가 고영향 테마에 연결될 때 (LLM 없음 → Haiku급)

일일 승급 상한 8건(초과분은 impact 순으로 다음 날 이월). 승급 결과는 `claim.extracted_by`와 `claim.escalation_reason`에 남긴다.

#### 6.2.3 T0 diff 우선 처리

성명·의결문·가이던스처럼 "같은 틀의 문서가 반복되는" 1차 문서는 모델에게 통째로 읽히지 않는다.

```
1. 직전 같은 종류 문서를 DB에서 꺼냄 (예: 2026-09-16 FOMC 성명 ↔ 2026-10-28 성명)
2. 문장 단위 정렬 + difflib → 추가/삭제/변경 문장 목록 (결정론적)
3. 변경 문장만 Sonnet급에: "이 변화는 매파적/비둘기파적/중립인가, 근거 단어는?" + 투표 결과·소수의견 추출
4. 결과 = claim(type=event, label=VERIFIED, evidence=primary_doc) + 인물 카드 성향 벡터 갱신 후보
```

모델이 긴 문서에서 미묘한 변화를 놓치는 위험을 없애고, 비용도 문서 전체 대비 10% 안팎으로 줄인다. 연준·한은 인사 연설도 같은 인물의 직전 연설과 핵심 문단을 비교한다.

#### 6.2.4 측정 실험 — 배정을 확정하는 법 (Phase 2)

- 층마다 Story 20개 (S-T1, S-T1-KO, S-T2, S-T0-LONG, 승급 후보 표본 = 5개 층 × 20 = 100개)
- 각 Story를 Haiku급·Sonnet급 둘 다로 추출. 정답 라벨: 층당 10개는 상우가 직접, 나머지 10개는 Opus급 추출을 정답으로 쓰고 상우가 3개만 스팟 체크
- 지표: claim F1(주어·술어·값 매칭), 수치 오류율, 관계 부호(+/−) 오류율, Story당 비용
- **판정 규칙:** claim F1 격차 ≥ 0.10 또는 수치 오류율 격차 ≥ 5%p인 층만 상위 모델 배정
  - 0.10의 근거: 층당 20 Story ≈ claim 80개에서 F1 표준오차가 대략 0.05라, 0.10은 약 2σ — 우연이 아닌 차이
  - 5%p의 근거: 주간 리포트 수치 문장 ≈ 40개 중 2개 이상이 틀릴 수준
- 결과는 ADR-00xx(모델 배정)로 고정하고 `config/models.yaml`의 `routing:` 섹션에 반영

#### 6.2.5 감사 샘플 — 모델 차이가 출처 신뢰도를 오염시키지 않게

문제: T0는 Sonnet급, T1은 Haiku급이 읽으면 "출처가 부정확한 것"과 "싼 모델이 잘못 읽은 것"이 섞인다. 그대로 두면 출처 신뢰도(§12)가 모델 차이를 출처 탓으로 돌린다.

- 매주(§10.5 Q7) 층별 Story 10개(S-T1, S-T1-KO, S-T2, 승급분, T4 루머 승급분 = 50개)를 **기준 모델(Sonnet급, 고정)**로 다시 추출. S-T0-LONG은 월 5건을 Opus급으로 감사
- 층별 **추출 오류율 e** = 기준 모델 대비 claim 불일치율 (4주 이동평균)
- 출처 신뢰도 갱신 시 반박(refuted) 1건의 가중치를 `1 − e(그 claim의 층)`으로 할인 → 모델 탓일 확률만큼 출처 감점을 줄인다
- e가 0.15를 넘는 층(측정 오차 2σ 이상의 의미 있는 악화로 시작 설정, §0.4로 보정)은 다음 달 라우팅 재판정 대상

#### 6.2.6 운영 규칙

- 모델명·단가는 `config/models.yaml`에만. 코드 하드코딩 🚫
- 모든 claim에 `extracted_by`(모델 등급+프롬프트 버전) 기록 → 감사·재처리 가능
- 모델 교체(새 버전 출시) 시: 측정 실험을 축소판(층당 10개)으로 다시 돌린 뒤 교체. 교체 전후 2주는 감사 샘플을 2배로

### 6.3 프롬프트 관리

- `prompts/<name>/v<N>.md` + `prompts/<name>/CHANGELOG.md`. 프롬프트 변경 = 버전 증가. `run` 테이블에 프롬프트 버전 기록.
- 추출 품질 평가셋: `eval/extraction/` 30개 Story(한/영 반반)에 사람이 라벨한 claims. 프롬프트 변경 시 `make eval-extract` 필수.

---

## 7. L4 검증 — 가짜·과장·재탕 정보 필터

### 7.1 설계 철학

"가짜 뉴스 탐지기"가 아니라 **claim 단위의 신뢰도 추정기**다. 기사 전체를 참/거짓으로 자르지 않고, 기사 안의 개별 주장(claim)마다 신호를 모아 confidence(0–1)와 label을 매긴다. 라벨:

| label | 의미 | 리포트 사용 |
|---|---|---|
| `VERIFIED` | 1차 출처 원문 또는 데이터 API와 직접 일치 | 사실 `[F]` |
| `CORROBORATED` | 독립 출처 ≥ 2 (전재 제외) 일치, 1차 출처 미확인 | 사실 `[F]` (출처 병기) |
| `SINGLE_SOURCE` | 출처 1개 | 해석 `[I]`로만, "보도에 따르면" 명시 |
| `DISPUTED` | 출처 간 충돌 | 충돌 자체를 보고 (양쪽 병기) |
| `DEBUNKED` | 공식 정정·반박 존재 | 🚫 본문 사용 금지. "검증 노트"에 교육용으로만 |
| `UNVERIFIABLE` | 검증 경로 없음(익명 소스 전망 등) | 추측 `[S]` + 확률 |
| `RECYCLED` | 과거 사건의 재탕 | 🚫 (단, "다시 도는 이유"가 인사이트면 언급) |
| `SPAM_SATIRE` | 풍자·광고·리딩방·봇 | 🚫 격리 |

### 7.2 신호 12개

| # | 신호 | 계산 | 가중 방향 |
|---|---|---|---|
| 1 | 출처 prior | `source_stats.credibility` (Tier 초기값 → 학습) | + |
| 2 | **독립 교차검증** | Story 내 독립 출처 수. 독립 = 모회사 다름 + 본문 유사도 < 0.8(전재 제외) + 서로 인용 관계 아님 | + (log scale) |
| 3 | **1차 출처 역추적** | claim이 문서(성명·공시·통계)를 인용하면 그 문서를 fetch해 수치/문장 존재 여부 확인(정규식+LLM 대조) | ++ (일치) / −− (불일치) |
| 4 | **수치 검증** | numeric claim을 FRED/ECOS/KRX/AV 값과 자동 비교(허용 오차 표) | ++ / −− |
| 5 | 시간 일관성 | 발행시각 vs 사건시각; 과거 Story와 임베딩 유사 ≥ 0.9 & 90일 이상 전 → RECYCLED 후보 | − |
| 6 | 언어 신호(LLM 루브릭) | 선정적 제목, 과장 수사, 익명 소스 비율, 저자 없음, 숫자 없는 단정, 긴급성 유도 | − |
| 7 | 도메인 위험 | 등록 ≤ 180일, 유명 매체 유사 도메인(typosquat), HTTPS 없음, 광고 밀도 | − |
| 8 | **루머 생명주기** | T4에서 최초 등장 후 1 영업일 내 T0/T1 확인 없음 → 감점; 2 영업일 후에도 없음 → UNVERIFIABLE 고정 (§0.4에서 실측 보정) | − |
| 9 | 정정·반박 감시 | 기업 IR 부인, 거래소 조회공시 답변, 연준/정부 해명, 팩트체크 기관(SNU팩트체크·Reuters/AP/AFP Fact Check) | DEBUNKED 트리거 |
| 10 | 시장 반응 정합성 | "X가 급등"류 claim을 가격 데이터와 대조; 큰 뉴스인데 관련 자산 무반응이면 플래그(가짜이거나 이미 반영) | ± |
| 11 | 생성 콘텐츠 신호 | 동일 문장 템플릿의 다수 도메인 동시 게시, 이미지 메타 없음, AI 생성 이미지 표기 | − |
| 12 | 레드팀 토론(선택) | 고영향·저신뢰 claim에 한해 `ping-pong`: 검사(Prosecutor) vs 변호(Defender) 3라운드 → 판사 | 최종 보정 |

점수식(초기값, §12에서 로지스틱 회귀로 재학습):

```
logit(conf) = 1.2·prior + 0.9·log1p(n_independent) + 1.5·primary_match + 1.5·numeric_match
            − 0.8·recycled − 0.7·language_risk − 1.0·domain_risk − 0.6·rumor_stale
            + 0.3·market_consistency − 2.0·debunked
label = rule(conf, flags)   # 예: debunked → DEBUNKED 우선, primary_match=1 → VERIFIED
```

### 7.3 게이트 정책 (발행 차단 규칙)

- 주간 리포트 본문 `[F]` 문장은 `VERIFIED | CORROBORATED` claim_id를 **반드시** 참조한다. fact-checker 에이전트가 참조 없는 `[F]`를 발견하면 발행 실패(exit≠0).
- `DEBUNKED`·`SPAM_SATIRE`·`RECYCLED`는 본문 금지, 검증 노트에만.
- 고영향(§9.1 impact ≥ 0.7) + 저신뢰(conf < 0.5) claim은 `review/YYYY-MM-DD.md`에 올리고 사람이 `approve|reject|unsure`를 적으면 `source_stats`와 학습셋에 반영. 사람이 안 읽어도 파이프라인은 돈다(§2-9).

### 7.4 알려진 함정 목록 (`config/traps.yaml`로 관리)

- 풍자·패러디 사이트, 리딩방·작전 텔레그램 지라시, 유튜브 썸네일 뉴스
- "소식통에 따르면"만 있는 정책 루머(특히 관세·금리·공시 전 M&A)
- 과거 차트·기사 재유통(날짜 잘린 캡처), 실적 '서프라이즈' 수치의 단위 혼동(QoQ vs YoY, 억/조)
- CEO·연준 인사 발언의 딥페이크·오역(원문 영상/성명과 대조)
- 예측시장 수치를 '사실'로 보도하는 기사(확률은 사실, 결과는 아님)
- 한국 기사의 '외신 종합' — 원문 링크 없으면 SINGLE_SOURCE 처리
- 하이퍼스케일러 capex '전망치'를 '확정치'로 쓰는 기사

### 7.5 평가셋과 학습

- `eval/verify/`: 200개 claim(참 100 / 거짓·과장·재탕 100), 출처: 팩트체크 기관 아카이브 + 과거 실제 정정 사례 + 합성 케이스(날짜 바꾼 재탕 등). 라벨러는 상우 + 하네스(이중 라벨, 불일치만 사람 확정).
- 매월 `make eval-verify` → precision/recall/F1 by label. 목표 F1 ≥ 0.85.
- 가중치 재학습은 월 1회만(Track C). 주중에 바꾸지 않는다.

### 7.6 교육 효과 — "검증 노트"

주간 리포트의 '검증 노트' 섹션은 그 주에 걸러낸 가짜·과장·재탕 3건과 **어떤 신호로 걸렀는지**를 적는다. 이것이 감각 훈련이다. 6개월 뒤 상우가 기사 제목만 보고 "이건 재탕이네"가 되는 게 목표.

---

## 8. L5 거미줄 — 관계 그래프 (Knowledge Graph)

### 8.1 온톨로지

**노드 타입**

| 타입 | 예 | 핵심 속성 |
|---|---|---|
| `person` | Kevin Warsh, Trump, Jensen Huang, 이창용 | 직책, 임기(from/to), 성향 벡터(§8.3), 인센티브, 트랙레코드 |
| `org` | Fed, Treasury, NVIDIA, SK하이닉스, Moonshot AI, Morgan Stanley, 한국은행 | 유형(central_bank/company/agency/bank/think_tank/fund), 국가, 섹터 |
| `country_bloc` | US, CN, KR, TW, EU, 이란, OPEC+ | — |
| `policy` | 관세(품목별), 반도체 수출통제, CHIPS Act, 감세안, 연준 QT | 상태(proposed/enacted/expired), 결정권자 |
| `asset` | NVDA, SOX, UST10Y, USDKRW, DRAM 계약가, HBM, 유가, BTC | 데이터 소스 키 |
| `product_tech` | GPU(Blackwell/Rubin), HBM4, CoWoS, KV캐시 압축(TurboQuant), 오픈웨이트 모델(Kimi K3) | 세대, 공급사 |
| `event` | FOMC 2026-12-09, 중간선거 2026-11-03, NVDA 실적, 삼성 실적, 이란 휴전 | 일시, 확정/예정, 결과 |
| `theme` | AI capex 지속성, 연준 독립성, 메모리 슈퍼사이클, 달러 약세, 한국 파병 | 모멘텀 지표(§9.1) |
| `indicator` | CPI, PPI, NFP, PCE, 반도체 수출, 외국인 순매수 | 발표 일정, 최신값 |
| `scenario` | "12월 인상 + 상원 공화 수성", "AI capex 가이던스 하향" | 확률, 트리거, 영향 경로 |

**엣지 타입** (모두 `src → dst`, `sign ∈ {+1,−1,0}`, `weight 0–1`, `confidence`, `valid_from/to`, `evidence[]`)

- 구조: `supplies_to`, `customer_of`, `competes_with`, `owns_stake`, `subsidiary_of`, `member_of`
- 권력: `appointed_by`, `reports_to`, `regulates`, `votes_on`(FOMC 투표권!), `lobbies`, `donates_to`, `allied_with`, `opposes`, `pressures`
- 인과·이익(핵심): `benefits_from`, `hurt_by`, `depends_on`, `exposed_to`, `triggers`, `hedges`
- 통계: `correlates_with(sign, lag_days, r)`, `leads`(선행)
- 담론: `argues`, `predicts`, `denies`, `confirms`
- 시간: `succeeds`, `precedes`, `scheduled_for`

### 8.2 이익관계 매트릭스 (cui bono)

테마마다 자동 생성·수동 보정되는 표. 리포트의 "거미줄" 섹션의 뼈대.

```
theme: 연준 12월 인상 가능성
  benefits_from: [달러, 단기채 수익률, 은행 NIM(단기), 원화 약세 수혜 수출주(조건부)]
  hurt_by:       [장기 성장주/AI 반도체 밸류에이션, 리츠, 신흥국 자금, KOSPI 외국인 수급, 트럼프 재정 계획]
  decision_makers: [Warsh(의장, 매파·독립성 과시 인센티브), Cook, Hammack(10월 인상 소수의견), ...]
  pressures: [Trump → Fed (인하 압박; 중간선거·부채이자 인센티브)]
  watch: [11월 CPI, 12/9 FOMC, SEP 점도표, 워시 연설 일정]
```

### 8.3 인물 카드 (`vault/entities/person/<id>.md` + `entity.profile_json`)

```yaml
id: kevin-warsh
role: Fed Chair (valid_from: 2026-05 ⚠️)
stance_vector:            # −1 ~ +1, evidence 링크 필수
  hawkish_dovish: +0.6    # 2026-09 인상, "인플레 너무 높고 오래"
  independence: +0.8      # 트럼프 인하 압박 공개 거부
  market_sensitivity: -0.2
incentives:
  - 의장 1년차: 독립성·신뢰 구축 (인상 결정의 비용 < 굴복의 평판 비용)
  - 재임명 시점·정치 환경 (⚠️)
track_record:            # 과거 발언 → 실제 결정 적중률, 자동 채점
  - 2026-10-16 "회의 예단 안 함" → 10/28 동결 (일치)
rhetoric_patterns: ["데이터 의존", "인플레 지속성 강조"]
listens_to: [FOMC 매파 블록, ...]
conflicts: []
sources: [claim_ids...]
```

한국 측 인물(한은 총재·기재부·대통령실 경제라인·삼성/하이닉스 경영진)도 같은 포맷. ⚠️ 현직자 이름은 하네스가 2026-11 기준으로 검증.

### 8.4 엔티티 해소 (Entity Resolution)

- 정규 ID는 slug(`kevin-warsh`) + 가능하면 Wikidata QID. 별칭 사전 `config/aliases.yaml`: `연준|Fed|Federal Reserve|FOMC(기관으로서)`, `젠슨 황|Jensen Huang|黃仁勳`, `닉스|SK하이닉스|SK hynix|000660.KS`.
- 신규 엔티티는 `entity.status=candidate`로 들어오고, 3개 이상 Story에서 등장하거나 사람이 승인하면 `confirmed`.
- 동명이인·역할 변경(의장 교체)은 `valid_from/to`로 처리. 그래프는 **시간 슬라이스**로 조회 가능해야 한다(`as_of=2026-11-01`).

### 8.5 시드 그래프 (수작업 YAML, 부록 E)

처음부터 LLM에 그래프를 맡기면 쓰레기가 쌓인다. **핵심 노드 ~200개, 엣지 ~500개**를 사람 검수한 YAML로 시작한다. 범위:

- 미국 통화·재정 축: Fed(의장·부의장·이사·지역연은 총재 12인 투표권 포함), Treasury, 의회 구도, 백악관 경제라인, CBO
- AI 반도체 공급망: 하이퍼스케일러(MSFT/GOOGL/AMZN/META/ORCL) → GPU/ASIC(NVDA/AMD/AVGO/MRVL) → 파운드리(TSMC/삼성) → 메모리(SK하이닉스/삼성/마이크론) → 장비(ASML/AMAT/LRCX/TEL) → 패키징(CoWoS) → 전력·데이터센터(유틸리티·건설) → 중국 변수(수출통제·화웨이·Moonshot/DeepSeek 저비용 모델)
- 한국 축: 한은·기재부·금감원·KRX, 삼성·하이닉스·어보브반도체(KOSDAQ 102120, 상우 재직사 — 이해충돌 표시), 외국인 수급, 원화, 수출
- 지정학: 이란·호르무즈·OPEC+·방산, 미중(관세·수출통제), 한미(통상·파병)
- 자산 간 통계 엣지: UST10Y→성장주(−), DXY→KOSPI 외국인(−), SOX→SK하이닉스(+, lag 0), 유가→헤드라인CPI(+, lag 30d) — r과 lag는 가격 데이터로 **계산**해서 넣는다(추정 금지)

### 8.6 그래프 분석

| 분석 | 방법 | 리포트 사용 |
|---|---|---|
| 중심성 | 주간 엣지 가중 PageRank / betweenness | "이번 주 허브" (누가 중앙에 섰나) |
| 커뮤니티 | Louvain | 서사 클러스터 = 테마 자동 발견 |
| 엣지 churn | 신규·강화·만료 엣지 수 | 관심이 어디로 이동했나 |
| **충격 전파** | §8.7 | 1·2·3차 효과 목록 |
| 경로 설명 | k-shortest paths(사건→자산) | "연결 설명" 문장 생성 |
| 주간 diff | 스냅샷 비교 | 그래프 변화 차트 |

### 8.7 충격 전파 알고리즘 (`graph/propagate.py`)

```python
IMPACT_EDGES = {"benefits_from", "hurt_by", "depends_on", "exposed_to", "triggers",
                "correlates_with", "supplies_to", "customer_of", "pressures"}
DECAY = {1: 1.0, 2: 0.6, 3: 0.35}

def propagate(G, shock, sign, magnitude, as_of, max_depth=3, floor=0.05):
    frontier = [(shock, sign, magnitude, [])]
    for depth in range(1, max_depth + 1):
        nxt = []
        for node, s, m, path in frontier:
            for e in G.out_edges(node, as_of=as_of, types=IMPACT_EDGES):
                s2 = s * e.sign
                m2 = m * e.weight * e.confidence * DECAY[depth]
                if m2 < floor: continue
                yield Effect(target=e.dst, sign=s2, magnitude=m2, depth=depth,
                             path=path + [e], evidence=e.evidence_ids)
                nxt.append((e.dst, s2, m2, path + [e]))
        frontier = nxt
```

전파 결과는 **시장 데이터와 대조**한다: 전파가 "SK하이닉스 −"라고 하는데 실제 +5%면 "시장이 다르게 본다" 플래그 → 그 자체가 그 주 최고의 인사이트 후보(§9.4).

### 8.8 시각화·탐색

- **주 뷰어: 자체 생성 HTML** `charts/graph-YYYY-WW.html` (cytoscape.js 단일 파일): 노드 색 = 타입, 엣지 색 = 부호(초록 이득 / 빨강 손해 / 회색 구조), 굵기 = weight×confidence, 시간 슬라이더(`as_of`), 엣지 클릭 시 evidence URL 목록. 엔티티 설명 md는 `vault/entities/`에 생성해 두되 Obsidian 연동은 Phase 8 선택.
- 주간 리포트에는 "이번 주 거미줄" 서브그래프(노드 ≤ 25) PNG를 matplotlib+networkx로 렌더.

---

## 9. L6 분석 엔진

### 9.1 테마 추적기 (Narrative Momentum)

Story→Theme 매핑(임베딩 + 룰). 테마별 주간 지표: 기사 수, 독립 출처 수, T0 비율, 감성 평균, 신규성(novelty), **혼잡도(crowdedness)** = 같은 결론을 말하는 출처 비율. 혼잡도 0.8 이상 + 가격 이미 반영 → "컨센서스 포화" 경고. 영향도(impact) = 그래프 중심성 × 자산 연결 수 × 출처 신뢰도.

### 9.2 레짐 탐지기 (주 1회 갱신, 규칙 기반 + 데이터)

| 축 | 입력 | 상태값 |
|---|---|---|
| 금리 | FOMC 결정·점도표·FedWatch·2Y | 인상 / 동결(매파) / 동결(비둘기) / 인하 |
| 유동성 | WALCL, RRP, TGA, 은행 준비금, HY 스프레드 | 긴축 / 중립 / 완화 |
| 달러 | DXY, USDKRW, 한미 단기금리차 | 강 / 중립 / 약 |
| 위험선호 | VIX, MOVE, HY, BTC, 소형주/대형주 | risk-on / 중립 / risk-off |
| AI 사이클 | 하이퍼스케일러 capex 가이던스, TSMC 월매출, DRAM/HBM 계약가, 리드타임, 데이터센터 착공·취소 | 확장 / 정점 논쟁 / 조정 |
| 한국 수급 | 외국인 순매수 20일, 반도체 수출, 환율 | 유입 / 중립 / 유출 |

레짐 전환 주간은 리포트 맨 위에 경보.

### 9.3 캘린더 엔진

FOMC·CPI·PPI·NFP·PCE 일정(BLS/BEA 페이지), 금통위, 미국 국채 입찰, 주요 실적(NVDA·AVGO·MU·TSMC 월매출·삼성·하이닉스), 옵션 만기, 선거·정치 일정, 연준 인사 연설 일정. 출력: "다음 2주 관전 포인트" (각 이벤트에 **이번 주 논제와의 연결**을 붙임).

### 9.4 교차자산 정합성 검사

서사 ↔ 가격의 불일치 탐지. 예: "인상 우려"가 테마 1위인데 2Y 금리 하락 → 서사가 틀렸거나 다른 힘이 있다. 불일치 목록은 chief-editor의 필수 입력.

### 9.5 역사적 유사 사례 (Analog Finder)

`eval/history/` 큐레이션 베이스(2000 닷컴 capex 붕괴, 2018 메모리 다운사이클·연준 인상, 2022 인상 사이클·성장주 조정, 2024–25 DeepSeek 쇼크 등 — 각 사례의 서사·데이터·결과를 md로) + 과거 주간 리포트 임베딩. 이번 주 리포트 벡터와 코사인 상위 3개를 "비슷했던 시기"로 제시하되 **차이점을 반드시 같이 적는다**.

### 9.6 포트폴리오 렌즈 (비공개)

`private/portfolio.yaml`(상우가 직접 관리, 레포 미추적)에 적힌 자산·비중·제약을 읽어, 이번 주 거미줄에서 **내 포트폴리오에 직접 걸리는 엣지**만 별도 섹션으로 뽑는다. 수량·금액은 리포트에 쓰지 않는다. 블로그 초안에는 이 섹션을 포함하지 않는다(🚫).

### 9.7 논제 원장 (Thesis Ledger)

매주 3–5개 논제. 형식: `"[기간]까지 [관측 가능한 사건] 확률 p. 틀렸다면 [신호]가 보인다."` 예: "2026-12-10까지 FOMC가 25bp 인상할 확률 0.45. 틀렸다면 11월 CPI 코어 MoM ≤ 0.2%와 워시 연설의 '충분히 제약적' 표현이 선행한다." 만기 시 자동 채점(Brier), 월간 회고에 누적 곡선.

---

## 10. L7 주간 합성 — 멀티에이전트 편집국

### 10.1 편집국 구성 (`.claude/agents/*.md`)

| 에이전트 | 모델 | 도구 | 입력 | 출력(≤ 800단어, 고정 포맷) |
|---|---|---|---|---|
| `macro-rates-analyst` | 중형 | DB 읽기, 차트 | 레짐·연준 claims·금리 데이터 | 사실/해석/함의/확신도/반증조건 |
| `policy-politics-analyst` | 중형 | DB 읽기 | 선거·재정·관세·수출통제·인물 카드 | 동일 |
| `semis-ai-analyst` | 중형 | DB 읽기, 차트 | capex·HBM/DRAM·공급망·실적 | 동일 |
| `korea-desk` | 중형 | DB 읽기 | KOSPI·원화·외국인·한은·정책 | 동일 |
| `graph-cartographer` | 중형 | 그래프 쿼리, 전파 | 주간 그래프 diff·전파 결과·정합성 불일치 | "이번 주 거미줄" 3개 경로 + 서브그래프 |
| `historian` | 중형 | 벡터 검색 | 이번 주 벡터 | 유사 사례 3 + 차이점 |
| `chief-editor` | 대형 | 전부 읽기 | 위 메모 전부 | 논제 3–5 초안, 한 줄 요약, 구조 |
| `skeptic-red-team` | 대형 | DB 읽기 | 논제 초안 | 각 논제 반대 논거·틀릴 조건·대안 가설 |
| `judge` | 대형 | — | 토론 로그 | 논제별 확률 보정·채택/기각 |
| `writer-ko` | 대형 | 리포트 템플릿, 블로그 문체 샘플 | 확정 논제 + 메모 | 리포트 본문(§10.4) |
| `fact-checker` | 중형 | DB 읽기 (**쓰기 금지**) | 리포트 본문 | PASS/FAIL + 위반 목록 (FAIL이면 발행 중단). 정정 섹션 누락도 FAIL |
| `data-steward` | 중형 | DB 읽기, `macroweb quality apply`(안전 수정만) | 품질 검토 결과(§10.5) | 품질 스코어카드 해설, 모순 판정, 사람 검토 큐 정리 |
| `chart-maker` | 소형 | Python 실행 | 데이터 스펙 | PNG 차트 5–8장 |
| `publisher` | 소형 | 파일·텔레그램 | 최종 md | 발행 |

원칙: 분석가 4명은 **병렬**, 각자 다른 컨텍스트(서로의 메모를 못 봄 → 독립성). 편집자만 전체를 본다. fact-checker는 쓰기 권한이 없다(검수자가 수정하면 검수가 아니다).

### 10.2 주간 워크플로

```
0  주간 데이터 품질 검토 (§10.5, 17:30~): 결정론적 검사 Q1–Q6 → 안전 수정 자동 적용 → Q7 감사 샘플 회수
   → data-steward 해설 → quality/YYYY-WW.md + 게이트 플래그(제외할 엣지, 경고 테마, 정정 목록)
1  데이터팩 생성 (Python, 게이트 플래그 반영): week_pack.json = 테마 상위 10, 검증된 claims 상위 100(impact순),
   그래프 diff, 전파 결과, 정합성 불일치, 레짐 표, 캘린더(2주), 가격 테이블, 지난 논제 채점
2  분석가 4 + cartographer + historian 병렬 실행 (서브에이전트, 각자 week_pack의 해당 슬라이스만)
3  chief-editor: 메모 6개 → 논제 초안 3–5 + 한 줄 요약
4  ping-pong 토론 (§10.3): skeptic ↔ editor 3라운드 → judge 판정 → 논제 확정(확률 포함)
5  writer-ko: 리포트 초안 (모든 [F] 문장에 claim_id 각주)
6  fact-checker GATE: claim_id 존재·라벨 적합·수치 일치·금지 표현(매수/매도 지시) 검사 → FAIL이면 5로 1회 회귀, 재실패 시 발행 중단 + 알림
7  chart-maker: 차트 생성, writer가 캡션 삽입
8  publisher: reports/YYYY-WW.md 확정, vault/weekly 링크, 텔레그램 요약(한 줄 요약 + 논제 3 + 링크), 블로그 초안(drafts/blog-YYYY-WW.md, 포트폴리오 섹션 제외)
9  run 기록(토큰·시간·게이트 결과), 실패 시 부분 산출물 보존
```

### 10.3 ping-pong 토론 프로토콜 (기존 ping-pong debate 시스템을 스킬로 흡수)

- 입력: 논제 1개 + 근거 claim_ids. 역할: Proponent(편집자 입장), Skeptic. 라운드당 ≤ 300단어, 3라운드 고정. 새 근거는 **DB에 있는 claim만** 인용 가능(외부 지식으로 사실을 만들지 못함). Judge는 (a) 채택/수정/기각 (b) 확률 (c) 가장 강한 반대 논거 1개를 출력하고 그것이 리포트 "반대 시나리오"에 들어간다.
- 토론 로그는 `reports/debates/YYYY-WW-<thesis>.md`로 보존(월간 회고 때 "어느 쪽이 맞았나" 채점).

### 10.4 리포트 템플릿 — 거미줄 리포트 (부록 I에 md 원형)

1. **한 줄 요약** — 이번 주 세상을 한 문장으로
2. **레짐 대시보드** — 6축 상태 + 전주 대비 화살표 + 전환 경보
3. **이번 주 거미줄 3가닥** — 각: 사건 → 경로(그래프 경로) → 결과 / 누가 이득·누가 손해 / 결정권자와 인센티브 / 확신도 / 틀리면 보일 신호
4. **움직인 사람들** — 이번 주 발언·행동한 인물 3–5명, 성향 벡터 변화, 의도 추정(`[S]` 명시)
5. **반도체 데스크** — AI capex·메모리 가격·공급망·실적, 한국 반도체 연결
6. **한국 데스크** — KOSPI·원화·외국인·정책
7. **검증 노트** — 걸러낸 가짜·과장·재탕 3건 + 걸러낸 신호
8. **논제 보드** — 새 논제 3–5(확률·기간·반증) + 지난 논제 채점
9. **다음 2주 캘린더** — 이벤트 + 이번 주 논제와의 연결
10. **비슷했던 시기** — 유사 사례 + 차이점
11. **반대 시나리오** — judge가 뽑은 가장 강한 반론
12. (비공개) **내 포트폴리오에 걸린 엣지**
13. **부록** — 출처 목록(신뢰도·라벨), 그래프 스냅샷, 차트, 토론 로그 링크

문체: 한국어, 평어체 블로그 톤(상우 블로그 `AI 투자 일기` 최근 5편을 `prompts/style/` 샘플로), 용어는 괄호 풀이, 표보다 문장, 휴대폰에서 3스크롤 이내 본문 + 부록. **매수·매도·헤지 지시 금지**(fact-checker 금지어 목록).

---

### 10.5 주간 데이터 품질 검토 (편집국 Step 0)

매일 쌓는 정보는 시간이 지나면 썩는다: 예측은 만기가 지나고, "현재 의장은 누구"류 사실은 바뀌고, 어제 VERIFIED였던 claim이 오늘 정정되고, 수집기가 조용히 죽는다. 주간 리포트는 **검사를 통과한 재고만** 쓴다.

원칙: (1) 결정론적 검사가 먼저, LLM은 판정이 필요한 것만. (2) 자동 수정은 되돌릴 수 있는 것만(상태 표시·만료·완전 일치 별칭 병합). 삭제는 하지 않는다. (3) 품질이 나빠도 리포트는 나간다 — 대신 해당 부분을 빼거나 경고를 단다(§2-9).

#### 7개 검사

| # | 검사 | 무엇을 보나 | 자동 처리 | 사람·LLM 처리 | 시작 경보 기준 (근거) |
|---|---|---|---|---|---|
| Q1 | **근거 무결성** | 모든 엣지에 evidence가 있나, evidence의 raw 스냅샷이 존재하고 sha256이 맞나, claim이 가리키는 article이 살아 있나 | 실패 엣지·claim을 `quarantined`로 → 데이터팩에서 제외 | — | **100% 불변식.** 하나라도 실패면 빨강 (근거 없는 엣지는 이 시스템의 정의상 존재하면 안 됨) |
| Q2 | **시효** | 만기 지난 forecast claim, 같은 주어·술어의 더 새 claim이 나온 "현재 상태" claim(직책·금리 수준 등), 종류별 기한(§0.4) 넘긴 미강화 엣지, 직책 바뀐 인물 | `expired` / `superseded`(새 claim 링크) / 엣지 `valid_to` 설정 | — | 처리 건수만 보고 (경보 없음) |
| Q3 | **모순** | 같은 주어·술어·시점에 값이 다른 claim이 둘 다 VERIFIED·CORROBORATED, 같은 src→dst에 반대 부호 엣지가 둘 다 활성(신뢰도 > 0.5) | — | data-steward(Sonnet급, 주 ≤ 20건): 하나를 superseded로 / 둘 다 맞고 조건이 다름(예: "인상 시 −, 인하 시 +")이면 조건 주석을 달고 유지 / 판단 불가면 review 큐 | 미해결 모순 7일 이상 1건이라도 노랑 (한 주를 넘겨 리포트에 섞이면 안 되므로) |
| Q4 | **중복·오염** | 별칭 정규화 후 같은 엔티티 쌍, 4주 넘게 candidate인 엔티티, **한 소스가 이번 주 신규 엣지의 30% 이상을 만든 경우** | 별칭 완전 일치만 병합(병합 이력 보존), 오래된 candidate 비활성 | 유사 이름 병합 후보·소스 쏠림은 review 큐 | 소스 쏠림 30% (소스 50개면 정상 몫의 15배 — 파서 버그나 스팸 의심) |
| Q5 | **소급 정정** | 이번 주 라벨이 바뀐 claim(→ DEBUNKED·DISPUTED·superseded) 중 **과거 리포트·논제가 인용한 것**, 경제지표 **수정치**(첫 발표 → 개정) | `report_citation`으로 영향받은 리포트·논제 추적 → 정정 목록 생성, 전파 결과 재계산 | 논제 판단이 바뀌는지 chief-editor가 판정 | 정정 목록이 비어 있지 않으면 리포트에 "정정" 섹션 **필수** |
| Q6 | **커버리지** | 테마·소스별 이번 주 수집량 vs 최근 4주 중앙값, 정상 주기의 2배 넘게 침묵한 소스, 상위 claim 중 T0 비율 | 소스 헬스 `degraded` 표시 | 수집 이상인지 실제로 조용한 주인지 data-steward가 가림 | 중앙값 대비 −50% (시작값, 8주 분포로 보정) · T0 비율 < 20% 노랑 |
| Q7 | **추출 품질 감사** | §6.2.5 감사 샘플 50개: 층별 추출 오류율 e, 수치 오류율, 관계 부호 오류율 | e를 신뢰도 갱신 할인율에 반영 | 오류 사례 상위 5개는 프롬프트 개선 후보로 `docs/PROMPT_PROPOSALS.md` | 층별 e > 0.15 노랑, 수치 오류율 > 5% 빨강 (§6.2.4와 같은 근거) |

경제지표 수정치(Q5): 고용·GDP 같은 지표는 첫 발표 후 개정된다. FRED의 발표 시점별 기록(ALFRED ⚠️ 접근 방식 확인)으로 "그 리포트를 쓸 때의 값"과 "지금의 값"을 비교해, 개정이 방향이나 해석을 바꿨을 때만 정정 목록에 올린다.

#### 게이트 — 품질 결과가 리포트에 미치는 영향

| 상태 | 리포트 처리 |
|---|---|
| Q1 실패 엣지·claim | 데이터팩에서 제외 (fact-checker가 인용 시 FAIL) |
| Q3 미해결 모순 | 해당 claim은 `[F]`로 쓸 수 없음 → 충돌 자체를 서술 |
| Q5 정정 존재 | 리포트 맨 위 "정정" 섹션 필수: 무엇이 틀렸고, 어느 주 리포트·논제가 썼고, 결론이 바뀌는지 |
| Q6 커버리지 빨강 테마 | 분석가 메모에 "수집 이상 가능" 단서 필수, 그 테마로 새 논제 금지 |
| Q7 빨강 층 | 그 층에서만 나온 수치는 `[I]`로 강등 |
| 전체 빨강 2개 이상 | 리포트 상단 배너 "이번 주 데이터 품질 경보" + 텔레그램 알림에 포함 |

#### 산출물

- `reports/quality/YYYY-WW.md`: 7개 검사 신호등, 자동 처리 로그, 미해결 큐, 지난주 대비 추이 (3스크롤 이내)
- 주간 리포트 레짐 대시보드 아래 한 줄: `데이터 품질: Q1🟢 Q2🟢 Q3🟡(2) Q4🟢 Q5 정정 1 Q6🟢 Q7🟢`
- `quality_run` 테이블에 지표 저장 → 월간 회고(§12)가 추세를 본다

#### 비용

Q1·Q2·Q4·Q6는 SQL·파이썬이라 0. Q3 판정 ≈ $0.3/주, Q7 감사 50개(Sonnet급 배치) ≈ $0.56/주, data-steward 해설 ≈ $0.15/주 → **≈ $4.3/월.**

## 11. L7' 발행·알림·연동

- `reports/YYYY-WW.md` git 커밋(자동), `vault/weekly/`에 링크 노트.
- 텔레그램: 기존 `investment-monitor-alerts` 봇 토큰 재사용(🔒 별도 채널 권장). 메시지 = 한 줄 요약 + 논제 3 + 리포트 경로.
- macOS 알림(osascript): 성공/실패.
- 블로그: Tistory Open API 종료(2024) → **초안 md만 생성**, 게시는 수동. 🔒 원하면 Playwright로 관리자 임시저장 자동화(로그인 세션 저장 필요, 별도 ADR).
- 투자일기 연동: 매월 1일 `digests/monthly-macro-YYYY-MM.md`("이달의 거시 배경", 10줄) 생성 → 투자일기 초안 자동화 흐름에 입력.
- `investment-monitor` 연동(선택): 그 쪽 `config.yaml` watchlist를 읽어 포트폴리오 렌즈 후보로, 이 쪽 레짐 표를 그 쪽 이메일 리포트 하단에 1줄 삽입.

---

## 12. L8 평가·학습 루프 (Track C, 매월 1일)

1. **논제 채점**: 만기 논제의 outcome 판정(데이터 API 자동 + 애매하면 review 큐) → Brier, 캘리브레이션 곡선(예측 확률 vs 실제 빈도).
2. **출처 적중률**: 각 소스가 낸 claim의 최종 라벨 분포 → `credibility` 베이지안 갱신(prior 강도 20). 반박 1건의 가중치는 `1 − e(층)`으로 할인(§6.2.5). 4주치 품질 스코어카드 추세도 함께 본다.
3. **검증기 재학습**: `eval/verify` + 지난달 사람 피드백으로 §7.2 가중치 로지스틱 회귀. F1 하락 시 롤백.
4. **그래프 정리**: 엣지 종류별 만료 기준(§0.4: 구조 365일·권력/이익 90일·발언 30일)을 넘긴 미강화 엣지에 `valid_to` 설정, candidate 엔티티 정리, 중심성 월간 추이.
5. **토론 채점**: judge가 기각한 논제 중 실제로 맞았던 것 / 채택했는데 틀린 것 → skeptic/editor 프롬프트 개선 메모.
6. **월간 회고 md**: 위 전부 + "이달의 거시 배경"(투자일기용) + 비용 집계.
7. **프롬프트 제안**: Stop 훅이 월간 run 로그를 읽고 `docs/PROMPT_PROPOSALS.md`에 개선안 작성(적용은 사람이).

---

## 13. 하네스 설계 (Claude Code)

### 13.1 레포 구조

```
macroweb/
├── PLAN.md                     # 이 문서 (SSOT)
├── CLAUDE.md                   # §0.1 규칙 + 명령어 + 현재 Phase 포인터 (짧게, ≤ 150줄)
├── .claude/
│   ├── settings.json           # 권한·훅
│   ├── agents/                 # §10.1 서브에이전트 14개 (md + frontmatter)
│   ├── skills/
│   │   ├── add-source/SKILL.md        # §4.5 절차
│   │   ├── verify-claim/SKILL.md      # §7 수동 검증 절차·루브릭
│   │   ├── graph-ops/SKILL.md         # 노드/엣지 추가·해소·전파 실행법
│   │   ├── weekly-report/SKILL.md     # §10.2 워크플로 (헤드리스 진입점)
│   │   ├── ping-pong-debate/SKILL.md  # §10.3 (기존 시스템 이식)
│   │   ├── chart/SKILL.md             # 차트 스펙→matplotlib 규약
│   │   ├── launchd-ops/SKILL.md       # 설치·로그·복구 절차
│   │   ├── monthly-review/SKILL.md    # §12
│   │   └── quality-review/SKILL.md    # §10.5 (주간 Step 0)
│   └── hooks/                  # 훅 스크립트 (python)
├── docs/ {PLAN_DIGEST.md, QUESTIONS.md, decisions/, PROMPT_PROPOSALS.md, RUNBOOK.md}
├── config/ {sources.yaml, aliases.yaml, traps.yaml, models.yaml(routing 포함), themes.yaml, calendar.yaml, key_persons.yaml, quality.yaml}
├── prompts/ {extract/, verify/, agents/, style/, CHANGELOG.md}
├── src/macroweb/
│   ├── cli.py                  # typer: collect|normalize|extract|verify|graph|digest|weekly|monthly|doctor|source
│   ├── collect/ normalize/ extract/ verify/ graph/ analyze/ synth/ publish/ eval/
│   ├── db/ {schema.sql, migrations/, repo.py}
│   └── llm/ {client.py(SDK 래퍼, 캐싱, 배치), schemas.py(pydantic), router.py(models.yaml)}
├── seed/ {entities.yaml, relations.yaml, persons/*.yaml}   # §8.5 시드 그래프
├── eval/ {extraction/, verify/, history/}
├── tests/ {fixtures/, unit/, golden/}
├── launchd/ {*.plist, install.sh, uninstall.sh}
├── bin/ {run_collect.sh, run_daily.sh, run_weekly.sh, run_monthly.sh}
├── data/  (gitignore)  raw/ db/ vectors/ graph/
├── reports/ digests/ charts/ drafts/ review/ vault/
├── private/ (gitignore)  portfolio.yaml, .env
├── pyproject.toml (uv), Makefile, .pre-commit-config.yaml
└── logs/ (gitignore)
```

### 13.2 CLAUDE.md 골격 (하네스가 작성)

```
# MacroWeb — 거미줄
목적: 매일 수집·검증·그래프 갱신, 매주 거시 인사이트 리포트 발행 (PLAN.md가 SSOT)
현재 Phase: 0  (docs/PLAN_DIGEST.md 먼저 읽을 것)
## 명령어
make doctor | uv run macroweb collect --date YYYY-MM-DD | ... | make eval-verify
## 불변 규칙
1) 출처 없는 숫자·인용·URL 생성 금지 2) [F] 문장은 claim_id 각주 필수 3) 매수/매도/헤지 지시 금지
4) 유료 벽 본문 수집 금지 5) 모델명은 config/models.yaml만 6) 모든 단계 idempotent
## 데이터 규칙
raw 스냅샷은 수정 금지. DB 스키마 변경은 migrations/ 통해서만.
## 스타일
완전한 파일로 쓰기, 영문 1줄 커밋, "다음 가자" = 현재 Phase 다음 DoD 항목
```

### 13.3 서브에이전트 정의 규약 ⚠️

`.claude/agents/<name>.md` — frontmatter에 `name`, `description`(언제 자동 위임되는지), `tools`(허용 도구 최소화; fact-checker는 쓰기 도구 제외), `model`(소/중/대 — 실제 값은 docs 확인). 본문 = 역할·입력·출력 포맷·금지사항. 예시는 부록 F.

### 13.4 훅 (`.claude/settings.json`) ⚠️ 이벤트명 docs 확인

| 이벤트 | 스크립트 | 목적 |
|---|---|---|
| SessionStart | `hooks/session_start.py` | PLAN_DIGEST·현재 Phase·미해결 QUESTIONS 출력 |
| PreToolUse(Bash) | `hooks/guard_bash.py` | `rm -rf`, `git push --force`, `data/raw` 수정, private/ 읽기 외 접근 차단 |
| PostToolUse(Write/Edit) | `hooks/lint_json.py` | prompts/·config/ 변경 시 스키마 검증 |
| Stop | `hooks/phase_check.py` | 현재 Phase DoD 체크리스트 상태 요약 + `make doctor` 결과 |

### 13.5 헤드리스·SDK 실행 (Track B)

- 기본: **Claude Agent SDK(Python)** 스크립트 `src/macroweb/synth/run_weekly.py`가 `weekly-report` 스킬의 절차를 코드로 고정하고, 서브에이전트 호출·토론·게이트를 순서대로 실행한다. launchd → `bin/run_weekly.sh` → `uv run python -m macroweb.synth.run_weekly --week 2026-W44`.
- 대안: `claude -p "/weekly-report 2026-W44" --output-format json` ⚠️(플래그·max-turns·권한 모드는 docs 확인). 비대화형에서는 권한 프롬프트가 뜨면 멈추므로 **허용 도구 목록을 settings에 고정**한다.
- 가드레일: 최대 턴 수, 최대 토큰 예산(초과 시 요약본만 발행), 타임아웃 60분, 실패 시 부분 산출물 보존 + 알림.
- 개발 중에는 VS Code에서 대화형 Claude Code로 같은 스킬을 수동 호출해 디버깅한다(동일 코드 경로).

### 13.6 관측·운영

- `run` 테이블 + `logs/` JSON 라인 로그. `macroweb status`: 최근 run, 소스 헬스, 큐 길이, 이번 달 토큰 사용량.
- `make doctor`: Python/uv/Playwright 설치, DB 무결성(PRAGMA integrity_check), 소스 50개 probe(HTTP 상태), API 키 존재, 디스크 여유, launchd 잡 로드 여부, 비용 캡 대비 사용률.
- 텔레그램 실패 알림에 **첫 에러 3줄 + 재실행 명령어** 포함.

### 13.7 테스트 전략

- 파서: 픽스처 골든 테스트(소스당 1+). 네트워크 호출은 테스트에서 금지(respx/vcr).
- 추출·검증: 평가셋 회귀(`make eval-extract`, `make eval-verify`), 임계치 미달 시 CI 실패.
- 그래프: 시드 로드 → 전파 결과 스냅샷 테스트.
- 주간 합성: `--dry-run`(LLM 호출 없이 데이터팩만), `--fixture-week`(저장된 데이터팩으로 합성 재현).
- pre-commit: ruff, mypy(느슨), yaml 스키마 검증.

---

## 14. 로드맵 — Phase별 Definition of Done

| Phase | 기간 | 목표 | DoD (전부 통과해야 다음 단계) |
|---|---|---|---|
| **0 스캐폴딩** | D1–2 | 뼈대 | 레포 구조·CLAUDE.md·agents/skills 골격·settings 훅·pyproject·Makefile·DB 스키마 v1·`make doctor` 통과·launchd plist dry-run(`launchctl print`로 로드 확인)·ADR-0001(docs 검증 결과) |
| **1 수집 MVP** | W1 | 매일 뭔가 쌓인다 | sources.yaml 20개(T0 8·T1 6·T2 3·T3 3) 어댑터+픽스처+골든·raw 스냅샷·URL/SimHash 중복제거·FRED/ECOS/AV 지표 수집·`collect` 3일 연속 무인 실행·일일 "수집 통계" md |
| **2 추출·검증 v1** | W2 | 첫 다이제스트 | 추출 프롬프트 v1 + 배치 파이프·claim/entity 테이블 채움·검증 신호 1·2·4·5·6 구현·라벨 부여·`review/` 큐·일일 다이제스트 10줄·추출 평가셋 30개 작성·**모델 라우팅 측정 실험(§6.2.4) 완료 + ADR**·T0 diff 우선 처리(FOMC 성명·금통위 의결문)·`extracted_by` 기록·**첫 주간 리포트 수동 생성(조악해도 됨, 템플릿 §10.4 준수)** |
| **3 거미줄 v1** | W3 | 관계가 보인다 | 시드 그래프 200노드/500엣지 YAML 로드·엔티티 해소(별칭 사전)·추출 relations→엣지 갱신(evidence 100%)·통계 엣지 r/lag 계산·vault 내보내기·전파 v1·주간 diff·서브그래프 PNG·**주간 품질 검토 v1(Q1·Q2·Q4·Q6) + 스코어카드**·승급 규칙 1–5 가동 |
| **4 편집국 v1** | W4 | 자동 주간 리포트 | 서브에이전트 6(분석가4·cartographer·editor)·writer-ko·fact-checker GATE·데이터팩 생성기·Agent SDK 러너·launchd weekly 등록·**일요일 17:30 자동 실행 → 19:30 전 발행 1회 성공**·텔레그램 알림 |
| **5 토론·논제·캘린더** | W5–6 | 반증 가능해진다 | ping-pong 스킬 이식·judge·논제 원장 + 자동 채점·캘린더 엔진·레짐 탐지기·교차자산 정합성·역사 베이스 5사례·chart-maker·블로그 초안·2회 연속 자동 발행 |
| **6 검증 v2 · 인물 카드** | W7–8 | 가짜를 거른다 | 신호 3·7·8·9·10·11 구현·평가셋 200개·F1 ≥ 0.85·traps.yaml·레드팀 검증 토론·인물 카드 30명(성향 벡터 evidence 링크)·검증 노트 섹션 가동·**품질 검토 v2(Q3 모순 판정, Q5 소급 정정·지표 수정치, Q7 감사 샘플) + 리포트 정정 섹션** |
| **7 학습 루프** | W9–12 | 스스로 나아진다 | 월간 회고 run·출처 credibility 갱신·검증기 재학습·그래프 정리·투자일기 '거시 배경' 생성·캘리브레이션 곡선·비용 리포트·**신뢰도 갱신에 층별 오류율 할인 적용·품질 경보 임계값 재보정**·RUNBOOK.md 완성·12주 성공 기준(§1.4) 측정 |
| **8+ 확장(백로그)** | — | — | 소스 150+·X/트위터(공식 API)·실적 콜 오디오 STT(상우 전공 활용: whisper 로컬)·옵션 스큐·Obsidian 플러그인·웹 대시보드·다국어 리포트 |

**2주 내 첫 리포트**가 최우선이다. Phase 2 끝의 "조악한 수동 리포트"를 건너뛰지 않는다.

---

## 15. 하네스 첫 프롬프트 (VS Code Claude Code 세션에 복붙)

```
너는 이 레포(macroweb)의 리드 엔지니어다. 루트의 PLAN.md가 단일 진실원이다.

할 일:
1. PLAN.md 전체를 읽고 docs/PLAN_DIGEST.md(≤300줄)를 쓴다.
2. PLAN.md의 ⚠️ 항목을 검증한다. 특히 §13의 Claude Code 기능(서브에이전트 frontmatter, 스킬, 훅 이벤트명,
   헤드리스 플래그, Agent SDK)은 https://code.claude.com/docs/en/claude_code_docs_map 을 가져와 확인하고
   틀린 부분을 docs/decisions/0001-claude-code-facts.md 에 기록한다. 모델명·배치 API·요금도 docs에서 확인해
   config/models.yaml을 만든다.
2-1. 가장 먼저 확인: `claude -p` 헤드리스와 Agent SDK가 각각 구독 한도로 과금되는지 API 키로 과금되는지 → ADR-0002 (§0.3 비용 결정이 여기에 달려 있다).
3. §13.1 구조로 레포를 생성한다: CLAUDE.md(§13.2 골격), .claude/settings.json(§13.4 훅 + 허용 도구),
   .claude/agents/ 14개(§10.1, 부록 F 규약), .claude/skills/ 9개(§13.1), pyproject(uv), Makefile, DB 스키마(부록 A).
4. Phase 0 DoD(§14)를 하나씩 통과시키고 Stop 훅으로 체크리스트를 출력한다.
5. §0.3 확정값으로 진행한다. §0.4 항목은 시작값으로 두고 보정 시점에 측정한다. 근거가 틀렸다고 판단되면 ADR로 바꾸고 docs/QUESTIONS.md에 적는다.

규칙: 출처 없는 숫자·URL 생성 금지. 완전한 파일로 쓰기. 영문 1줄 커밋. Phase 건너뛰기 금지.
첫 응답은 "PLAN_DIGEST 작성 완료 + ⚠️ 검증 결과 요약 + Phase 0 체크리스트"로 끝낸다.
```

이후 세션 지시는 짧게: "다음 가자" / "Phase 1 시작" / "소스 추가: TrendForce" / "주간 리포트 dry-run".

---

## 16. 리스크 · 법 · 윤리 · 비용

### 16.1 법·윤리
- robots.txt·이용약관 준수, 유료 벽 우회 🚫, 개인정보(커뮤니티 작성자) 저장 🚫(집계만).
- 원문 보관은 개인 연구용(비공개). **발행물·블로그에는 요약과 링크만**, 인용은 짧게.
- 어보브반도체는 상우 재직사 → 그래프에 `conflict_of_interest` 플래그, 리포트에서 해당 종목은 공시 사실만.
- 리포트는 투자 자문이 아니며 본인 판단용. 블로그 초안 하단 고지문 자동 삽입.

### 16.2 기술 리스크
| 리스크 | 대응 |
|---|---|
| 사이트 구조 변경으로 파서 깨짐 | 골든 테스트 + 헬스 degraded 보고 + 어댑터별 격리 |
| 에이전트 폭주·비용 폭발 | 턴·토큰 캡, 월 상한, dry-run 기본, 헤드리스 허용 도구 고정 |
| 환각(없는 출처) | claim_id 각주 강제 + fact-checker GATE + 출처 URL 재fetch 검사 |
| 맥이 잠들어 잡 누락 | pmset wake, idempotent, 누락 감지(`status`가 24h 이상 run 없음 → 알림) |
| 그래프 오염 | candidate/confirmed 2단계, evidence 없는 엣지 거부, 월간 정리 |
| 편향 고착(같은 결론 반복) | 혼잡도 지표, 레드팀 토론, 역사 유사 사례의 '차이점' 강제 |
| 상우가 안 읽음 | 텔레그램 한 줄 요약 + 논제 3개만. 전문은 선택 |

### 16.3 보안
- API 키는 `private/.env` + macOS Keychain(선택). 레포·로그에 키 출력 🚫(훅으로 grep 차단).
- Playwright는 로그인 세션 없음(블로그 자동 게시를 켤 때만 별도 프로필).

### 16.4 비용 — 계산 근거 (단가: Haiku급 $1/$5, Sonnet급 $3/$15, Opus급 $5/$25 per 1M 토큰, 배치 50% 할인 기준 ⚠️ 현행 모델 단가로 `config/models.yaml` 갱신 후 `make cost`로 재계산)

T1/T2 추출 (Haiku급, 배치):
- Story 80개 × (가변 입력 2.5k + 캐시된 시스템·스키마 1.5k, 출력 0.7k), 마감 직후 실시간 처리분과 엔티티 해소 포함
- **≈ $0.30/일 → $9/월**

T0 1차 문서 정독:
- 주 ~15건 × (입력 20k, 출력 2k), Sonnet급 배치 ≈ $0.68/주. 성명류는 diff만 읽어 실제는 더 적음
- 실적 콜·의사록 월 4–6건 Opus급 배치 ≈ $0.6/월
- **≈ $3.5/월**

승급 재추출 (Sonnet급 배치, 일 ≤ 8건 × 입력 4k·출력 0.7k) **≈ $2.2/월**

주간 편집국 (실시간):
- 분석가·cartographer·historian 6개 (Sonnet급, 각 입력 25k/출력 3k) ≈ $0.72
- chief-editor (Opus급, 30k/4k) ≈ $0.25
- 토론: 논제 4 × 3라운드 × 2역할 = 24호출 (Sonnet급, 8k/0.5k) ≈ $0.76 · judge 4호출 (Opus급) ≈ $0.30
- writer-ko (Opus급, 40k/8k) ≈ $0.40 · fact-checker (Sonnet급, 재시도 포함) ≈ $0.25
- 소계 ≈ $2.7, 에이전트 도구 호출·컨텍스트 재로딩 오버헤드 ×2 → **≈ $5.4/주 → $22/월**

주간 품질 검토 (§10.5) **≈ $4.3/월** · 월간 회고 **≈ $2/월**

합계 예상 **≈ $43/월**, 하드캡 **$45**. 단계별 강등: 80%($36) → T1/T2 추출 50개 / 100% → 주간 리포트만 실행 / 주간 단독 예산 $8 초과 시 토론 라운드 3→2. **품질 검토와 T0 정독은 강등 대상에서 제외**(신뢰도의 바닥이라서).

비교 기준: 지금 investment-monitor는 API 비용 $0이다. 이 시스템은 그보다 한 단계 비싼 대신 "매일 읽어주는 애널리스트 팀" 역할을 한다. 비싸다고 느껴지면 첫 번째 레버는 T1/T2 추출 80 → 50 (−$3.4), 두 번째는 토론·작성까지 Sonnet급 통일 (−$8). 구독 헤드리스 경로가 확인되면 주간 몫이 0에 가까워진다.

---

## 17. 부록

### A. DB 스키마 (SQLite, 핵심 DDL)

```sql
CREATE TABLE source (id TEXT PRIMARY KEY, name TEXT, tier INTEGER, kind TEXT, url TEXT, lang TEXT,
  country TEXT, topics TEXT, paywall INTEGER DEFAULT 0, enabled INTEGER DEFAULT 1, parser TEXT,
  rate_limit_s REAL DEFAULT 2.0, parent_org TEXT);
CREATE TABLE source_stats (source_id TEXT PRIMARY KEY REFERENCES source(id), credibility REAL,
  n_claims INTEGER DEFAULT 0, n_confirmed INTEGER DEFAULT 0, n_refuted INTEGER DEFAULT 0,
  health TEXT DEFAULT 'ok', updated_at TEXT);
CREATE TABLE article (id TEXT PRIMARY KEY, url TEXT, canonical_url TEXT UNIQUE, source_id TEXT,
  title TEXT, author TEXT, published_at TEXT, fetched_at TEXT, lang TEXT, text TEXT, text_ko TEXT,
  raw_path TEXT, sha256 TEXT, paywalled INTEGER, status TEXT);
CREATE VIRTUAL TABLE article_fts USING fts5(title, text, content='article', content_rowid='rowid', tokenize='trigram');
CREATE TABLE story (id TEXT PRIMARY KEY, first_seen TEXT, last_seen TEXT, title_rep TEXT,
  n_articles INTEGER, n_independent INTEGER, theme_ids TEXT, embedding_id TEXT, summary_ko TEXT);
CREATE TABLE story_article (story_id TEXT, article_id TEXT, is_syndicated INTEGER, PRIMARY KEY(story_id, article_id));
CREATE TABLE entity (id TEXT PRIMARY KEY, type TEXT, canonical_name TEXT, aliases TEXT, wikidata_qid TEXT,
  country TEXT, sector TEXT, profile_json TEXT, status TEXT DEFAULT 'candidate', valid_from TEXT, valid_to TEXT,
  conflict_of_interest INTEGER DEFAULT 0);
CREATE TABLE claim (id TEXT PRIMARY KEY, story_id TEXT, text TEXT, type TEXT, subject_eid TEXT, predicate TEXT,
  object_eid TEXT, value REAL, unit TEXT, time_ref TEXT, confidence REAL, label TEXT, impact REAL,
  signals_json TEXT, first_seen TEXT, last_updated TEXT);
CREATE TABLE evidence (id TEXT PRIMARY KEY, claim_id TEXT, article_id TEXT, span_start INTEGER, span_end INTEGER,
  kind TEXT, note TEXT);
CREATE TABLE relation (id TEXT PRIMARY KEY, src_eid TEXT, dst_eid TEXT, type TEXT, sign INTEGER, weight REAL,
  confidence REAL, lag_days INTEGER, r REAL, valid_from TEXT, valid_to TEXT, evidence_ids TEXT, last_reinforced TEXT,
  origin TEXT CHECK(origin IN ('seed','extracted','computed')));
CREATE TABLE thesis (id TEXT PRIMARY KEY, week TEXT, text TEXT, horizon_date TEXT, probability REAL,
  falsifier TEXT, status TEXT, outcome INTEGER, brier REAL, debate_path TEXT, claim_ids TEXT);
CREATE TABLE report_citation (report_week TEXT, claim_id TEXT, relation_id TEXT, section TEXT);  -- 소급 정정 추적
CREATE TABLE quality_run (week TEXT PRIMARY KEY, q1_fail INTEGER, q2_expired INTEGER, q2_superseded INTEGER,
  q3_open INTEGER, q4_merged INTEGER, q4_flood_source TEXT, q5_errata INTEGER, q6_json TEXT, q7_json TEXT, status_json TEXT);
-- claim 추가 컬럼: status TEXT DEFAULT 'active' CHECK(status IN ('active','superseded','expired','retracted','quarantined')),
--   superseded_by TEXT, extracted_by TEXT, stratum TEXT, escalation_reason TEXT
CREATE TABLE run (id TEXT PRIMARY KEY, job TEXT, started_at TEXT, ended_at TEXT, status TEXT, stats_json TEXT,
  prompt_versions TEXT, tokens_in INTEGER, tokens_out INTEGER);
CREATE TABLE market (date TEXT, key TEXT, value REAL, source TEXT, PRIMARY KEY(date, key));
CREATE INDEX idx_claim_label ON claim(label, impact);
CREATE INDEX idx_rel_src ON relation(src_eid, type);
CREATE INDEX idx_rel_dst ON relation(dst_eid, type);
```

### B. `config/sources.yaml` 항목 예시

```yaml
- id: fed_press
  name: Federal Reserve press releases
  tier: 0
  kind: rss            # rss | html | api | playwright | pdf
  url: https://www.federalreserve.gov/feeds/press_all.xml   # ⚠️ 검증
  lang: en
  country: US
  topics: [fed, rates, policy]
  parent_org: federal-reserve
  parser: rss_default
  rate_limit_s: 5
  paywall: false
  credibility_prior: 0.95
- id: yna_economy
  name: 연합뉴스 경제
  tier: 1
  kind: rss
  url: https://www.yna.co.kr/rss/economy.xml   # ⚠️ 검증
  lang: ko
  country: KR
  topics: [macro, korea, markets]
  parent_org: yonhap
  parser: rss_default
  credibility_prior: 0.80
- id: trendforce_press
  name: TrendForce press center (DRAM/NAND 가격)
  tier: 2
  kind: html
  url: https://www.trendforce.com/presscenter/   # ⚠️ 검증
  lang: en
  topics: [memory, dram, hbm, semis]
  parser: trendforce_press_v1
  credibility_prior: 0.70
- id: polymarket_fed
  name: Polymarket — Fed decision markets
  tier: 3
  kind: api
  url: https://gamma-api.polymarket.com/markets?tag=fed   # ⚠️ 검증
  topics: [fed, prediction_market]
  parser: polymarket_v1
  credibility_prior: 0.70   # 가격은 사실, 결과는 아님
```

### C. 추출 프롬프트 골격 (`prompts/extract/v1.md`)

```
역할: 경제 뉴스에서 검증 가능한 주장(claim)·엔티티·관계·이익관계를 추출하는 분석가.
출력: 아래 JSON 스키마만. 설명 문장 금지. 모르면 null.
규칙:
- claim은 원자적(한 문장 = 한 사실). 숫자는 value/unit 분리, 기간(QoQ/YoY/MoM) 명시.
- 기사가 문서(성명·공시·통계·보고서)를 인용하면 cited_primary_doc에 제목+날짜.
- "소식통/관계자" 인용은 anonymous_source=true.
- relations는 기사가 명시한 것만. 추론으로 만들지 않는다(추론은 cui_bono에 why와 함께).
- novelty_hint: 기사 스스로 과거 사건을 되짚으면 recycled.
- red_flags: 제목 과장, 저자 없음, 숫자 없는 단정, 긴급성 유도, 단위 혼동 의심.
[스키마: §6.1]
```

### D. 검증 루브릭(언어 신호) 출력 스키마

```json
{"sensational_headline": 0.0, "hedging_density": 0.0, "anonymous_ratio": 0.0,
 "has_named_author": true, "numbers_without_source": 0, "urgency_cues": 0.0,
 "satire_probability": 0.0, "ad_or_pump_probability": 0.0, "language_risk": 0.0}
```

### E. 시드 그래프 YAML 예시 (`seed/relations.yaml`, 2026-11 맥락 — 전부 ⚠️ evidence 필요)

```yaml
entities:
  - {id: fed, type: org, name: Federal Reserve, aliases: [연준, Fed, FOMC]}
  - {id: kevin-warsh, type: person, name: Kevin Warsh, aliases: [워시, 케빈 워시], role: Fed Chair}
  - {id: lisa-cook, type: person, name: Lisa Cook, role: Fed Governor}
  - {id: beth-hammack, type: person, name: Beth Hammack, role: Cleveland Fed President}
  - {id: donald-trump, type: person, name: Donald Trump, role: US President}
  - {id: us-midterm-2026, type: event, name: 2026 US midterm election, date: 2026-11-03}
  - {id: fomc-2026-12-09, type: event, name: FOMC December 2026, date: 2026-12-09}
  - {id: ust10y, type: asset, name: US 10Y yield, data_key: FRED:DGS10}
  - {id: sox, type: asset, name: PHLX Semiconductor Index, data_key: STOOQ:^SOX}
  - {id: sk-hynix, type: org, name: SK hynix, aliases: [하이닉스, 닉스, 000660.KS], country: KR, sector: memory}
  - {id: nvidia, type: org, name: NVIDIA, aliases: [엔비디아, NVDA]}
  - {id: moonshot-ai, type: org, name: Moonshot AI, aliases: [문샷], country: CN}
  - {id: kimi-k3, type: product_tech, name: Kimi K3 (open-weight, low-cost)}
  - {id: turboquant, type: product_tech, name: Google TurboQuant (KV-cache compression)}
  - {id: hbm, type: product_tech, name: HBM}
  - {id: usdkrw, type: asset, name: USD/KRW, data_key: ECOS:FX_USDKRW}
  - {id: kospi, type: asset, name: KOSPI}
  - {id: theme-ai-capex, type: theme, name: AI capex 지속성}
  - {id: theme-fed-independence, type: theme, name: 연준 독립성}
  - {id: iran-conflict, type: event, name: 이란 전쟁/호르무즈}
  - {id: oil, type: asset, name: Brent, data_key: FRED:DCOILBRENTEU}
relations:
  - {src: kevin-warsh, dst: fed, type: reports_to, sign: 0, weight: 1.0, origin: seed}
  - {src: lisa-cook, dst: fomc-2026-12-09, type: votes_on, sign: +1, weight: 1.0, note: "10월 인상 소수의견"}
  - {src: beth-hammack, dst: fomc-2026-12-09, type: votes_on, sign: +1, weight: 1.0}
  - {src: donald-trump, dst: fed, type: pressures, sign: -1, weight: 0.8, note: "금리 인하 요구"}
  - {src: us-midterm-2026, dst: donald-trump, type: triggers, sign: 0, weight: 0.9, note: "임기 후반 권력 구도"}
  - {src: fomc-2026-12-09, dst: ust10y, type: triggers, sign: +1, weight: 0.6, note: "인상 시 상승(조건부)"}
  - {src: ust10y, dst: sox, type: correlates_with, sign: -1, weight: 0.5, origin: computed}   # r, lag 계산 후 채움
  - {src: sox, dst: sk-hynix, type: correlates_with, sign: +1, weight: 0.7, origin: computed}
  - {src: nvidia, dst: sk-hynix, type: customer_of, sign: +1, weight: 0.9, note: "HBM"}
  - {src: sk-hynix, dst: hbm, type: supplies_to, sign: +1, weight: 1.0}
  - {src: kimi-k3, dst: theme-ai-capex, type: hurt_by, sign: -1, weight: 0.5, note: "저비용 모델→capex 재평가"}
  - {src: turboquant, dst: hbm, type: hurt_by, sign: -1, weight: 0.4, note: "메모리 수요 둔화 우려"}
  - {src: theme-ai-capex, dst: sk-hynix, type: benefits_from, sign: +1, weight: 0.8}
  - {src: sk-hynix, dst: kospi, type: exposed_to, sign: +1, weight: 0.8}
  - {src: ust10y, dst: usdkrw, type: correlates_with, sign: +1, weight: 0.4, origin: computed}
  - {src: iran-conflict, dst: oil, type: triggers, sign: +1, weight: 0.7}
  - {src: oil, dst: fed, type: pressures, sign: +1, weight: 0.4, note: "헤드라인 물가 경유, lag"}
```

### F. 서브에이전트 예시

`.claude/agents/fact-checker.md`
```
---
name: fact-checker
description: 주간 리포트 초안의 모든 [F] 문장이 DB의 VERIFIED/CORROBORATED claim을 참조하는지, 수치가 일치하는지, 금지 표현이 없는지 검사한다. 리포트 발행 직전에 반드시 호출.
tools: [Read, Bash(uv run macroweb claim get *), Bash(uv run macroweb market get *)]   # ⚠️ 도구 표기법 docs 확인
model: sonnet   # ⚠️ config/models.yaml의 mid 등급
---
너는 검수자다. 수정하지 않는다. 결과는 PASS 또는 FAIL 한 단어로 시작하고, FAIL이면 위반 목록을
(줄번호, 문장, 위반 유형{missing_claim_id, label_too_weak, number_mismatch, forbidden_phrase, unverifiable_as_fact}, 제안) 표로 낸다.
금지 표현: 매수|매도|비중 확대|비중 축소|헤지하라|환노출하라|추천.
수치는 claim.value/unit과 market 테이블을 대조하고 허용 오차는 config/tolerances.yaml을 따른다.
```

`.claude/agents/skeptic-red-team.md`
```
---
name: skeptic-red-team
description: 편집자의 논제 초안을 공격한다. 각 논제에 대해 가장 강한 반대 논거, 틀릴 조건, 대안 가설을 DB의 claim만 근거로 제시한다.
tools: [Read, Bash(uv run macroweb claim search *), Bash(uv run macroweb graph path *)]
model: opus   # ⚠️
---
규칙: 외부 지식으로 사실을 만들지 않는다. 모든 반론은 claim_id 또는 relation_id를 인용한다.
각 논제마다: (1) 반대 논거 ≤ 150단어 (2) 틀릴 때 먼저 보일 신호 2개 (3) 대안 가설 1개와 그 확률.
"양쪽 다 가능"은 금지. 입장을 가져라.
```

### G. 스킬 예시 `.claude/skills/weekly-report/SKILL.md`

```
---
name: weekly-report
description: 주간 거미줄 리포트를 생성한다. 데이터팩 생성→분석가 병렬→편집→ping-pong 토론→작성→fact-check 게이트→차트→발행. "주간 리포트", "weekly", "/weekly-report" 요청 시 사용.
---
절차 (§10.2와 동일, 각 단계 산출물 경로 고정):
1. `uv run macroweb weekly pack --week $WEEK` → data/weekly/$WEEK/pack.json
2. 서브에이전트 병렬: macro-rates-analyst, policy-politics-analyst, semis-ai-analyst, korea-desk, graph-cartographer, historian
   → data/weekly/$WEEK/memos/*.md  (각자 pack.json의 자기 슬라이스만 읽는다)
3. chief-editor → theses_draft.md
4. ping-pong-debate 스킬 × 논제 수 → debates/*.md → judge → theses_final.json
5. writer-ko → draft.md (템플릿 reports/_template.md)
6. fact-checker → gate.json; FAIL이면 5를 1회 재시도, 재실패 시 중단하고 알림
7. chart-maker → charts/$WEEK/*.png; writer가 캡션 삽입
8. publisher → reports/$WEEK.md, vault/weekly/$WEEK.md, drafts/blog-$WEEK.md, 텔레그램
실패 시: 부분 산출물을 지우지 말 것. run 테이블에 status=failed와 단계 기록.
```

### H. launchd plist + 래퍼

`launchd/com.sawoo.macroweb.weekly.plist`
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.sawoo.macroweb.weekly</string>
  <key>ProgramArguments</key><array>
    <string>/bin/bash</string><string>/Users/sawoo/macroweb/bin/run_weekly.sh</string>
  </array>
  <key>StartCalendarInterval</key><dict>
    <key>Weekday</key><integer>0</integer><key>Hour</key><integer>17</integer><key>Minute</key><integer>30</integer>
  </dict>
  <key>WorkingDirectory</key><string>/Users/sawoo/macroweb</string>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    <key>MACROWEB_ENV</key><string>prod</string>
  </dict>
  <key>StandardOutPath</key><string>/Users/sawoo/macroweb/logs/weekly.out.log</string>
  <key>StandardErrorPath</key><string>/Users/sawoo/macroweb/logs/weekly.err.log</string>
  <key>RunAtLoad</key><false/>
</dict></plist>
```

`bin/run_weekly.sh`
```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source private/.env; set +a
WEEK="$(uv run python -c 'import datetime as d;print(d.date.today().strftime("%G-W%V"))')"
LOCK="data/.weekly.lock"; exec 9>"$LOCK"; flock -n 9 || { echo "already running"; exit 0; }
caffeinate -i uv run python -m macroweb.synth.run_weekly --week "$WEEK" \
  || { uv run macroweb notify --level error --job weekly --tail 3; exit 1; }
uv run macroweb notify --level info --job weekly --message "거미줄 리포트 $WEEK 발행"
```
(install.sh: `cp launchd/*.plist ~/Library/LaunchAgents/ && launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.sawoo.macroweb.*.plist`; 확인: `launchctl print gui/$(id -u)/com.sawoo.macroweb.weekly`)

### I. 리포트 템플릿 `reports/_template.md`

```
# 거미줄 리포트 {{week}} ({{date_range}})

**한 줄:** {{one_liner}}

## 정정 (있을 때만, 맨 위)
{{errata}}

## 레짐
금리 {{regime.rates}} · 유동성 {{regime.liquidity}} · 달러 {{regime.dollar}} · 위험선호 {{regime.risk}} · AI 사이클 {{regime.ai}} · 한국 수급 {{regime.kr_flow}}
{{regime_alert}}
데이터 품질: {{quality_line}}

## 이번 주 거미줄
### 1. {{strand1.title}}
사건 → 경로 → 결과: {{strand1.path}}
이득: {{strand1.winners}} / 손해: {{strand1.losers}}
결정권자와 인센티브: {{strand1.actors}}
확신도 {{strand1.conf}} · 틀리면 보일 신호: {{strand1.falsifier}}
(2, 3 동일)

## 움직인 사람들
## 반도체 데스크
## 한국 데스크
## 검증 노트 — 이번 주 걸러낸 것
## 논제 보드
| # | 논제 | 기간 | 확률 | 틀리면 |  … 지난 논제 채점: …
## 다음 2주
## 비슷했던 시기
## 반대 시나리오
## (비공개) 내 포트폴리오에 걸린 엣지
## 부록: 출처 · 그래프 · 차트 · 토론 로그
> 본 리포트는 개인 학습·판단용 자료이며 투자 자문이 아닙니다. [F]=검증 사실 [I]=해석 [S]=추측
```

### J. 용어집 (리포트 괄호 풀이용 시드 — `config/glossary.yaml`)

FOMC(연방공개시장위원회, 미국 기준금리 결정 회의) · 점도표(위원들의 금리 전망 분포) · 매파/비둘기파(긴축/완화 선호) · 연준 독립성(정치권 압력과 무관한 금리 결정) · 장기금리(10년 국채 수익률, 성장주 밸류에이션의 할인율) · capex(설비투자) · FCF(잉여현금흐름) · HBM(고대역폭메모리, AI GPU 옆 메모리) · CoWoS(TSMC 첨단 패키징) · 오픈웨이트(가중치 공개 모델) · KV캐시(추론 시 메모리를 차지하는 중간값) · 외국인 수급(외국인 순매수, KOSPI 방향의 큰 손) · 한미 금리차(환헤지 비용의 뿌리) · Brier score(확률 예측 정확도, 0이 완벽) · 혼잡도(같은 결론을 말하는 출처 비율) · 전파(한 사건이 그래프를 타고 번지는 경로)

---

*끝. 다음 개정(v0.2)은 Phase 2 완료 후, 첫 수동 리포트의 교훈을 반영해 §7·§8을 수정한다.*
