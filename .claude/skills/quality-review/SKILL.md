---
name: quality-review
description: 주간 데이터 품질 검토 Q1–Q7 (근거 무결성·시효·모순·중복/오염·소급 정정·커버리지·추출 감사)을 돌리고 스코어카드와 게이트 플래그를 만든다. weekly-report Step 0. "/quality-review 2026-W44".
argument-hint: "[YYYY-Www]"
disable-model-invocation: true
---
# 절차 (PLAN §10.5, config/quality.yaml)
WEEK = `$0`.
1. 결정론적 검사: `uv run macroweb quality run --week $WEEK` → `data/weekly/$WEEK/quality_raw.json` (Q1·Q2·Q4·Q6 는 SQL/파이썬, 자동 처리는 되돌릴 수 있는 것만: 상태 표시·만료·완전 일치 별칭 병합. **삭제 없음**).
2. 감사 샘플(Q7): `uv run macroweb quality audit --week $WEEK` (층별 10개 × 5 = 50 Story 를 기준 모델로 재추출, 배치 결과 회수) → 층별 오류율 e.
3. `data-steward` 서브에이전트에 `quality_raw.json` 을 주고: Q3 모순 판정(≤ 20건), Q6 원인 가림, Q7 오류 사례 상위 5개 → `docs/PROMPT_PROPOSALS.md`.
4. 산출: `reports/quality/$WEEK.md` (신호등·자동 처리 로그·미해결 큐·추이), `data/weekly/$WEEK/gate_flags.json`, `quality_run` 테이블 행.
5. 게이트 규칙(quality.yaml `gate`): Q1 실패 → 데이터팩 제외 / Q3 미해결 → [F] 금지 / Q5 정정 → 리포트 '정정' 섹션 필수 / Q6 빨강 → 새 논제 금지 / Q7 빨강 → 수치 [I] 강등 / 빨강 2개 이상 → 상단 배너 + 텔레그램.
품질이 나빠도 리포트는 나간다 — 대신 해당 부분을 빼거나 경고를 단다(PLAN §2-9).
