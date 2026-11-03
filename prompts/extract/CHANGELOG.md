# prompts/extract CHANGELOG
- v1 (2026-11-01): PLAN 부록 C 골격 + §6.1 스키마(`macroweb.llm.schemas.ExtractionResult`). Phase 2 평가셋 30개로 첫 측정 예정.
- v2 (2026-11-03): claim.text 는 원문 언어(검증 단계 원문 대조용), time_ref 는 원문 날짜만, 본문 없으면 claims=[] + red_flags=["no_body"]. 첫 실주행 3건(ECB, 본문 없음)에서 v1 이 한국어 번역 claim 과 추정 날짜를 만든 것을 보고 수정.
