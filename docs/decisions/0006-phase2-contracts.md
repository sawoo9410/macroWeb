# ADR-0006 — Phase 2 인터페이스 계약 (스키마 v3 · 검증 수식 · 추출 멱등 키 · 프롬프트 조립)

- 상태: 확정(인터페이스) · 날짜: 2026-11-02 · Phase 1 → 2 사이. PLAN §0.1-1 의 예외("스키마·인터페이스 정의는 미리 해도 된다")만 쓴다. 추출·검증 **로직**은 Phase 1 DoD(3일 무인 실행)와 `ANTHROPIC_API_KEY`(Q19)가 갖춰진 뒤 들어간다.

## 맥락
Phase 1 의 남은 DoD 둘은 시간(소크)과 Phase 2 의존(launchd daily)이다. 기다리는 동안 Phase 2 가 반복해서 고치게 될 경계들 — 무엇을 모델에 주고, 결과를 어디에 어떤 키로 넣고, 신호를 어떻게 점수·라벨로 바꾸는지 — 를 먼저 고정하면 Phase 2 는 채우기만 하면 된다.

## 결정
1. **스키마 v3 (`0003_phase2.sql`)**: `llm_batch`(배치 원장: provider_batch_id·상태·건수·비용·result_path), `extraction`(Story × prompt_version × model_tier 가 기본키 = **멱등 키**; `custom_id` UNIQUE; status queued→submitted→succeeded/failed/quarantined/escalated; `result_json` 보관 → §6.2.5 감사 재처리 가능), `review_queue`(검토 큐의 원천 — `review/<date>.md` 는 여기서 렌더), `story` 에 `stratum·lang·rep_article_id·impact·selected_at`.
2. **custom_id = `ext_<story_id>_v<N>_<tier>`** (영숫자·`_`·`-`, ≤ 64자 — Batches API 제한). 같은 Story 를 같은 프롬프트·같은 모델로 두 번 제출하지 않는다; 승급은 tier 가 바뀌므로 새 행이다.
3. **검증 수식은 `config/verify.yaml` 에만** (§7.2 초기 가중치). **절편 `bias = -1.0` 을 추가**했다 — 원식대로면 단일 출처 T4 루머(prior 0.3, n=1)가 conf 0.73 으로 시작해 "저신뢰" 큐에 걸리지 않는다; 절편을 넣으면 0.49, T1 단일 0.64, T0 1차 문서 일치 0.91 로 §7.1 라벨 의미와 맞는다. 월 1회 재학습(§7.5)이 절편도 함께 학습한다.
4. **라벨 결정 순서** (`verify/contracts.py:decide_label`): SPAM_SATIRE → DEBUNKED → RECYCLED → VERIFIED(1차 문서 또는 데이터 API 일치) → DISPUTED(충돌 또는 불일치) → CORROBORATED(독립 출처 ≥ 2) → UNVERIFIABLE(검증 경로 없음·루머 유예 경과) → SINGLE_SOURCE. 계산되지 않은 신호는 0 으로 두고 `missing` 에 기록한다(Phase 2 v1 은 신호 1·2·4·5·6 만 계산).
5. **운영 파라미터는 `config/extract.yaml`** (일 80 Story, T0 전량, 입력 6k 토큰, 선별 가중치, 배치 06:30/07:20, 검토 큐 임계, 다이제스트 10줄). 모델·단가·라우팅은 계속 `models.yaml`.
6. **프롬프트 조립** (`llm/prompting.py`): 시스템 = 프롬프트 파일 본문(모든 Story 에 동일 → 프롬프트 캐시 적중), 유저 = 메타(source·tier·stratum·published·lang·url·독립 출처 수·절단 여부) + 제목 + 본문. 본문은 앞 85% + 뒤 10% 로 절단하고 절단 사실을 표시한다. `extract.yaml prompt.version` 이 `run.prompt_versions` 에 기록된다.
7. 템플릿: `digests/_template-daily.md`(10줄 고정 구조), `review/_template.md`(approve/reject/unsure 열).

## 결과
- Phase 2 첫 세션의 할 일이 명확해진다: (1) `StorySelector` 구현(테마 키워드 → 임베딩), (2) `Extractor` 구현(LLMClient + llm_batch/extraction 원장), (3) 신호 1·2·4·5·6 계산기, (4) `digest` 명령, (5) 평가셋 30개(Q20).
- 이 ADR 이후에도 Phase 2 로직 파일은 만들지 않는다(§0.1-1). 소크가 끝나고 키가 들어오면 "다음 가자" 로 Phase 2 를 연다.
