#!/usr/bin/env python3
"""
偏离评分：把不在正常基线里的轨迹写入 deviation_candidates（候选池）
- 对每个已结束的轨迹，按 区域×小时 -> 区域全天 -> 全局 依次找基线
- 稳健 z-score：|x - median| / (1.4826 * MAD)
- 超过阈值才进候选池，不直接告警
"""
import argparse
import json
import os
import time
from datetime import datetime

import psycopg2

from features import FEATURES, FEATURE_FLOOR
from deviation_text import describe_reason

PG_DSN = os.getenv(
    "PG_DSN",
    "host=127.0.0.1 port=5432 dbname=prod_db user=prod_user password=SecurePwd@2025",
)
THRESHOLD = float(os.getenv("DEVIATION_THRESHOLD", "8.0"))
BATCH = int(os.getenv("BATCH_SIZE", "500"))
POLL = float(os.getenv("POLL_INTERVAL", "30"))
SCORE_FEATURES = [
    "duration_s", "path_efficiency", "reversals", "path_ratio",
    "extent_ratio", "mean_speed", "dwell_ratio", "n_points",
]


def log(*a):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}]", *a, flush=True)


def connect_pg():
    while True:
        try:
            c = psycopg2.connect(PG_DSN)
            c.autocommit = False
            return c
        except Exception as e:
            log("PG 连接失败:", e, "5s 后重试")
            time.sleep(5)


def get_baseline(cur, region, hour):
    for r, h in ((region, hour), (region, -1), ("*", -1)):
        cur.execute(
            "select model from baselines where region_id=%s and hour_bucket=%s "
            "and weekday=-1 and crowd_level='all' order by updated_at desc limit 1",
            (r, h),
        )
        row = cur.fetchone()
        if row and row[0]:
            return row[0]
    return None


def score_once(conn):
    with conn.cursor() as cur:
        cur.execute(
            "select trace_id, region_id, hour_bucket, features from tracks "
            "where end_time is not null and scored = false and features is not null "
            "order by start_time asc limit %s",
            (BATCH,),
        )
        rows = cur.fetchall()

        scored = 0
        candidates = 0
        for trace_id, region, hour, feats in rows:
            base = get_baseline(cur, region or "*", int(hour) if hour is not None else -1)
            if not base:
                continue
            zs = []
            for f in SCORE_FEATURES:
                v = feats.get(f)
                b = base.get(f)
                if not isinstance(v, (int, float)) or not b:
                    continue
                med = float(b["median"])
                denom = float(b.get("scale") or (1.4826 * float(b.get("mad", 0))))
                if denom < 1e-6:
                    denom = max(abs(med) * 0.1, FEATURE_FLOOR.get(f, 0.01))
                z = abs(v - med) / denom
                zs.append((z, f, v, med))
            zs.sort(reverse=True)
            score = zs[0][0] if zs else 0.0
            reason = [
                {"feature": f, "value": v, "median": m, "z": round(z, 2)}
                for z, f, v, m in zs[:3]
            ]
            if score >= THRESHOLD:
                cur.execute(
                    "insert into deviation_candidates (trace_id, score, reason, status, description) "
                    "values (%s, %s, %s, 'pending', %s) on conflict (trace_id) do nothing",
                    (trace_id, round(score, 3), json.dumps(reason), describe_reason(reason)),
                )
                if cur.rowcount:
                    candidates += 1
            cur.execute("update tracks set scored = true where trace_id = %s", (trace_id,))
            scored += 1
        conn.commit()
    return scored, candidates


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()

    conn = connect_pg()
    if args.once:
        s, c = score_once(conn)
        log(f"评分完成: tracks={s} candidates={c} threshold={THRESHOLD}")
        return

    log(f"启动偏离评分 threshold={THRESHOLD} batch={BATCH} poll={POLL}s")
    while True:
        try:
            s, c = score_once(conn)
            if s:
                log(f"评分: tracks={s} candidates={c}")
        except Exception as e:
            log("评分异常:", repr(e))
            try:
                conn.rollback()
            except Exception:
                pass
        time.sleep(POLL)


if __name__ == "__main__":
    main()
