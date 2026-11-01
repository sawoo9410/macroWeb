# PLAN_DIGEST — MACROWEB_PLAN v0.3 요약 (≤ 300줄, 세션 재시작 시 먼저 읽는다)

> 원문 `PLAN.md`(1,249줄)가 SSOT. 이 요약은 길을 찾기 위한 지도다. §번호는 PLAN 의 절. ADR(`docs/decisions/`)이 PLAN 과 다르면 ADR 이 이긴다.
> 작성 2026-11-01 (Phase 0 첫 세션). 현재 Phase/DoD 상태는 `docs/phase_status.json`.

## 0. 한 문장
매일 50개 소스를 긁어 **claim 단위로 검증**하고 **관계 그래프(거미줄)** 를 갱신한 뒤, 매주 일요일 저녁 멀티에이전트 편집국이 **반증 가능한 논제**가 담긴 한국어 리포트를 발행하는 기계. 매수·매도 지시는 하지 않는다(§1.3).

## 1. 운영 규칙 (§0.1 — CLAUDE.md 에 복사됨)
Phase 순서 엄수 · 결정은 ADR · 🔒는 QUESTIONS.md 에 적고 기본값 진행 · 가짜 데이터 금지 · Phase 끝 `make doctor` · 모든 단계 idempotent CLI · 스크래핑 예절(robots, 2s, 유료 벽 본문 금지) · "다음 가자" = 다음 DoD.

## 2. 확정값 (§0.3) — 근거가 바뀌면 ADR 로 바꾼다
| 결정 | 값 |
|---|---|
| 주간 발행 | 일 17:30 KST 시작(품질 검토 Step 0 ≤ 20분 → 편집국) · 19:30 완료 |
| 일일 처리 | 07:00 KST (미 마감 06:00 겨울 기준 + 30분), 07:30 전 다이제스트 |
| 수집 주기 | 30분 틱 + 소스별 적응 주기 `clamp(0.5×피드창, 15분, 6h)` + 이벤트 ±2h 는 T0 10분 |
| 일일 LLM 물량 | T1/T2 Story 80개 정밀 추출 + T0 1차 문서 전량, 나머지 제목·임베딩만 |
| 배치 | 틱마다 롤링 제출, 06:30 마지막 배치, 07:20 까지 미완료분만 실시간 |
| 월 비용 상한 | API $45 (80% → 추출 50개, 100% → 주간만; T0 정독·품질 검토는 강등 제외). **ADR-0001: 단가 하락으로 API 예상 ≈ $9/월** |
| 주간 실행기 | ~~Agent SDK~~ → **`claude -p` 구독 경로 (ADR-0002)** |
| 시장 데이터 | FRED·Stooq·FDR·ECOS. Alpha Vantage 사용 안 함(investment-monitor 와 키 충돌) |
| 그래프 뷰어 | 자체 HTML(cytoscape.js) — 색=부호, 굵기=가중치, 시간 슬라이더. Obsidian 은 Phase 8 선택 |
| 알림 | 기존 텔레그램 봇, **별도 채팅방**, 한 줄 요약 + 논제 3 + 경로 |
| 리포트 | 한국어·괄호 풀이·투자 1년차 눈높이. 블로그는 초안 md 만(티스토리 API 종료) |
| 포트폴리오 렌즈 | `private/portfolio.yaml`, 비중·노출 방향만, 블로그 초안 제외 |

## 3. 측정해서 정하는 값 (§0.4)
Story 동일 판정(SimHash ≤3, 코사인 ≥0.92; Phase 1 끝 200쌍 라벨) · 검증 가중치(로지스틱 회귀, 월 1회) · 출처 prior(Tier 0.15–0.95, 베이지안 강도 20) · 루머 유예 2 영업일 · 엣지 만료 구조 365/권력·이익 90/발언 30일 · 통계 엣지 r·lag(계산만) · 층별 추출 모델(Phase 2 실험: F1 격차 ≥0.10 또는 수치 오류율 격차 ≥5%p 인 층만 상위 모델) · 승급 상한 8/일 · 품질 경보 임계(8주 후 5%/95%).

