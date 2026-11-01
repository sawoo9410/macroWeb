-- MacroWeb schema v1 — PLAN 부록 A + claim 상태 컬럼(status/superseded_by/extracted_by/stratum/escalation_reason)
-- + run 비용 컬럼(model_tier/cost_usd). 이후 변경은 migrations/NNNN_*.sql 로만 (ADR 필요).
CREATE TABLE IF NOT EXISTS schema_version (
  version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, note TEXT);

CREATE TABLE IF NOT EXISTS source (
  id TEXT PRIMARY KEY, name TEXT, tier INTEGER, kind TEXT, url TEXT, lang TEXT,
  country TEXT, topics TEXT, paywall INTEGER DEFAULT 0, enabled INTEGER DEFAULT 1, parser TEXT,
  rate_limit_s REAL DEFAULT 2.0, parent_org TEXT, stratum TEXT);
CREATE TABLE IF NOT EXISTS source_stats (
  source_id TEXT PRIMARY KEY REFERENCES source(id), credibility REAL,
  n_claims INTEGER DEFAULT 0, n_confirmed INTEGER DEFAULT 0, n_refuted INTEGER DEFAULT 0,
  health TEXT DEFAULT 'ok', last_ok_at TEXT, consecutive_failures INTEGER DEFAULT 0, updated_at TEXT);

CREATE TABLE IF NOT EXISTS article (
  id TEXT PRIMARY KEY, url TEXT, canonical_url TEXT UNIQUE, source_id TEXT REFERENCES source(id),
  title TEXT, author TEXT, published_at TEXT, fetched_at TEXT, lang TEXT, text TEXT, text_ko TEXT,
  raw_path TEXT, sha256 TEXT, paywalled INTEGER DEFAULT 0, status TEXT DEFAULT 'new');
CREATE VIRTUAL TABLE IF NOT EXISTS article_fts USING fts5(
  title, text, content='article', content_rowid='rowid', tokenize='trigram');
CREATE TRIGGER IF NOT EXISTS article_ai AFTER INSERT ON article BEGIN
  INSERT INTO article_fts(rowid, title, text) VALUES (new.rowid, new.title, new.text);
END;
CREATE TRIGGER IF NOT EXISTS article_ad AFTER DELETE ON article BEGIN
  INSERT INTO article_fts(article_fts, rowid, title, text) VALUES ('delete', old.rowid, old.title, old.text);
END;
CREATE TRIGGER IF NOT EXISTS article_au AFTER UPDATE ON article BEGIN
  INSERT INTO article_fts(article_fts, rowid, title, text) VALUES ('delete', old.rowid, old.title, old.text);
  INSERT INTO article_fts(rowid, title, text) VALUES (new.rowid, new.title, new.text);
END;

CREATE TABLE IF NOT EXISTS story (
  id TEXT PRIMARY KEY, first_seen TEXT, last_seen TEXT, title_rep TEXT,
  n_articles INTEGER DEFAULT 0, n_independent INTEGER DEFAULT 0, theme_ids TEXT, embedding_id TEXT, summary_ko TEXT);
CREATE TABLE IF NOT EXISTS story_article (
  story_id TEXT REFERENCES story(id), article_id TEXT REFERENCES article(id), is_syndicated INTEGER DEFAULT 0,
  PRIMARY KEY (story_id, article_id));

CREATE TABLE IF NOT EXISTS entity (
  id TEXT PRIMARY KEY, type TEXT, canonical_name TEXT, aliases TEXT, wikidata_qid TEXT,
  country TEXT, sector TEXT, profile_json TEXT, status TEXT DEFAULT 'candidate', valid_from TEXT, valid_to TEXT,
  conflict_of_interest INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS claim (
  id TEXT PRIMARY KEY, story_id TEXT REFERENCES story(id), text TEXT, type TEXT, subject_eid TEXT, predicate TEXT,
  object_eid TEXT, value REAL, unit TEXT, time_ref TEXT, confidence REAL, label TEXT, impact REAL,
  signals_json TEXT, first_seen TEXT, last_updated TEXT,
  status TEXT DEFAULT 'active' CHECK (status IN ('active','superseded','expired','retracted','quarantined')),
  superseded_by TEXT, extracted_by TEXT, stratum TEXT, escalation_reason TEXT);
CREATE TABLE IF NOT EXISTS evidence (
  id TEXT PRIMARY KEY, claim_id TEXT REFERENCES claim(id), article_id TEXT REFERENCES article(id),
  span_start INTEGER, span_end INTEGER, kind TEXT CHECK (kind IN ('supports','contradicts','primary_doc','data_api')), note TEXT);

CREATE TABLE IF NOT EXISTS relation (
  id TEXT PRIMARY KEY, src_eid TEXT REFERENCES entity(id), dst_eid TEXT REFERENCES entity(id), type TEXT,
  sign INTEGER CHECK (sign IN (-1,0,1)), weight REAL, confidence REAL, lag_days INTEGER, r REAL,
  valid_from TEXT, valid_to TEXT, evidence_ids TEXT, last_reinforced TEXT,
  origin TEXT CHECK (origin IN ('seed','extracted','computed')), status TEXT DEFAULT 'candidate', note TEXT);

CREATE TABLE IF NOT EXISTS thesis (
  id TEXT PRIMARY KEY, week TEXT, text TEXT, horizon_date TEXT, probability REAL,
  falsifier TEXT, status TEXT, outcome INTEGER, brier REAL, debate_path TEXT, claim_ids TEXT);
CREATE TABLE IF NOT EXISTS report_citation (
  report_week TEXT, claim_id TEXT, relation_id TEXT, section TEXT);
CREATE TABLE IF NOT EXISTS quality_run (
  week TEXT PRIMARY KEY, q1_fail INTEGER, q2_expired INTEGER, q2_superseded INTEGER,
  q3_open INTEGER, q4_merged INTEGER, q4_flood_source TEXT, q5_errata INTEGER, q6_json TEXT, q7_json TEXT, status_json TEXT);

CREATE TABLE IF NOT EXISTS run (
  id TEXT PRIMARY KEY, job TEXT, started_at TEXT, ended_at TEXT, status TEXT, stats_json TEXT,
  prompt_versions TEXT, tokens_in INTEGER DEFAULT 0, tokens_out INTEGER DEFAULT 0,
  model_tier TEXT, cost_usd REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS market (
  date TEXT, key TEXT, value REAL, source TEXT, PRIMARY KEY (date, key));

CREATE INDEX IF NOT EXISTS idx_claim_label ON claim(label, impact);
CREATE INDEX IF NOT EXISTS idx_claim_story ON claim(story_id);
CREATE INDEX IF NOT EXISTS idx_rel_src ON relation(src_eid, type);
CREATE INDEX IF NOT EXISTS idx_rel_dst ON relation(dst_eid, type);
CREATE INDEX IF NOT EXISTS idx_article_source ON article(source_id, fetched_at);
CREATE INDEX IF NOT EXISTS idx_run_job ON run(job, started_at);
