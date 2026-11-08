#!/usr/bin/env python3
"""
行为分析桥接：Frigate 事件 -> 规则(异常逗留 / 反复徘徊) -> kafka_messages -> alarm_records

用法：
  python behavior_bridge.py            # 持续运行
  python behavior_bridge.py --once     # 只跑一轮
  python behavior_bridge.py --selftest # 用合成轨迹验证规则，不写库
"""
import argparse
import json
import math
import os
import sys
import time
import urllib.request
from datetime import datetime

import psycopg2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from behavior_rules import analyze, compute_features  # noqa: E402

FRIGATE = os.getenv("FRIGATE_URL", "http://127.0.0.1:5000")
PG_DSN = os.getenv(
    "PG_DSN",
    "host=127.0.0.1 port=5432 dbname=prod_db user=prod_user password=SecurePwd@2025",
)
POLL = float(os.getenv("POLL_INTERVAL", "3"))
WINDOW = float(os.getenv("EVENT_WINDOW", "300"))
TOPIC = "行为检测"

BASE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE, "behavior_state.json")


def log(*a):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}]", *a, flush=True)


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


def save_state(processed):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(processed)[-2000:], f)


def http_json(path):
    req = urllib.request.Request(FRIGATE + path, headers={"User-Agent": "behavior-bridge"})
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


def _bbox_pixels(box, w=720, h=404):
    if not (isinstance(box, list) and len(box) == 4):
        return None, None, None, None
    return (
        int(round(box[0] * w)),
        int(round(box[1] * h)),
        int(round(box[2] * w)),
        int(round(box[3] * h)),
    )


def write_alarm(conn, event, result):
    eid = event.get("id")
    data = event.get("data") or {}
    camera_id = event.get("camera", "")
    key = f"{eid}:{result['rule']}"

    with conn.cursor() as cur:
        cur.execute(
            "select 1 from kafka_messages where message->>'event_id' = %s limit 1", (key,)
        )
        if cur.fetchone():
            return False

        msg = {
            "event_id": key,
            "source_event_id": eid,
            "event_type": result["rule"],
            "event_name": result["name"],
            "camera_id": camera_id,
            "timestamp": event.get("start_time"),
            "confidence": result["confidence"],
            "detected_object": event.get("label"),
            "description": result["description"],
            "snapshot_url": f"{FRIGATE}/api/events/{eid}/snapshot.jpg",
            "bbox": data.get("box"),
            "severity": result["severity"],
            "source": "behavior_rule",
            "features": result["features"],
        }
        cur.execute(
            "insert into kafka_messages(topic, message, created_at) values (%s, %s, now()) returning id",
            (TOPIC, json.dumps(msg, ensure_ascii=False)),
        )
        kid = cur.fetchone()[0]

        try:
            alarm_time = datetime.fromtimestamp(float(event.get("start_time")))
        except Exception:
            alarm_time = datetime.now()

        bx, by, bw, bh = _bbox_pixels(data.get("box"))
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
                alarm_time,
                result["description"],
                msg["snapshot_url"],
                kid,
                datetime.now(),
                "behavior_rule",
                result["rule"],
                camera_id,
                result["confidence"],
                json.dumps(data.get("box")) if data.get("box") else None,
                json.dumps(msg, ensure_ascii=False),
                result["severity"],
                result["name"],
                bx,
                by,
                bw,
                bh,
                "active",
            ),
        )
    conn.commit()
    return True


def run_once(conn, processed):
    now = time.time()
    events = http_json(f"/api/events?after={now - WINDOW}&limit=200")
    triggered = 0
    for e in events:
        for result in analyze(e):
            key = f"{e.get('id')}:{result['rule']}"
            if key in processed:
                continue
            if write_alarm(conn, e, result):
                processed.add(key)
                triggered += 1
                log(f"触发 {result['name']} -> {result['description']}")
    save_state(processed)
    return len(events), triggered


def selftest():
    def ev(name, pts, dur):
        t0 = 1000.0
        path = [[[x, y], t0 + i * (dur / (len(pts) - 1))] for i, (x, y) in enumerate(pts)]
        return {
            "id": f"sim-{name}",
            "label": "person",
            "camera": "sim",
            "start_time": t0,
            "end_time": t0 + dur,
            "data": {"path_data": path, "box": [0.4, 0.4, 0.1, 0.2], "top_score": 0.9},
        }

    loiter = [(0.5 + 0.01 * math.sin(i / 2), 0.5 + 0.01 * math.cos(i / 2)) for i in range(20)]
    pacing = []
    for i in range(30):
        x = 0.2 + 0.6 * abs(((i / 5) % 2) - 1)
        pacing.append((x, 0.5))
    normal = [(0.1 + 0.8 * i / 14, 0.5) for i in range(15)]

    cases = [
        ("异常逗留", ev("loiter", loiter, 30)),
        ("反复徘徊", ev("pacing", pacing, 30)),
        ("正常穿行", ev("normal", normal, 10)),
    ]
    for expect, e in cases:
        feats = compute_features(
            e["data"]["path_data"], e["start_time"], e["end_time"]
        )
        rules = analyze(e)
        names = [r["name"] for r in rules] or ["无"]
        print(f"[{expect}] features={feats}")
        print(f"    -> rules={names}")
    print("selftest 完成（未写库）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        selftest()
        return

    log("启动行为分析桥接（异常逗留 / 反复徘徊）")
    conn = connect_pg()
    processed = load_state()
    if args.once:
        n, t = run_once(conn, processed)
        log(f"扫描 {n} 个事件，触发 {t} 条行为告警")
        return
    while True:
        try:
            n, t = run_once(conn, processed)
            if t:
                log(f"扫描 {n} 个事件，触发 {t} 条行为告警")
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