## 4. 목표·성공 기준 (§1)
산출물: 수집 스냅샷(30분) · 일일 다이제스트 10줄(07:00) · **거미줄 리포트**+품질 스코어카드(일 17:30→19:30) · 월간 회고(1일).
12주 후: 12회 무중단 발행 · 논제 Brier — 시장 가격 있는 논제는 시장 Brier +0.02 이내, 없으면 ≤0.20 · 가짜뉴스 F1 ≥0.85 · 그래프 노드 ≥1,000/엣지 ≥5,000(evidence 100%) · 투자일기 자동 삽입 · "왜"를 설명 가능한 비율↑.
**맥락 시드(§1.5)** — 연준 의장 워시·9/16 인상·10/28 동결 10:2, PPI 4년래 최대, 중간선거 11/3, 이란 전쟁, AI 반도체 조정(브로드컴·마이크론·TurboQuant·Kimi K3), KOSPI 6000대, BTC 8만대 — **전부 ⚠️ 검증 대상 claim** 으로 `seed/claims_to_verify.yaml` 에 등록. 사실로 쓰지 않는다.

## 5. 설계 원칙 10 (§2)
스크래핑이 뿌리(URL+시각+해시+raw) · 사실/해석/추측 [F][I][S] 분리 · 1차 출처 우선(충돌은 기록) · 반증 가능해야 논제 · 뉴스는 엣지 · 인물엔 인센티브 · 한국 투자자 렌즈 · 싸게 많이/비싸게 적게 · 하네스 우선(사람 손 0) · 2주 내 첫 리포트.

## 6. 아키텍처 (§3)
- **Track A (매일, 결정론적 Python + SDK 직접 호출·배치)**: L1 수집 → L2 정규화/중복제거 → L3 추출 → L4 검증 → L5 그래프 갱신 → 다이제스트.
- **Track B (매주, 에이전트)**: L6 분석 → 편집국(분석가4 ∥ cartographer ∥ historian → chief-editor → ping-pong 3라운드 → judge → writer-ko → fact-checker GATE → chart-maker → publisher).
- **Track C (매월)**: L8 평가·학습.
- 저장: SQLite WAL `data/db/macroweb.sqlite` + FTS5(trigram) · 벡터 sqlite-vec/FAISS(bge-m3 로컬) · raw `data/raw/YYYY/MM/DD/<sha256>.html.gz`(+meta) · vault md · reports/charts/digests git 추적 · private/ 제외.

## 7. L1 수집 (§4)
Tier prior: T0 1차 0.95 · T1 통신사·주요지 0.80 · T2 전문 0.65 · T3 예측시장·데이터 0.70(가격은 사실) · T4 커뮤니티 0.30 · T5 미분류 0.15.
레지스트리 `config/sources.yaml`(현재 32개 등록, Phase 1 DoD 는 20개 어댑터). 소스 1개 = 어댑터 1개 + 픽스처 1개 + 골든 테스트 1개. 실패 격리(3회 연속 → degraded). 유료 벽 제목·리드·링크만. 중복: URL 정규화 → 제목 SimHash ≤3 → 본문 코사인 ≥0.92 = 같은 Story(전재는 독립 출처 아님).
launchd: collect(1800s) · daily 07:00 · weekly 일 17:30 · monthly 1일 08:00. 잠든 맥은 pmset 로 깨움, idempotent 필수, caffeinate, 로그 `logs/<job>.{out,err}.log`, 실패 시 osascript+텔레그램.

## 8. L2–L3 정규화·추출 (§5–6)
스키마 핵심: article · story · story_article · claim(type numeric/event/quote/forecast/attribution, label, status) · evidence · entity(valid_from/to, candidate→confirmed) · relation(sign, weight, confidence, evidence_ids, origin seed/extracted/computed) · thesis · run · source_stats · market · report_citation · quality_run (부록 A → `src/macroweb/db/schema.sql`).
추출 계약(§6.1 → `llm/schemas.py:ExtractionResult`): summary_ko, claims[], entities[], relations[](기사가 명시한 것만), cui_bono[], sentiment, novelty_hint, red_flags.
**모델 라우팅(§6.2)**: 기준은 "잘못 읽었을 때의 비용". 층별 기본: S-DATA LLM 없음 · S-T0-STMT diff 만 mid · S-T0-LONG mid(월 4–6건 large) · S-T1/S-T1-KO/S-T2 small · S-T4 LLM 없음 · S-ER mid. 승급 규칙 5개(스키마 실패·수치 불일치·고영향 DISPUTED·핵심 인물 직접 발언·고영향 루머), 일 8건. T0 diff 우선(직전 성명과 문장 정렬 → 변경 문장만). 측정 실험(Phase 2, 층당 20 Story, Haiku vs Sonnet). 감사 샘플 주 50개(기준 모델 Sonnet)로 층별 오류율 e → 출처 감점 할인 `1−e`. 모든 claim 에 `extracted_by`. 프롬프트는 `prompts/<name>/v<N>.md` + CHANGELOG, `make eval-extract`.

