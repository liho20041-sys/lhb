#!/usr/bin/env python3
"""
轨迹记忆写入：Frigate 事件 -> PostgreSQL tracks
- 常驻轮询 Frigate /api/events
- 计算轨迹特征（时长/效率/反转/范围/速度/静止占比）
- 按 trace_id upsert，保留长期轨迹
"""
import json
import os
import time
import urllib.request
from datetime import datetime

import psycopg2

from features import compute, grid_cell, parse_points

FRIGATE = os.getenv("FRIGATE_URL", "http://127.0.0.1:5000")
CAMERA = os.getenv("CAMERA", "demo")
PG_DSN = os.getenv(
    "PG_DSN",
    "host=127.0.0.1 port=5432 dbname=prod_db user=prod_user password=SecurePwd@2025",
)
POLL = float(os.getenv("POLL_INTERVAL", "5"))
TRACK_LABELS = {"person", "bicycle", "car", "motorcycle", "bus", "truck"}
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "writer_state.json")


def log(*a):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}]", *a, flush=True)


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"last_event_ts": time.time() - 600}


def save_state(s):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(s, f)


def connect_pg():
    while True:
        try:
            c = psycopg2.connect(PG_DSN)
            c.autocommit = False
            log("PostgreSQL 已连接")
            return c
        except Exception as e:
            log("PG 连接失败:", e, "5s 后重试")
            time.sleep(5)


def fetch_events(after):
    url = f"{FRIGATE}/api/events?after={int(after)}&limit=300"
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read().decode())


def upsert_track(cur, e, feats):
    start = float(e.get("start_time") or 0)
    end = e.get("end_time")
    end_dt = datetime.fromtimestamp(float(end)) if end else None
    start_dt = datetime.fromtimestamp(start)
    path = [[p[0], p[1], p[2]] for p in parse_points((e.get("data") or {}).get("path_data"))]
    d = e.get("data") or {}
    quality = d.get("top_score") or d.get("score")
    trace_id = f"{CAMERA}:{e.get('id')}"
    cur.execute(
        """
        insert into tracks
          (trace_id, camera_id, label, start_time, end_time, duration_s, path,
           region_id, hour_bucket, weekday, quality_score, assoc_conf, features, scored)
        values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,false)
        on conflict (trace_id) do update set
          end_time = excluded.end_time,
          duration_s = excluded.duration_s,
          path = excluded.path,
          features = excluded.features,
          updated_at = now(),
          scored = case
            when tracks.end_time is distinct from excluded.end_time then false
            else tracks.scored
          end
        """,
        (
            trace_id,
            CAMERA,
            e.get("label"),
            start_dt,
            end_dt,
            feats["duration_s"],
            json.dumps(path),
            CAMERA,
            start_dt.hour,
            start_dt.weekday(),
            quality,
            1.0,
            json.dumps(feats),
        ),
    )
    return trace_id


def main():
    log(f"启动轨迹写入 Frigate={FRIGATE} camera={CAMERA} poll={POLL}s")
    conn = connect_pg()
    state = load_state()
    while True:
        try:
            now = time.time()
            after = max(state.get("last_event_ts", now - 600) - 2, now - 3600)
            events = fetch_events(after)
            n = 0
            with conn.cursor() as cur:
                for e in events:
                    if e.get("label") not in TRACK_LABELS:
                        continue
                    pts = parse_points((e.get("data") or {}).get("path_data"))
                    if len(pts) < 2:
                        continue
                    start = float(e.get("start_time") or pts[0][2])
                    end = e.get("end_time") or now
                    feats = compute(pts, start, end)
                    if not feats:
                        continue
                    feats["grid"] = grid_cell(pts)
                    upsert_track(cur, e, feats)
                    state["last_event_ts"] = max(float(state.get("last_event_ts", 0)), start)
                    n += 1
                conn.commit()
            save_state(state)
            if n:
                log(f"写入/更新 {n} 条轨迹")
        except Exception as e:
            log("循环异常:", repr(e))
            try:
                conn.rollback()
            except Exception:
                pass
            time.sleep(3)
        time.sleep(POLL)


if __name__ == "__main__":
    main()
