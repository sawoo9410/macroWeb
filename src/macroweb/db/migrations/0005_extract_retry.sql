-- 0005_extract_retry (Phase 2): 일시 오류(하네스·네트워크)로 실패한 추출을 몇 번 재시도했는지 — 선별이 재시도 상한·쿨다운을 적용한다.
ALTER TABLE extraction ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0;