## 9. L4 검증 (§7)
claim 단위 신뢰도 추정기. 라벨: VERIFIED([F]) · CORROBORATED([F], 출처 병기) · SINGLE_SOURCE([I], "보도에 따르면") · DISPUTED(충돌 보고) · DEBUNKED(본문 금지) · UNVERIFIABLE([S]+확률) · RECYCLED(금지) · SPAM_SATIRE(격리).
신호 12: 출처 prior · 독립 교차검증(log) · 1차 출처 역추적(++/−−) · 수치 검증 · 시간 일관성 · 언어 신호(LLM 루브릭, 부록 D) · 도메인 위험 · 루머 생명주기 · 정정·반박 감시 · 시장 반응 정합성 · 생성 콘텐츠 신호 · 레드팀 토론.
점수식 초기값 `logit = 1.2·prior + 0.9·log1p(n) + 1.5·primary + 1.5·numeric − 0.8·recycled − 0.7·lang − 1.0·domain − 0.6·rumor + 0.3·market − 2.0·debunked`.
게이트: [F] 는 VERIFIED|CORROBORATED claim_id 필수(fact-checker 가 막음) · 금지 라벨 본문 불가 · 고영향+저신뢰는 review 큐(사람이 안 읽어도 돈다). 함정 `config/traps.yaml`. 평가셋 200개 F1 ≥0.85(Phase 6). 리포트 '검증 노트' = 그 주 걸러낸 3건.

## 10. L5 거미줄 (§8)
노드 10종(person·org·country_bloc·policy·asset·product_tech·event·theme·indicator·scenario) · 엣지 30종(구조·권력·인과이익 benefits_from/hurt_by/… · 통계 correlates_with(r,lag) · 담론 · 시간). cui bono 매트릭스(테마별 이득/손해/결정권자/압력/watch). 인물 카드(성향 벡터 + evidence, 인센티브, 트랙레코드) → `seed/persons/`. 엔티티 해소: slug+QID, `config/aliases.yaml`, candidate→confirmed(Story 3개), 시간 슬라이스 `as_of`. 시드 그래프 ~200노드/500엣지(사람 검수 YAML, 부록 E → `seed/`). 분석: PageRank/betweenness·Louvain·churn·전파(`propagate`, decay 1/0.6/0.35, floor 0.05)·k-shortest paths·주간 diff. 전파 결과 ≠ 가격 반응이면 그 주 최고 인사이트 후보. 뷰어: 자체 HTML + 리포트용 서브그래프 PNG(≤25 노드).

## 11. L6 분석 (§9)
테마 추적(기사 수·독립 출처·T0 비율·감성·신규성·**혼잡도** ≥0.8+가격 반영 → 컨센서스 포화) · 레짐 6축(금리·유동성·달러·위험선호·AI 사이클·한국 수급; 전환 주간 경보) · 캘린더(이벤트 ↔ 논제 연결) · 교차자산 정합성 · 역사 유사(큐레이션 베이스 + 차이점 필수) · 포트폴리오 렌즈(비공개) · 논제 원장 `"[기간]까지 [사건] 확률 p. 틀렸다면 [신호]"` + Brier 자동 채점.

## 12. L7 편집국 (§10)
에이전트 14: macro-rates·policy-politics·semis-ai·korea-desk(중형, 병렬·독립) · graph-cartographer · historian · chief-editor(대형) · skeptic-red-team(대형) · judge(대형) · writer-ko(대형) · fact-checker(중형, **쓰기 금지**) · data-steward(중형) · chart-maker(소형) · publisher(소형) → `.claude/agents/`.
워크플로 0–9: 품질 검토 → 데이터팩 → 메모 6 병렬 → 편집(논제 3–5) → ping-pong 3라운드 → judge → writer → fact-check GATE(1회 회귀) → 차트 → 발행 → run 기록 (`.claude/skills/weekly-report`).
리포트 13섹션(부록 I → `reports/_template.md`): 한 줄 · 정정 · 레짐 · 거미줄 3가닥 · 움직인 사람들 · 반도체 데스크 · 한국 데스크 · 검증 노트 · 논제 보드 · 다음 2주 · 비슷했던 시기 · 반대 시나리오 · (비공개) 포트폴리오 · 부록.
**품질 검토 Q1–Q7(§10.5 → `config/quality.yaml`)**: 근거 무결성(100% 불변식) · 시효 · 모순(data-steward) · 중복/오염(소스 쏠림 30%) · 소급 정정(정정 섹션 필수) · 커버리지(−50%, T0 <20%) · 추출 감사(e >0.15 노랑, 수치 >5% 빨강). 게이트 표 참조. 품질이 나빠도 리포트는 나간다(빼거나 경고).

