-- 匿名外观向量（ReID）
create table if not exists track_embeddings (
  trace_id   text primary key,
  camera_id  text,
  start_time timestamptz,
  embedding  jsonb,
  failed     boolean default false,
  created_at timestamptz default now()
);
create index if not exists idx_emb_time on track_embeddings(start_time);

-- 跨时段/跨镜关联
create table if not exists reid_links (
  id         serial primary key,
  a_trace    text,
  b_trace    text,
  similarity real,
  gap_s      real,
  same_camera boolean,
  created_at timestamptz default now(),
  unique(a_trace, b_trace)
);
create index if not exists idx_reid_a on reid_links(a_trace);
create index if not exists idx_reid_b on reid_links(b_trace);

-- 线索池扩展
alter table risk_clues add column if not exists clue_key text unique;
alter table risk_clues add column if not exists evidence_summary text;
