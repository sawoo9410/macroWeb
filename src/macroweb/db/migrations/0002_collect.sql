-- 0002_collect (Phase 1, ADR-0004): 수집 스케줄 상태·fetch 로그·기사 중복제거 컬럼.
-- schema.sql(v1)은 수정하지 않는다. simhash 는 64비트라 SQLite 부호 있는 INTEGER 를 넘을 수 있어 16자리 hex TEXT 로 저장.
ALTER TABLE source ADD COLUMN fetch_body INTEGER DEFAULT 0;
ALTER TABLE source_stats ADD COLUMN last_fetch_at TEXT;
ALTER TABLE source_stats ADD COLUMN next_due_at TEXT;
ALTER TABLE source_stats ADD COLUMN interval_s INTEGER;
ALTER TABLE source_stats ADD COLUMN feed_window_s INTEGER;
ALTER TABLE source_stats ADD COLUMN etag TEXT;
ALTER TABLE source_stats ADD COLUMN last_modified TEXT;
ALTER TABLE source_stats ADD COLUMN last_status INTEGER;
ALTER TABLE source_stats ADD COLUMN last_error TEXT;
ALTER TABLE source_stats ADD COLUMN n_fetches INTEGER DEFAULT 0;
ALTER TABLE source_stats ADD COLUMN n_items_total INTEGER DEFAULT 0;
ALTER TABLE article ADD COLUMN summary TEXT;
ALTER TABLE article ADD COLUMN title_simhash TEXT;
ALTER TABLE article ADD COLUMN body_status TEXT DEFAULT 'none';
ALTER TABLE article ADD COLUMN extra_json TEXT;
ALTER TABLE story ADD COLUMN title_simhash TEXT;
CREATE TABLE IF NOT EXISTS fetch_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, source_id TEXT REFERENCES source(id), fetched_at TEXT, status INTEGER,
  not_modified INTEGER DEFAULT 0, items_seen INTEGER DEFAULT 0, items_new INTEGER DEFAULT 0,
  market_points INTEGER DEFAULT 0, bytes INTEGER DEFAULT 0, elapsed_ms INTEGER, error TEXT, raw_path TEXT, run_id TEXT);
CREATE INDEX IF NOT EXISTS idx_fetch_log_source ON fetch_log(source_id, fetched_at);
CREATE INDEX IF NOT EXISTS idx_article_simhash ON article(title_simhash);
CREATE INDEX IF NOT EXISTS idx_article_published ON article(published_at);
