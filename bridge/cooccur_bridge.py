#!/usr/bin/env python3
"""
共现检测：同一相机内，两条 person 轨迹在时间轴上持续接近 -> 告警

判定：
  两条轨迹在重叠时段内，按 1s 采样，距离 <= CO_DIST 的连续时长 >= CO_SUSTAIN，
  视为"共现/结伴同行"。

只使用轨迹位置与时间，不涉及人脸/身份。

用法：
  python cooccur_bridge.py            # 持续运行
  python cooccur_bridge.py --once     # 单轮
  python cooccur_bridge.py --selftest # 合成轨迹验证
"""
import argparse
import json
import math
import os
import time
import urllib.request
from datetime import datetime

import psycopg2

FRIGATE = os.getenv("FRIGATE_URL", "http://127.0.0.1:5000")
PG_DSN = os.getenv(
    "PG_DSN",
    "host=127.0.0.1 port=5432 dbname=prod_db user=prod_user password=SecurePwd@2025",
)
POLL = float(os.getenv("POLL_INTERVAL", "3"))
CO_DIST = float(os.getenv("CO_DIST", "0.08"))
CO_SUSTAIN = float(os.getenv("CO_SUSTAIN", "8"))
CO_MIN_OVERLAP = float(os.getenv("CO_MIN_OVERLAP", "8"))
WINDOW = float(os.getenv("EVENT_WINDOW", "90"))
STEP = 1.0
TOPIC = "行为检测"

BASE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE, "cooccur_state.json")


def log(*a):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}]", *a, flush=True)


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


def save_state(s):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(s)[-2000:], f)


