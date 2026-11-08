-- 轨迹记忆库
create table if not exists tracks (
  trace_id        text primary key,
  camera_id       text,
  label           text,
  start_time      timestamptz,
  end_time        timestamptz,
  duration_s      real,
  path            jsonb,
  region_id       text,
  hour_bucket     int,
  weekday         int,
  quality_score   real,
  assoc_conf      real,
  features        jsonb,
  scored          boolean default false,
  created_at      timestamptz default now(),
  updated_at      timestamptz default now()
);
create index if not exists idx_tracks_start on tracks(start_time);
create index if not exists idx_tracks_region on tracks(region_id, hour_bucket);
create index if not exists idx_tracks_unscored on tracks(scored) where scored = false;

-- 正常基线
create table if not exists baselines (
  id          serial primary key,
  region_id   text,
  hour_bucket int default -1,
  weekday     int default -1,
  crowd_level text default 'all',
  model       jsonb,
  sample_n    int,
  updated_at  timestamptz default now(),
  unique(region_id, hour_bucket, weekday, crowd_level)
);

-- 偏离候选（不是告警）
create table if not exists deviation_candidates (
  id         serial primary key,
  trace_id   text unique,
  score      real,
  reason     jsonb,
  status     text default 'pending',
  created_at timestamptz default now()
);
create index if not exists idx_dev_status on deviation_candidates(status);

-- 线索池（Phase 2 用）
create table if not exists risk_clues (
  id         serial primary key,
  clue_type  text,
  score      real,
  evidence   jsonb,
  status     text default 'pending',
  created_at timestamptz default now()
);
