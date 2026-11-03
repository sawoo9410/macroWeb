-- 0006_graph_v1 (Phase 3): 그래프 운영 카운터·병합 이력·주간 스냅샷 (PLAN §8.4·§8.6).
ALTER TABLE entity ADD COLUMN n_stories INTEGER NOT NULL DEFAULT 0;
ALTER TABLE entity ADD COLUMN merged_into TEXT;
ALTER TABLE relation ADD COLUMN n_stories INTEGER NOT NULL DEFAULT 0;
CREATE TABLE IF NOT EXISTS graph_snapshot (
  week TEXT PRIMARY KEY, taken_at TEXT, as_of TEXT, n_nodes INTEGER, n_edges INTEGER, edge_ids_json TEXT, stats_json TEXT);
CREATE INDEX IF NOT EXISTS idx_relation_src ON relation(src_eid, status);
CREATE INDEX IF NOT EXISTS idx_relation_dst ON relation(dst_eid, status);
CREATE INDEX IF NOT EXISTS idx_claim_story ON claim(story_id);
