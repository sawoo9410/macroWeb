---
name: ping-pong-debate
description: 논제 1개를 Proponent(편집자 입장) ↔ Skeptic 3라운드로 토론시키고 judge 가 판정하게 한다. 새 근거는 DB 의 claim 만. 고영향·저신뢰 claim 의 검증 레드팀(신호 12)에도 쓴다. "/ping-pong-debate <thesis_id>".
argument-hint: "[thesis_id]"
disable-model-invocation: true
---
# 프로토콜 (PLAN §10.3 — ping-pong debate 시스템을 스킬로 흡수)
입력: `data/weekly/$WEEK/theses_draft.md` 의 논제 `$0` + 근거 claim_ids.
로그: `reports/debates/$WEEK-$0.md` (append-only; 월간 회고가 "어느 쪽이 맞았나"를 채점한다).

1. **라운드 1** — Proponent(편집자 입장, chief-editor 메모를 근거로 ≤ 300 단어) → Skeptic(`skeptic-red-team`, ≤ 300 단어: 반대 논거·틀릴 신호 2개·대안 가설+확률).
2. **라운드 2·3** — 각자 상대의 직전 논거에 직접 답한다. 새 근거는 `uv run macroweb claim search` 로 찾은 **DB 의 claim 만** 인용(claim_id 필수). 외부 지식으로 사실을 만들지 못한다.
3. **판정** — `judge` 가 로그만 읽고 (a) 채택/수정/기각 (b) 확률 (c) 가장 강한 반대 논거 1개 → 그 반론이 리포트 "반대 시나리오"에 들어간다.
4. 예산: 논제당 호출 ≤ 7회. 주간 단독 예산 초과 시 라운드 3→2 (models.yaml budget).

검증 레드팀 모드(`--claim <claim_id>`): Prosecutor(skeptic) vs Defender 3라운드 → judge 가 confidence 보정값과 라벨 제안을 낸다(§7.2 신호 12). 결과는 `review/$WEEK.md` 에 기록하고 라벨 변경은 사람이 승인.
