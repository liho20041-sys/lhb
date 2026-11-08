#!/usr/bin/env python3
"""
正常基线构建：按 区域×小时 统计轨迹特征的 median / MAD
- region×hour、region×全天、全局 三级基线
- 数据不足的组自动跳过
"""
import argparse
import json
import os
import statistics
import time
from collections import defaultdict
from datetime import datetime

import psycopg2

from features import FEATURES, FEATURE_FLOOR

PG_DSN = os.getenv(
    "PG_DSN",
    "host=127.0.0.1 port=5432 dbname=prod_db user=prod_user password=SecurePwd@2025",
)
MIN_SAMPLES = int(os.getenv("MIN_SAMPLES", "15"))
INTERVAL = int(os.getenv("BASELINE_INTERVAL", "600"))


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


def build_once(conn):
    with conn.cursor() as cur:
        cur.execute(
            "select region_id, hour_bucket, features from tracks "
            "where end_time is not null and features is not null"
        )
        rows = cur.fetchall()

    groups = defaultdict(list)
    for region, hour, feats in rows:
        if not isinstance(feats, dict):
            continue
        groups[(region or "*", -1)].append(feats)
        groups[("*", -1)].append(feats)
        if hour is not None:
            groups[(region or "*", int(hour))].append(feats)

    written = 0
    for (region, hour), items in groups.items():
        if len(items) < MIN_SAMPLES:
            continue
        model = {}
        for f in FEATURES:
            vals = [x.get(f) for x in items if isinstance(x.get(f), (int, float))]
            if len(vals) < MIN_SAMPLES:
                continue
            med = float(statistics.median(vals))
            mad = float(statistics.median([abs(v - med) for v in vals]))
            scale = max(1.4826 * mad, 0.1 * abs(med), FEATURE_FLOOR.get(f, 0.01))
            model[f] = {"median": round(med, 4), "mad": round(mad, 4), "scale": round(scale, 4)}
        if not model:
            continue
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into baselines (region_id, hour_bucket, weekday, crowd_level, model, sample_n, updated_at)
                values (%s, %s, -1, 'all', %s, %s, now())
                on conflict (region_id, hour_bucket, weekday, crowd_level)
                do update set model = excluded.model, sample_n = excluded.sample_n, updated_at = now()
                """,
                (region, hour, json.dumps(model), len(items)),
            )
        written += 1
    conn.commit()
    return written, len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()

    conn = connect_pg()
    if args.once:
        w, n = build_once(conn)
        log(f"基线构建完成: groups={w} tracks={n} min_samples={MIN_SAMPLES}")
        return

    log(f"启动基线构建 interval={INTERVAL}s min_samples={MIN_SAMPLES}")
    while True:
        try:
            w, n = build_once(conn)
            log(f"基线构建: groups={w} tracks={n}")
        except Exception as e:
            log("构建异常:", repr(e))
            try:
                conn.rollback()
            except Exception:
                pass
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
