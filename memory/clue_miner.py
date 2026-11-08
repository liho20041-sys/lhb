#!/usr/bin/env python3
"""
线索挖掘：频次/周期/共现网络 -> risk_clues
线索类型：
  - deviation_cluster：某区域/时段短期内偏离候选聚集
  - odd_hour：某区域在历史罕见时段出现活动
  - return：同一匿名外观多次出现（跨时段/跨镜）
  - companion：两名目标长期共同出现
"""
import argparse
import json
import os
import time
from collections import defaultdict
from datetime import datetime

import psycopg2

PG_DSN = os.getenv(
    "PG_DSN",
    "host=127.0.0.1 port=5432 dbname=prod_db user=prod_user password=SecurePwd@2025",
)
INTERVAL = int(os.getenv("CLUE_INTERVAL", "300"))
MIN_DEVIATION_CLUSTER = int(os.getenv("CLUE_MIN_DEVIATION", "3"))
ODD_HOUR_TOTAL = int(os.getenv("CLUE_ODD_TOTAL", "100"))
ODD_HOUR_MAX_FRAC = float(os.getenv("CLUE_ODD_FRAC", "0.03"))
REID_MIN_SIM = float(os.getenv("REID_SIM_THRESHOLD", "0.8"))
REID_MIN_GAP = float(os.getenv("REID_MIN_GAP", "60"))
COMPANION_MIN = int(os.getenv("CLUE_COMPANION_MIN", "2"))


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


def insert_clue(cur, clue_type, clue_key, score, evidence, summary):
    cur.execute(
        "insert into risk_clues(clue_type, clue_key, score, evidence, evidence_summary, status) "
        "values(%s,%s,%s,%s,%s,'pending') on conflict (clue_key) do nothing",
        (clue_type, clue_key, round(float(score), 4), json.dumps(evidence, ensure_ascii=False), summary),
    )
    return cur.rowcount


def mine_deviation_cluster(cur):
    cur.execute(
        "select t.region_id, t.hour_bucket, count(*) n, max(d.score) mx, "
        "array_agg(d.trace_id) traces, array_agg(d.id) ids "
        "from deviation_candidates d join tracks t on t.trace_id = d.trace_id "
        "where d.status = 'pending' and d.created_at > now() - interval '24 hours' "
        "group by 1,2 having count(*) >= %s",
        (MIN_DEVIATION_CLUSTER,),
    )
    n = 0
    for region, hour, cnt, mx, traces, ids in cur.fetchall():
        key = f"dev_cluster:{region}:{hour}"
        summary = f"{region} 在 {hour}:00 左右出现 {cnt} 条偏离候选，最高偏离分 {float(mx):.2f}"
        evidence = {"region": region, "hour": hour, "count": cnt, "candidate_ids": ids, "traces": traces}
        n += insert_clue(cur, "deviation_cluster", key, mx, evidence, summary)
    return n


def mine_odd_hour(cur):
    cur.execute("select region_id, hour_bucket, count(*) n from tracks group by 1,2")
    rows = cur.fetchall()
    totals = defaultdict(int)
    per = {}
    for region, hour, n in rows:
        totals[region] += n
        per[(region, hour)] = n
    added = 0
    for (region, hour), n in per.items():
        total = totals[region]
        if total < ODD_HOUR_TOTAL or n < 2:
            continue
        frac = n / total
        if frac >= ODD_HOUR_MAX_FRAC:
            continue
        key = f"odd_hour:{region}:{hour}"
        summary = f"{region} 在 {hour}:00 时段出现 {n} 条轨迹（占该区域 {frac:.1%}），属于历史罕见时段活动"
        evidence = {"region": region, "hour": hour, "count": n, "total": total, "fraction": round(frac, 4)}
        added += insert_clue(cur, "odd_hour", key, 1 - frac, evidence, summary)
    return added


def _find(parent, x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


def mine_return(cur):
    cur.execute(
        "select a_trace, b_trace, similarity, gap_s, same_camera from reid_links "
        "where similarity >= %s and gap_s >= %s",
        (REID_MIN_SIM, REID_MIN_GAP),
    )
    links = cur.fetchall()
    if not links:
        return 0

    parent = {}
    sim_of = {}
    for a, b, sim, gap, same in links:
        for x in (a, b):
            parent.setdefault(x, x)
        ra, rb = _find(parent, a), _find(parent, b)
        if ra != rb:
            parent[rb] = ra
        sim_of[(a, b)] = float(sim)

    comps = defaultdict(set)
    for x in parent:
        comps[_find(parent, x)].add(x)

    added = 0
    for root, traces in comps.items():
        if len(traces) < 3:
            continue
        traces = sorted(traces)
        cur.execute(
            "select camera_id, extract(epoch from start_time) from track_embeddings "
            "where trace_id = any(%s)",
            (traces,),
        )
        meta = cur.fetchall()
        if not meta:
            continue
        cams = sorted({m[0] for m in meta if m[0]})
        times = [float(m[1]) for m in meta if m[1] is not None]
        span = max(times) - min(times) if len(times) >= 2 else 0
        max_sim = max(
            (float(s) for (a, b), s in sim_of.items() if a in traces and b in traces),
            default=REID_MIN_SIM,
        )
        key = f"return:{traces[0]}"
        summary = (
            f"同一匿名外观在 {span / 60:.0f} 分钟内出现 {len(traces)} 次"
            f"（摄像头 {','.join(cams)}），可能为回流/多次踩点"
        )
        evidence = {"traces": traces, "size": len(traces), "span_s": round(span, 1), "cameras": cams}
        added += insert_clue(cur, "return", key, max_sim, evidence, summary)
    return added


def mine_companion(cur):
    cur.execute(
        "select id, raw_data->'features'->>'event_a', raw_data->'features'->>'event_b' "
        "from alarm_records where event_type = 'cooccur' "
        "and create_time > now() - interval '7 days' and raw_data is not null"
    )
    groups = defaultdict(list)
    for aid, a, b in cur.fetchall():
        if not a or not b:
            continue
        pair = tuple(sorted([str(a), str(b)]))
        groups[pair].append(aid)

    added = 0
    for (a, b), ids in groups.items():
        if len(ids) < COMPANION_MIN:
            continue
        key = f"companion:{a}:{b}"
        score = min(1.0, len(ids) / 10.0)
        summary = f"两名目标在近 7 天内共同出现 {len(ids)} 次，可能为长期结伴"
        evidence = {"event_a": a, "event_b": b, "count": len(ids), "alarm_ids": ids}
        added += insert_clue(cur, "companion", key, score, evidence, summary)
    return added


def mine_once(conn):
    with conn.cursor() as cur:
        d = mine_deviation_cluster(cur)
        o = mine_odd_hour(cur)
        r = mine_return(cur)
        c = mine_companion(cur)
    conn.commit()
    return {"deviation_cluster": d, "odd_hour": o, "return": r, "companion": c}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()

    conn = connect_pg()
    if args.once:
        log("线索挖掘:", mine_once(conn))
        return

    log(f"启动线索挖掘 interval={INTERVAL}s")
    while True:
        try:
            log("线索挖掘:", mine_once(conn))
        except Exception as e:
            log("挖掘异常:", repr(e))
            try:
                conn.rollback()
            except Exception:
                pass
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
