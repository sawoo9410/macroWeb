---
name: monthly-review
description: 매월 1일 학습 루프(Track C) — 논제 Brier 채점·캘리브레이션, 출처 신뢰도 베이지안 갱신(층별 오류율 할인), 검증기 재학습·롤백, 그래프 정리, 토론 채점, 투자일기용 '이달의 거시 배경', 비용 집계. "/monthly-review 2026-11".
argument-hint: "[YYYY-MM]"
disable-model-invocation: true
---
# 절차 (PLAN §12, Phase 7)
MONTH = `$0`.
1. `uv run macroweb monthly score --month $MONTH` — 만기 논제 outcome(데이터 API 자동, 애매하면 review 큐) → Brier, 캘리브레이션 곡선. 예측시장 가격이 있던 논제는 시장 Brier 대비 차이를 적는다(목표 +0.02 이내).
2. `uv run macroweb monthly credibility --month $MONTH` — 소스별 claim 라벨 분포 → credibility 갱신(prior 강도 20). 반박 1건 가중치 = `1 − e(층)` (§6.2.5). 4주 품질 스코어카드 추세 첨부.
3. `make eval-verify` → §7.2 가중치 로지스틱 회귀 재학습. F1 하락 시 **롤백**. 주중엔 바꾸지 않는다.
4. `uv run macroweb graph prune --month $MONTH` — 종류별 만료(구조 365·권력/이익 90·발언 30일), candidate 정리, 중심성 월간 추이.
5. 토론 채점: judge 가 기각했는데 맞았던 논제 / 채택했는데 틀린 논제 → `docs/PROMPT_PROPOSALS.md` 에 skeptic/editor 개선 메모.
6. 산출: `digests/monthly-review-$MONTH.md` (위 전부 + 비용 집계 `make cost` 실측 대비) · `digests/monthly-macro-$MONTH.md` ("이달의 거시 배경" 10줄 — 주간 리포트 4개 압축, 투자일기 초안 입력).
7. 라우팅 재판정: 층별 e > 0.15 인 층은 §6.2.4 축소 실험(층당 10개) 후 `config/models.yaml routing` 갱신 + ADR.