def http_json(path):
    req = urllib.request.Request(FRIGATE + path, headers={"User-Agent": "cooccur-bridge"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def connect_pg():
    while True:
        try:
            conn = psycopg2.connect(PG_DSN)
            conn.autocommit = False
            log("PostgreSQL 已连接")
            return conn
        except Exception as e:
            log("PostgreSQL 连接失败:", e, "5s 后重试")
            time.sleep(5)


def parse_points(e):
    pts = []
    for item in (e.get("data") or {}).get("path_data") or []:
        try:
            (x, y), t = item
            pts.append((float(x), float(y), float(t)))
        except Exception:
            continue
    pts.sort(key=lambda p: p[2])
    return pts


def interp(pts, t):
    if not pts or t < pts[0][2] or t > pts[-1][2]:
        return None
    for i in range(1, len(pts)):
        t0, t1 = pts[i - 1][2], pts[i][2]
        if t0 <= t <= t1:
            a = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
            x = pts[i - 1][0] + a * (pts[i][0] - pts[i - 1][0])
            y = pts[i - 1][1] + a * (pts[i][1] - pts[i - 1][1])
            return x, y
    return pts[-1][0], pts[-1][1]


def pair_features(e1, e2, now):
    p1, p2 = parse_points(e1), parse_points(e2)
    if len(p1) < 2 or len(p2) < 2:
        return None
    s1 = float(e1.get("start_time") or 0)
    s2 = float(e2.get("start_time") or 0)
    en1 = float(e1.get("end_time") or now)
    en2 = float(e2.get("end_time") or now)

    start = max(s1, s2, p1[0][2], p2[0][2])
    end = min(en1, en2, p1[-1][2], p2[-1][2])
    if end - start < CO_MIN_OVERLAP:
        return None

    t = start
    best = cur = 0.0
    best_start = None
    run_start = None
    dists = []
    while t <= end:
        a, b = interp(p1, t), interp(p2, t)
        if a and b:
            d = math.hypot(a[0] - b[0], a[1] - b[1])
            dists.append(d)
            if d <= CO_DIST:
                if cur == 0:
                    run_start = t
                cur += STEP
                if cur > best:
                    best = cur
                    best_start = run_start
            else:
                cur = 0
        t += STEP

    if best < CO_SUSTAIN:
        return None
    return {
        "sustained": round(best, 1),
        "min_dist": round(min(dists), 4) if dists else None,
        "avg_dist": round(sum(dists) / len(dists), 4) if dists else None,
        "start": best_start,
        "event_a": e1.get("id"),
        "event_b": e2.get("id"),
        "label_a": e1.get("label"),
        "label_b": e2.get("label"),
    }


def find_pairs(events, now):
    persons = [e for e in events if e.get("label") == "person" and parse_points(e)]
    out = []
    for i in range(len(persons)):
        for j in range(i + 1, len(persons)):
            f = pair_features(persons[i], persons[j], now)
            if f:
                out.append((persons[i], persons[j], f))
    return out


def _bbox_pixels(box, w=1280, h=720):
    if not (isinstance(box, list) and len(box) == 4):
        return None, None, None, None
    return (
        int(round(box[0] * w)), int(round(box[1] * h)),
        int(round(box[2] * w)), int(round(box[3] * h)),
    )


def union_box(b1, b2):
    if not b1:
        return b2
    if not b2:
        return b1
    x1 = min(b1[0], b2[0]); y1 = min(b1[1], b2[1])
    x2 = max(b1[0] + b1[2], b2[0] + b2[2])
    y2 = max(b1[1] + b1[3], b2[1] + b2[3])
    return [x1, y1, x2 - x1, y2 - y1]


def write_alarm(conn, e1, e2, f):
    camera_id = e1.get("camera", "demo")
    ids = sorted([str(f["event_a"]), str(f["event_b"])])
    key = f"cooccur-{camera_id}-{ids[0]}-{ids[1]}"
    with conn.cursor() as cur:
        cur.execute(
            "select 1 from kafka_messages where message->>'event_id' = %s limit 1", (key,)
        )
        if cur.fetchone():
            return False
        b1 = (e1.get("data") or {}).get("box")
        b2 = (e2.get("data") or {}).get("box")
        box = union_box(b1, b2)
        desc = (
            f"共现：2 人持续接近 {f['sustained']}s，"
            f"最近距离 {f['min_dist']}，平均 {f['avg_dist']}"
        )
        msg = {
            "event_id": key,
            "event_type": "cooccur",
            "event_name": "共现",
            "camera_id": camera_id,
            "timestamp": f.get("start"),
            "confidence": 0.8,
            "detected_object": "person",
            "description": desc,
            "snapshot_url": f"{FRIGATE}/api/events/{f['event_a']}/snapshot.jpg",
            "bbox": box,
            "severity": "medium",
            "source": "behavior_rule",
            "features": f,
        }
        cur.execute(
            "insert into kafka_messages(topic, message, created_at) values (%s, %s, now()) returning id",
            (TOPIC, json.dumps(msg, ensure_ascii=False)),
        )
        kid = cur.fetchone()[0]
        bx, by, bw, bh = _bbox_pixels(box)
        cur.execute(
            """
            insert into alarm_records (
                camera_name, location, time, details, snapshot, kafka_msg_id,
                create_time, create_by, event_type, camera_id, confidence,
                bbox_data, raw_data, alert_level, event_name,
                bbox_x, bbox_y, bbox_width, bbox_height, status
            ) values (
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
            )
            """,
            (
                f"摄像头_{camera_id}",
                f"{TOPIC}@{camera_id}",
                datetime.fromtimestamp(float(f.get("start") or time.time())),
                desc,
                msg["snapshot_url"],
                kid,
                datetime.now(),
                "behavior_rule",
                "cooccur",
                camera_id,
                0.8,
                json.dumps(box),
                json.dumps(msg, ensure_ascii=False),
                "medium",
                "共现",
                bx, by, bw, bh,
                "active",
            ),
        )
    conn.commit()
    return True


def run_once(conn, processed):
    now = time.time()
    events = http_json(f"/api/events?after={now - WINDOW}&limit=200")
    pairs = find_pairs(events, now)
    n = 0
    for e1, e2, f in pairs:
        ids = sorted([str(f["event_a"]), str(f["event_b"])])
        key = f"{ids[0]}-{ids[1]}"
        if key in processed:
            continue
        if write_alarm(conn, e1, e2, f):
            processed.add(key)
            n += 1
            log(f"触发 共现 -> {f['sustained']}s 最近距离 {f['min_dist']}")
    save_state(processed)
    return len(events), len(pairs), n


def selftest():
    def ev(name, pts, dur, t0=1000.0):
        path = [[[x, y], t0 + i * (dur / (len(pts) - 1))] for i, (x, y) in enumerate(pts)]
        return {"id": name, "label": "person", "camera": "sim",
                "start_time": t0, "end_time": t0 + dur,
                "data": {"path_data": path, "box": [0.4, 0.4, 0.1, 0.2]}}

    a = ev("a", [(0.3 + 0.02 * i, 0.5) for i in range(16)], 15)
    b = ev("b", [(0.33 + 0.02 * i, 0.52) for i in range(16)], 15)   # 与 a 同行
    c = ev("c", [(0.1 + 0.05 * i, 0.5) for i in range(12)], 11)    # 迎面而过
    d = ev("d", [(0.9 - 0.05 * i, 0.5) for i in range(12)], 11)

    f1 = pair_features(a, b, 1020)
    f2 = pair_features(c, d, 1020)
    print("同行 ->", f1)
    print("迎面 ->", f2)
    print("selftest 完成（未写库）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        selftest()
        return

    log(f"启动共现检测 dist<={CO_DIST} sustain>={CO_SUSTAIN}s")
    conn = connect_pg()
    processed = load_state()
    if args.once:
        e, p, n = run_once(conn, processed)
        log(f"事件={e} 候选对={p} 触发={n}")
        return
    while True:
        try:
            e, p, n = run_once(conn, processed)
            if n:
                log(f"事件={e} 候选对={p} 触发={n}")
        except Exception as ex:
            log("循环异常:", repr(ex))
            try:
                conn.rollback()
            except Exception:
                pass
            time.sleep(3)
        time.sleep(POLL)


if __name__ == "__main__":
    main()
