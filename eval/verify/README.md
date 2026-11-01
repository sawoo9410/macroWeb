# eval/verify — 검증 평가셋 (Phase 6 DoD: 200 claim, 참 100 / 거짓·과장·재탕 100)
출처: 팩트체크 기관 아카이브(SNU팩트체크·Reuters/AP/AFP Fact Check) + 과거 실제 정정 사례 + 합성 케이스(날짜 바꾼 재탕). 이중 라벨(상우 + 하네스), 불일치만 사람 확정. 월 1회 `make eval-verify` → label 별 P/R/F1, 목표 F1 ≥ 0.85.
