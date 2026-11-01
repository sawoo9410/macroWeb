# eval/extraction — 추출 평가셋 (Phase 2 DoD: 30 Story, 한/영 반반)
파일: `NNN.json` = `{story_id, source_id, stratum, text_path(tests/fixtures/...), gold: ExtractionResult}`. 라벨러: 상우(층당 10) + Opus 추출(층당 10, 3개 스팟체크). 지표: claim F1(주어·술어·값), 수치 오류율, 관계 부호 오류율, Story당 비용. `make eval-extract` 가 회귀 실행.
