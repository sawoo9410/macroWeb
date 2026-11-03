# ADR-0012 — 검증 v2 부분 구현과 월간 학습 루프 v1 (모델 호출 없이 가능한 것부터)

- 날짜: 2026-11-03 · 상태: 채택 · 관련: PLAN §7.2(#7–#11), §7.4 함정, §7.6 검증 노트, §10.5 Q3·Q5·Q7, §12 월간 루프, ADR-0009, ADR-0010

## 맥락
ADR-0010 의 구축 우선 모드에서 Phase 6·7 의 골격을 같은 날 세운다. Phase 6 의 신호 3(1차 문서 역추적)·8(루머 생명주기)·12(레드팀)는 각각 문서 fetch 파이프, T4 수집, 토론 실동작이 필요하고,
Q7 감사 샘플은 Sonnet 호출 50건/주가 필요하다. 지금 데이터로 결정론적으로 계산할 수 있는 것만 먼저 넣고, 나머지는 "미계산" 으로 표시한다.

## 결정
1. **검증 v2 (`verify/signals_v2.py`)**: #7 도메인 위험 = HTTPS 없음·sources.yaml 밖 소스(각 0.5; WHOIS 등록일·typosquat 은 뒤), #9 정정·반박 감시 = 후속 기사 제목의 정정 단서 + claim 주어 일치 → `review_queue(kind=debunk_candidate)` (**자동 DEBUNKED 없음** — 단서만으로는 약하다), #10 시장 반응 = "급등/급락" 류 claim 의 방향 vs 당일 market 변화(±1/0, 변화 임계 0.2%·0.02pp), #11 생성 콘텐츠 = 같은 정규화 문장이 24시간 안에 3개 소스 이상(언어 위험 +0.2). `config/traps.yaml` 의 함정 중 결정 가능한 6개(unit_confusion·anonymous_policy_rumor·prediction_market_as_fact·capex_guidance_as_actual·korean_foreign_roundup·recycled/satire)를 적용하고 claim 의 `verify.v2.traps` 에 남긴다. 익명 정책 루머·예측시장 수치는 `unverifiable`, '외신 종합' 은 독립 출처 수를 1 로 묶어 CORROBORATED 를 막는다.
2. **품질 v2**: Q3 모순(같은 주어·술어·기간의 값 불일치가 둘 다 사실 라벨, 같은 src→dst 반대 부호 활성 엣지) → `contradiction` 큐, 7일 넘게 미해결이면 노랑. Q5 소급 정정 = `report_citation` 이 가리키는 claim 의 라벨·상태 변화 목록(비어 있지 않으면 '정정' 섹션 필수; 게이트 `errata_required`). Q7 은 ⚪ 로 둔다.
3. **검토 큐 반영**: `review apply --review review/<날짜>.md` 가 decision 을 큐에 기록하고 `source_stats` 확인/반박 카운트와 `eval/verify/decisions.jsonl` 에 쌓는다. **라벨은 사람이 바꾸지 않는다**(검증기 재학습의 입력일 뿐).
4. **월간 루프 v1 (`monthly/run.py`)**: 논제 자동 채점 + Brier 캘리브레이션, 출처 신뢰도 베이지안 갱신 `cred' = (20·prior + 확인 − 반박·(1−e)) / (20 + 확인 + 반박)` (e = 층별 추출 오류율, Q7 전까지 0; [0.05, 0.99] 로 자름), 엣지 만료·오래된 candidate 집계·PageRank 상위, 비용(llm_batch 합·run 통계, 구독 환산), 품질 스코어카드 추세, 추출 오류 상위(프롬프트 제안 후보 — 제안서는 사람이 쓴다), `digests/monthly-macro-YYYY-MM.md` 10줄, `reports/monthly/YYYY-MM.md`.
5. 검증기 재학습(§12-3)·토론 채점(§12-5)·Stop 훅 프롬프트 제안(§12-7)은 입력이 생길 때까지 "미해결" 섹션에 적는다.

## 결과
- 신뢰도 갱신은 v1 라벨 분포에 좌우된다: T0 문서는 자기 근거로 전부 VERIFIED 라 상승 쪽으로 치우친다 — Phase 6 의 1차 문서 역추적이 들어오기 전까지 T0 의 prior(0.95) 근처에 머무는 게 정상이다.
- 정정 후보 큐는 거짓 양성이 많을 수 있다(제목 단서 + 이름 일치). 첫 달은 큐 크기를 보고 단서 목록을 조정한다.
- 모든 새 신호는 `claim.signals_json.verify.v2` 에 입력값과 함께 남아 리포트의 검증 노트가 "어떤 신호로 걸렀는지" 를 그대로 쓴다(§7.6).
