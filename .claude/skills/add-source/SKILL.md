---
name: add-source
description: 수집 소스를 추가한다 — sources.yaml 항목 → 실제 요청 probe → 픽스처 저장 → 골든 테스트 → make doctor → 커밋. "소스 추가: TrendForce", "add source", "/add-source <id>" 요청 시. 어댑터 없이 소스를 추가하지 않는다.
argument-hint: "[source_id]"
---
# 절차 (PLAN §4.5, §4.3)
1. `config/sources.yaml` 에 항목 추가 — 스키마는 `src/macroweb/config.py:Source` (id slug, tier 0–5, kind rss|html|api|playwright|pdf|json, url, lang, topics, parent_org(전재·독립성 판정용), parser, rate_limit_s ≥ 2, paywall, stratum S-*, auth_env(키 **이름**만), probe_url). 유료 벽이면 `paywall: true` → 제목·리드·링크만.
2. `uv run macroweb config validate --path config/sources.yaml`.
3. `uv run macroweb source probe <id>` — 실제 요청(일반 UA, 키 없음). 403/404 면 대체 URL 을 찾거나 `enabled: false` + notes.
4. 어댑터: `src/macroweb/collect/fetchers/` 의 해당 kind 에 파서 함수 `parse_<parser>()` (Phase 1 골격 참조). 소스 1개 = 어댑터 1개.
5. 응답 스냅샷을 `tests/fixtures/<id>/` 에 저장(날짜 포함 파일명, 개인정보·쿠키 제거) → 골든 테스트 `tests/golden/test_<id>.py` (네트워크 호출 금지 — 픽스처만).
6. robots.txt 확인(`uv run macroweb source robots <id>`, Phase 1) · 도메인당 동시 1연결 · 간격 ≥ 2s.
7. `make doctor` 통과 → `git add config/sources.yaml tests/fixtures/<id> tests/golden/test_<id>.py src/...` → 영문 1줄 커밋.
외부 요청 헤더에 이메일 등 개인정보가 필요한 소스(SEC EDGAR)는 사용자에게 먼저 묻는다(docs/QUESTIONS.md Q3).
