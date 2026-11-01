# seed/ — 사람이 검수한 시드 (PLAN §8.5, 부록 E)

- `entities.yaml` · `relations.yaml`: 핵심 노드/엣지 시드. **전부 `needs_evidence: true`** — Phase 3 로드 시 `candidate` 로 들어가고, evidence(claim_id)가 붙어야 `confirmed`. 통계 엣지(`origin: computed`)의 r/lag 는 가격 데이터로 계산해 채운다(추정 금지).
- `persons/*.yaml`: 인물 카드 시드(§8.3). 현직 여부 ⚠️ 2026-11 기준 검증.
- `claims_to_verify.yaml`: PLAN §1.5 "지금 이 순간의 맥락 시드" — 사실이 아니라 **검증 대상 claim**. Phase 2 검증 레이어의 첫 실전 테스트.
목표 규모: 200 노드 / 500 엣지 (Phase 3 DoD). 지금은 부록 E 의 20 노드 / 17 엣지.
