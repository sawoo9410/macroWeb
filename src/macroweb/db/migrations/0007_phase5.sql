-- 0007_phase5: 주간 레짐 스냅샷·논제 자동 채점 필드 (PLAN §9.2·§9.7).
CREATE TABLE IF NOT EXISTS regime_week (
  week TEXT PRIMARY KEY, as_of TEXT, regime_json TEXT, created_at TEXT);
ALTER TABLE thesis ADD COLUMN auto_json TEXT;
ALTER TABLE thesis ADD COLUMN created_at TEXT;
ALTER TABLE thesis ADD COLUMN scored_at TEXT;
