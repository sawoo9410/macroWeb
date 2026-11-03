---
name: weekly-report
description: 주간 거미줄 리포트를 생성한다 — 품질 검토 → 데이터팩 → 분석가 병렬 → 편집 → ping-pong 토론 → 작성 → fact-check 게이트 → 차트 → 발행. "주간 리포트", "weekly", "/weekly-report 2026-W44" 요청 시. launchd 의 claude -p 헤드리스 진입점(ADR-0002).
argument-hint: "[YYYY-Www]"
disable-model-invocation: true
---
# 주간 리포트 절차 (PLAN §10.2, 부록 G) — 각 단계 산출물 경로 고정

WEEK = `$0` (없으면 `uv run python -c 'import datetime as d;print(d.date.today().strftime("%G-W%V"))'`).
작업 디렉터리 `data/weekly/$WEEK/`. **실패해도 부분 산출물을 지우지 않는다.** 각 단계 끝에 `uv run macroweb weekly record --week $WEEK --step <n> --status ok|failed`.

0. **품질 검토** — `/quality-review $WEEK` (data-steward). 산출: `reports/quality/$WEEK.md`, `data/weekly/$WEEK/gate_flags.json` (제외 엣지·경고 테마·정정 목록).
1. **데이터팩** — `uv run macroweb weekly pack --week $WEEK` → `pack.json` (테마 상위 10, 검증 claims 상위 100(impact 순), 그래프 diff, 전파 결과, 정합성 불일치, 레짐 표, 캘린더 2주, 가격 테이블, 지난 논제 채점; 게이트 플래그 반영).
2. **병렬 메모 6개** — 서브에이전트 `macro-rates-analyst`, `policy-politics-analyst`, `semis-ai-analyst`, `korea-desk`, `graph-cartographer`, `historian` 를 **동시에** 호출. 각자 pack.json 의 자기 슬라이스만 읽는다(서로의 메모를 주지 않는다). 산출 `memos/<name>.md`.
3. **편집** — `chief-editor` → `theses_draft.md` (논제 3–5, 한 줄 요약, 레짐, 구조, 정정 판단).
4. **토론** — 논제마다 `/ping-pong-debate <thesis_id>` (skeptic-red-team ↔ editor 3라운드) → `reports/debates/$WEEK-<id>.md`; 끝나면 `judge` → `theses_final.json`.
5. **작성** — `writer-ko` → `draft.md` (템플릿 `reports/_template.md`, 모든 [F] 에 claim_id).
6. **게이트** — 먼저 결정론 게이트 `uv run macroweb weekly gate --week $WEEK` (claim_id 존재·라벨·수치·금지 표현·격리 라벨·포트폴리오 금액; `gate.json` 저장), 그다음 `fact-checker` 가 의미 검수. 둘 중 하나라도 FAIL 이면 5 를 **1회만** 재시도(위반 목록만 수정) 후 `draft_final.md` 로 저장. 재실패 → 중단, `uv run macroweb notify --level error --job weekly --tail 3`.
7. **차트** — `chart-maker` → `charts/$WEEK/*.png` + `chart_captions.json`; writer 가 캡션 삽입.
8. **발행** — `publisher` 는 직접 파일을 만들지 않고 `uv run macroweb weekly publish --week $WEEK` 를 부른다(게이트 PASS 일 때만 `reports/$WEEK.md`, `vault/weekly/$WEEK.md`, `drafts/blog-$WEEK.md`(포트폴리오 섹션 제외), 알림을 만든다). 헤드리스 러너(`macroweb weekly run`)도 claude 가 끝난 뒤 같은 게이트·발행을 한 번 더 돌린다 — 두 번 실행해도 결과는 같다.
9. **기록** — run 테이블(토큰·시간·게이트 결과). 예산: 전체 ≤ 60분, 주간 단독 $8 초과 시 토론 라운드 3→2 (models.yaml budget).

규칙: 출처 없는 숫자·URL 금지 · 매수/매도 지시 금지 · `private/` 읽기 금지 · 헤드리스(-p)에서는 질문하지 말고 기본값으로 진행하되 결정을 `data/weekly/$WEEK/decisions.md` 에 적는다.
