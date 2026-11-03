# ADR-0008 — Phase 1 소크(3일 무인 실행)가 끝나기 전에 Phase 2 를 시작한다

- 상태: 확정(사용자 결정 2026-11-03: "3일 기다리지 말고 Phase 2 시작하자") · PLAN §0.1-1(Phase 순서) 과 충돌하며 **이 ADR 이 이긴다**.

## 맥락
Phase 1 DoD 중 남은 둘은 코드가 아니라 시간(`unattended-3d`, 2026-11-05 23:15 KST 까지)과 Phase 2 의존(`launchd-daily`)이다. 수집 계층은 테스트 140개·실수집·launchd 첫 실행으로 검증됐고, 소크는 "launchd 아래에서 3일간 깨지지 않는가"를 확인하는 단계라 Phase 2 코드를 쓰는 것과 서로 간섭하지 않는다.

## 결정
1. `docs/phase_status.json` 의 `current_phase` 를 2 로 올리고, Phase 1 의 미완료 항목은 `carry_over` 로 남겨 계속 추적한다. Phase 2 를 "끝났다"고 선언하려면 이월 항목도 닫혀야 한다.
2. 소크 기간의 규칙: launchd `collect` 잡의 명령(`bin/run_collect.sh`)은 Phase 2 가 `tick`(수집 → 추출 ≤ 틱당 15 → 검증)으로 교체하기 전까지 손대지 않는다. 교체 시점은 추출·검증이 단위 테스트와 수동 실행으로 확인된 뒤이며, 교체 자체가 소크의 일부가 된다(실패하면 되돌리고 기록).
3. Phase 2 DoD 는 PLAN §14 그대로(추출 v1·claim/entity·검증 신호 1·2·4·5·6·다이제스트·평가셋 30·라우팅 실험·T0 diff·첫 수동 리포트). 배치 API 항목은 ADR-0007 의 headless 분산 처리로 읽는다.

## 결과
- 2026-11-03 부터 Phase 2 작업 시작. `unattended-3d` 는 11-05 저녁에 `fetch_log` 로 판정(3일 동안 틱 누락·degraded 없음).
