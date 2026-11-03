-- 0004_extract_v1 (Phase 2): 추출 결과에 쓰인 정확한 모델 id, claim 의 원문 주어/목적어·언어.
ALTER TABLE extraction ADD COLUMN model TEXT;
ALTER TABLE claim ADD COLUMN raw_subject TEXT;
ALTER TABLE claim ADD COLUMN raw_object TEXT;
ALTER TABLE claim ADD COLUMN lang TEXT;
CREATE INDEX IF NOT EXISTS idx_claim_subject ON claim(subject_eid);
CREATE INDEX IF NOT EXISTS idx_claim_status ON claim(status, label);
