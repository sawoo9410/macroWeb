# ADR-0009 — 검증 v1: 결정론 신호 1·2·4·5·6, 모델 호출 없음

- 날짜: 2026-11-03 · 상태: 채택 · 관련: PLAN §7.1–7.3, §14 Phase 2 DoD(verify-signals-v1), ADR-0006(라벨 규칙·절편), ADR-0007(구독 호출 예산)

## 맥락
Phase 2 DoD 는 검증 신호 1(출처 prior)·2(독립 교차검증)·4(수치 검증)·5(시간 일관성)·6(언어 신호)과 라벨, review 큐를 요구한다.
지금 없는 것: 임베딩(bge-m3, Phase 2 후반), 1차 문서 역추적(신호 3, Phase 6), 데이터 API 키(FRED·ECOS — Q19 와 별개로 미발급).
PLAN §7.2 의 신호 6은 LLM 루브릭(`prompts/verify/v1.md`)인데, ADR-0007 의 구독 호출 예산(소크 60/일)에서 Story 마다 호출을 하나 더 쓰면 추출량이 절반으로 준다.

## 결정
1. **모델·네트워크 없이** L1–L3 가 이미 저장한 것만으로 신호를 계산한다(`verify/signals.py`). 매 틱 `collect → extract → verify` 로 돈다(`macroweb tick`).
2. 신호별 v1 정의
   - 1 prior = `source_stats.credibility`(없으면 `TIER_PRIOR[tier]`).
   - 2 n_independent = `story.n_independent`(모회사 다름·전재 제외; 수집 단계에서 계산). claim 단위 교차검증(같은 주장이 다른 Story 에도)은 Phase 3 엔티티 해소 뒤.
   - 3 primary_match 는 Phase 6 이지만 **퇴화 사례만** 적용: claim 이 T0 1차 문서 자체에서 나왔으면(`evidence.kind = primary_doc`) 1 → VERIFIED. "ECB 가 X 라고 했다" 의 근거가 ECB 문서 자체이기 때문.
   - 4 numeric_match: `config/verify.yaml numeric_keys` 의 패턴(주어·문장)으로 `market` 키를 고르고, claim 날짜(없으면 기사 날짜) 이전 최근 7일 안의 값과 `tolerances.yaml by_unit` 로 비교. **수준(level)만** 비교하고 변화폭(bp·%p·YoY·"by")은 건너뛴다. 불일치(−1)는 허용 오차 3배 밖이고 문장에 수준 표지("…에 마감", "closed at")가 있을 때만 — 애매하면 미판정. 지금 비교 가능한 키: UST 수익률·NAVER 지수·ECB 교차환율·Kraken BTC(ADR-0005).
   - 5 recycled: 같은 언어 기사 중 **90일 이상 전** 제목 SimHash 해밍 ≤ 3 이 있으면 1 → RECYCLED. 임베딩 cosine ≥ 0.9 규칙은 bge-m3 뒤에 교체(`rules.recycled.min_cosine` 유지).
   - 6 language_risk: LLM 루브릭 대신 **추출 결과의 red_flags + 결정론 특징**(선정적 제목 정규식·익명 인용·바이라인 없음(T1+만)·전망을 확정처럼·헤지 밀도·'외신 종합' 원문 없음·출처 없는 수치)의 가중 합을 0–1 로 자른다(`language_proxy.weights`).
   - 플래그: `unverifiable` = 익명 인용 + 인용·전망형 claim, `spam_satire` = red_flags 에 풍자·광고·리딩방 단서. `disputed` 는 v1 에서 수치 불일치로만 생긴다(출처 간 충돌 판정은 Phase 3).
3. 점수·라벨은 ADR-0006 의 `verify/contracts.py`(절편 −1.0 포함) 그대로. 결과는 `claim.confidence/label` 과 `claim.signals_json["verify"]`(모든 입력·근거 문장 포함) 에 기록 — 리포트의 각주와 fact-checker 가 "왜 이 라벨인가" 를 읽을 수 있게.
4. review 큐: impact ≥ 0.7 · conf < 0.5 (`rules.high_impact/low_confidence`) 인 claim 을 `review_queue(kind=low_conf_high_impact)` 에 한 번만 넣고 열린 항목 전체를 `review/<KST날짜>.md` 로 쓴다. 사람이 decision 을 적어 반영하는 `verify apply --review` 는 Phase 2 후반(source_stats 학습과 함께).
5. `claim.impact` 는 v1 에서 선별 impact(테마 유사도 × tier prior, 독립 출처 ≥ 3 강제 승격) × claim 유형 가중치다. PLAN §9.1 의 그래프 중심성 기반 impact 는 Phase 3.

## 대안
- Story 마다 Haiku 루브릭 호출(PLAN 원안): 신호 품질은 낫지만 소크 예산에서 추출량 절반. 평가셋(eval/verify)이 생기면 proxy 와 루브릭을 비교해 되돌릴 수 있게 프롬프트는 남겨 둔다.
- 검증을 Phase 6 까지 미루기: 그러면 첫 다이제스트·첫 수동 리포트에 `[F]` 각주를 달 수 없다(불변 규칙 2).

## 결과
- 라벨이 전부 설명 가능하고 재실행해도 같다(`macroweb verify --all` idempotent). 비용 0.
- 약점: 언어 신호가 거칠다(과장 제목 정규식·red_flags 의존), 단일 출처 T0 문서가 모두 VERIFIED 가 된다(문서가 "말했다" 는 사실은 맞지만 내용의 진위는 아님 — 리포트는 이를 "성명에 따르면" 으로 써야 하고 writer-ko 규약에 반영), DISPUTED 는 수치에서만 나온다.
- eval/verify(Q20 과 함께 라벨 30개)가 생기면 §7.5 로지스틱 재학습 전에 이 proxy 들의 AUC 를 먼저 본다.
