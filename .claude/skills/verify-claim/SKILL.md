---
name: verify-claim
description: claim 하나를 수동으로 검증한다 — 12개 신호 루브릭으로 confidence 와 라벨(VERIFIED/CORROBORATED/SINGLE_SOURCE/DISPUTED/DEBUNKED/UNVERIFIABLE/RECYCLED/SPAM_SATIRE)을 매기고 review 큐에 기록한다. "이 claim 검증해줘", "/verify-claim <claim_id>".
argument-hint: "[claim_id]"
---
# 루브릭 (PLAN §7.1–7.4)
`uv run macroweb claim get $0` 로 claim·evidence·Story 의 기사 목록을 본 뒤 신호를 하나씩 채운다:
1. 출처 prior(`source_stats.credibility`) 2. 독립 교차검증 수(모회사 다름·본문 유사도 < 0.8·서로 인용 아님; 연합 전재는 제외) 3. 1차 출처 역추적(성명·공시·통계 원문 fetch → 수치/문장 존재) 4. 수치 검증(FRED/ECOS/KRX 값, `config/tolerances.yaml`) 5. 시간 일관성(90일 이상 전 유사 Story → RECYCLED 후보) 6. 언어 신호(`prompts/verify/v1.md` 루브릭) 7. 도메인 위험 8. 루머 생명주기(T4 최초 → 2 영업일 내 T0/T1 확인 없음) 9. 정정·반박 감시(IR 부인·조회공시·팩트체크) 10. 시장 반응 정합성 11. 생성 콘텐츠 신호 12. (고영향·저신뢰면) `/ping-pong-debate --claim $0`.
점수식(초기값): `logit = 1.2·prior + 0.9·log1p(n_indep) + 1.5·primary + 1.5·numeric − 0.8·recycled − 0.7·lang − 1.0·domain − 0.6·rumor + 0.3·market − 2.0·debunked`. 규칙 우선: debunked → DEBUNKED, primary=1 → VERIFIED.
함정 목록 `config/traps.yaml` 을 대조한다(단위 혼동·외신 종합·전망치≠확정치·예측시장 수치).
출력: `review/YYYY-MM-DD.md` 에 `| claim_id | 제안 라벨 | confidence | 결정적 신호 | approve/reject/unsure(사람) |` 한 줄 추가. DB 라벨 변경은 `uv run macroweb verify apply` 로만(사람 승인 후).
