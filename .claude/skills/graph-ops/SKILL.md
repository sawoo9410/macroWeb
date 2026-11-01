---
name: graph-ops
description: 거미줄 그래프 운영 — 노드/엣지 추가, 엔티티 해소(별칭 병합), 충격 전파, 경로 탐색, 시간 슬라이스 조회, vault/HTML 내보내기 명령과 규약. 그래프 관련 작업 전부에 사용.
---
# 규약 (PLAN §8)
- 노드 타입: person, org, country_bloc, policy, asset, product_tech, event, theme, indicator, scenario. 엣지 타입은 `src/macroweb/llm/schemas.py:RELATION_TYPES` (구조·권력·인과이익·통계·담론·시간). 모든 엣지는 `src→dst`, `sign ∈ {-1,0,1}`, `weight 0–1`, `confidence`, `valid_from/to`, **evidence[] 필수**.
- 2단계: 새 엔티티/엣지는 `candidate` → Story 3개 이상 또는 사람 승인 시 `confirmed`. evidence 없는 엣지는 거부된다(Q1 불변식).
- 시간: 직책 교체·동명이인은 `valid_from/to`; 조회는 항상 `--as-of`.
- 통계 엣지(correlates_with/leads)는 `uv run macroweb graph stats --pair <a> <b>` 로 **계산**한 r/lag 만(최근 2년 일별, lag −5~+30, |r| ≥ 0.3, 롤링 안정성). 추정 금지.
- 만료: 구조 365일 · 권력/이익 90일 · 발언 30일 미강화 시 `valid_to` (§0.4).

# 명령 (Phase 3 구현)
`uv run macroweb graph load-seed` · `graph add-entity --id --type --name --aliases` · `graph add-edge --src --dst --type --sign --weight --evidence <claim_id,...>` · `graph resolve --candidates` · `graph path <src> <dst> [--k 3]` · `graph propagate <shock_node> --sign ±1 --magnitude 1.0 --as-of <date>` · `graph diff --week` · `graph export-vault` · `graph render --week --nodes` · `graph html --week` (cytoscape.js 단일 파일).
# 금지
어보브반도체(abov)는 `conflict_of_interest=1` 유지. 시드 YAML(`seed/`)을 LLM 추출 결과로 덮어쓰지 않는다 — 시드는 사람이 검수한 베이스다.