## 13. 발행·학습 (§11–12)
발행: `reports/YYYY-WW.md` 커밋 · vault 링크 · 텔레그램 · osascript · 블로그 초안 `drafts/` · 투자일기용 `digests/monthly-macro-YYYY-MM.md` · investment-monitor 연동(선택).
월간: 논제 채점·캘리브레이션 → 출처 credibility(할인 적용) → 검증기 재학습(F1 하락 시 롤백) → 그래프 정리 → 토론 채점 → 회고 md → 프롬프트 제안.

## 14. 하네스 (§13) — 공식 docs 검증 결과는 ADR-0001
레포 구조 §13.1 생성 완료. CLAUDE.md ≤150줄. 서브에이전트 frontmatter(name·description·tools·model·effort·maxTurns·disallowedTools·skills). 훅: SessionStart(컨텍스트) · PreToolUse Bash(guard) · PostToolUse Edit|Write(lint) · Stop(DoD+doctor 를 `systemMessage` 로). 헤드리스: `claude -p "/weekly-report W" --output-format json --permission-mode acceptEdits --permission-prompts none --max-turns --max-budget-usd` (`--bare` 금지 — 구독 OAuth 를 건너뛴다). 테스트: 픽스처 골든(네트워크 금지) · 평가셋 회귀 · 전파 스냅샷 · 주간 `--dry-run`/`--fixture-week` · pre-commit(ruff·mypy·yaml).

## 15. 로드맵 DoD (§14) — 상세는 `docs/phase_status.json`
0 스캐폴딩(D1–2) → 1 수집 MVP(W1: 소스 20·픽스처·raw·중복제거·지표·3일 무인) → 2 추출·검증 v1(W2: 프롬프트 v1·배치·신호 1·2·4·5·6·다이제스트·평가셋 30·라우팅 실험 ADR·T0 diff·**첫 수동 리포트**) → 3 거미줄 v1(W3: 시드 200/500·해소·엣지 갱신·통계 엣지·vault·전파·품질 v1·승급) → 4 편집국 v1(W4: 에이전트 6+writer+fact-checker·데이터팩·러너·launchd weekly·**일 17:30 자동 발행 1회**·텔레그램) → 5 토론·논제·캘린더(W5–6) → 6 검증 v2·인물 카드(W7–8: F1 ≥0.85·traps·카드 30·품질 v2) → 7 학습 루프(W9–12: 월간·RUNBOOK·12주 측정) → 8+ 백로그.
**2주 내 첫 리포트가 최우선. Phase 2 끝의 조악한 수동 리포트를 건너뛰지 않는다.**

## 16. 리스크·법·비용 (§16)
robots·유료 벽 우회 금지·커뮤니티 개인정보 저장 금지·발행물엔 요약과 링크만·어보브반도체 이해충돌 플래그·투자 자문 아님 고지. 기술 리스크 대응표(파서 깨짐→골든+degraded, 에이전트 폭주→턴·토큰 캡, 환각→claim_id 강제+GATE, 잠든 맥→pmset+idempotent, 그래프 오염→2단계+evidence, 편향 고착→혼잡도+레드팀, 안 읽음→텔레그램 한 줄). 보안: 키는 `private/.env`, 로그·레포 출력 금지(훅). 비용 계산은 `config/cost_workload.yaml` × `config/models.yaml` → `make cost`.

## 17. 이 세션이 바꾼 것 (ADR 요약)
- ADR-0001 Claude Code 사실 검증: 훅 이벤트명 ✅, Stop 출력은 `systemMessage` ✏️, 에이전트 `tools:` 에 `Bash(…)` 패턴 불가 → permissions 로 ✏️, `--permission-prompts none` 추가 ✅, `--bare` 는 구독 불가 ⚠️, 단가 전부 하락 ✏️, macOS 에 flock 없음 → mkdir 락 ✏️, plist 경로 실제 경로로 ✏️.
- ADR-0002 주간 실행기 = `claude -p` 구독 OAuth (Agent SDK 는 API 키 정책). API 월 예상 ≈ $9.
- ADR-0003 레포 위치 `/Users/seosang-u/projects/finance/macroWeb`, 원격 `github.com/sawoo9410/macroWeb`(**PUBLIC** — QUESTIONS Q1), `MACROWEB_PLAN_v0.3.md` → `PLAN.md`, Python 3.12.16(uv).
