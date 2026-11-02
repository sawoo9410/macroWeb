-- 0003_phase2 (ADR-0006): Phase 2 인터페이스만 — 배치 원장, Story 별 추출 멱등 키, 검토 큐, Story 선별 컬럼.
-- 추출·검증 로직은 Phase 1 DoD(3일 무인 실행) 통과 후 들어간다 (PLAN §0.1-1 예외: 스키마는 미리).
CREATE TABLE IF NOT EXISTS llm_batch (
  id TEXT PRIMARY KEY, provider_batch_id TEXT, job TEXT, model_tier TEXT, prompt_version TEXT,
  submitted_at TEXT, ended_at TEXT, status TEXT, n_requests INTEGER DEFAULT 0, n_succeeded INTEGER DEFAULT 0,
  n_errored INTEGER DEFAULT 0, cost_usd REAL DEFAULT 0, result_path TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS extraction (
  story_id TEXT REFERENCES story(id), prompt_version TEXT, model_tier TEXT, custom_id TEXT UNIQUE,
  batch_id TEXT REFERENCES llm_batch(id),
  status TEXT DEFAULT 'queued' CHECK (status IN ('queued','submitted','succeeded','failed','quarantined','escalated')),
  stratum TEXT, escalation_reason TEXT, result_json TEXT, error TEXT, tokens_in INTEGER, tokens_out INTEGER,
  cost_usd REAL, created_at TEXT, updated_at TEXT,
  PRIMARY KEY (story_id, prompt_version, model_tier));
CREATE TABLE IF NOT EXISTS review_queue (
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, claim_id TEXT REFERENCES claim(id), story_id TEXT REFERENCES story(id),
  reason TEXT, payload_json TEXT, created_at TEXT, decided_at TEXT,
  decision TEXT CHECK (decision IN ('approve','reject','unsure')), decided_by TEXT);
ALTER TABLE story ADD COLUMN stratum TEXT;
ALTER TABLE story ADD COLUMN lang TEXT;
ALTER TABLE story ADD COLUMN rep_article_id TEXT;
ALTER TABLE story ADD COLUMN impact REAL;
ALTER TABLE story ADD COLUMN selected_at TEXT;
CREATE INDEX IF NOT EXISTS idx_extraction_status ON extraction(status, created_at);
CREATE INDEX IF NOT EXISTS idx_review_open ON review_queue(decided_at);
