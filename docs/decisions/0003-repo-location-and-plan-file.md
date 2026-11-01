# ADR-0003 — 레포 위치·PLAN.md·원격 저장소·실행 환경

- 상태: 확정 · 날짜: 2026-11-01 · Phase 0

## 맥락
PLAN 은 레포 이름을 `macroweb/`, 경로를 `/Users/sawoo/macroweb`(부록 H) 로 적었고 문서 파일명은 `MACROWEB_PLAN_v0.3.md` 였다. 사용자가 기록 보관처로 `https://github.com/sawoo9410/macroWeb.git` 를 지정했다.

## 결정
1. 레포 루트 = `/Users/seosang-u/projects/finance/macroWeb` (기존 finance 프로젝트 관례). plist·래퍼의 절대경로는 이 값. uid 501.
2. `MACROWEB_PLAN_v0.3.md` 를 `PLAN.md` 로 **이름 변경**(복사가 아니라 이동 — SSOT 가 둘이 되지 않게). 버전은 문서 머리 표에 있다. 다음 개정은 `PLAN.md` 를 직접 고치고 머리 표의 버전을 올린다.
3. 원격 `origin = https://github.com/sawoo9410/macroWeb.git`, 기본 브랜치 `main`. 커밋 제목 영문 1줄, 트레일러(`Co-Authored-By`) 허용.
4. 원격 저장소는 생성 시점(2026-11-01 14:01 UTC) 기준 **PUBLIC** 이다. `private/`·`data/`·`logs/`·`.env*` 는 `.gitignore` 로 제외되지만 `PLAN.md` 자체에 재직사·통근 경로·포트폴리오 구성이 적혀 있다. 공개 범위 결정은 사용자 몫(QUESTIONS Q1). 비밀값은 어떤 경우에도 커밋하지 않는다(훅 + deny 규칙).
5. 실행 환경: `uv`(brew) + uv 관리 Python 3.12.16(`.python-version`). 시스템 Python 3.9 는 훅 스크립트만 쓴다(stdlib, 3.9 호환 문법 유지 — `ruff` per-file-ignores 로 UP 규칙 제외).
6. 홈 디렉터리의 `~/CLAUDE.md`(home-organize 프로젝트 규칙)와 `~/.claude/CLAUDE.md`(전역 규칙)는 이 레포에도 적용된다. 특히 비밀값 파일 금독·`git add -A` 금지·개인정보 외부 전송 전 확인은 `CLAUDE.md` 불변 규칙 7–9 로 흡수했다.

## 결과
- 플랜의 `macroweb/` 표기는 디렉터리 `macroWeb` 을 가리키는 것으로 읽는다(코드 패키지명은 `macroweb`).
- 다른 세션이 동시에 작업하면 전역 규칙대로 worktree(`git worktree add ../macroWeb-<주제>`)를 쓰고 `.venv`·`private/`·`data/` 를 심링크한다(데이터·DB 는 공유, 수집·DB 쓰기는 main 체크아웃에서만).
