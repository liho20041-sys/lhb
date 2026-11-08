#!/usr/bin/env python3
"""
人群聚集检测：Frigate 同时在场的 person -> 区域内人数 + 持续时间 -> 告警

判定：在指定归一化区域内，同时在场人数 >= CROWD_MIN_COUNT，
并持续 >= CROWD_SUSTAIN 秒，触发一次「人群聚集」。

只统计目标数量与位置，不涉及人脸/身份。

用法：
  python crowd_bridge.py            # 持续运行
  python crowd_bridge.py --once     # 单轮
  python crowd_bridge.py --selftest # 用合成数据验证计数逻辑
"""
import argparse
import json
import os
import sys
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
MIN_COUNT = int(os.getenv("CROWD_MIN_COUNT", "3"))
SUSTAIN = float(os.getenv("CROWD_SUSTAIN", "5"))
COOLDOWN = float(os.getenv("CROWD_COOLDOWN", "30"))
REGION = tuple(float(x) for x in os.getenv("CROWD_REGION", "0,0,1,1").split(","))

BASE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE, "crowd_state.json")
TOPIC = "行为检测"


def log(*a):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}]", *a, flush=True)


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"first_ts": None, "fired": False, "last_fire_ts": 0.0}


def save_state(s):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(s, f)


def http_json(path):
    req = urllib.request.Request(FRIGATE + path, headers={"User-Agent": "crowd-bridge"})
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


def person_position(e):
    pd = (e.get("data") or {}).get("path_data") or []
    if pd:
        try:
            p = pd[-1][0]
            return float(p[0]), float(p[1])
        except Exception:
            pass
    box = (e.get("data") or {}).get("box")
    if isinstance(box, list) and len(box) == 4:
        return box[0] + box[2] / 2, box[1] + box[3] / 2
    return None


def is_active(e, now, grace=1.0):
    s = float(e.get("start_time") or 0)
    en = e.get("end_time")
    if not en:
        return s <= now
    return s <= now <= float(en) + grace


def in_region(pos):
    if not pos:
        return False
    x1, y1, x2, y2 = REGION
    return x1 <= pos[0] <= x2 and y1 <= pos[1] <= y2


def active_persons(events, now):
    out = []
    for e in events:
        if e.get("label") != "person":
            continue
        if not is_active(e, now):
            continue
        pos = person_position(e)
        if in_region(pos):
            out.append((e, pos))
    return out


def _bbox_pixels(box, w=1280, h=720):
    if not (isinstance(box, list) and len(box) == 4):
        return None, None, None, None
    return (
        int(round(box[0] * w)),
        int(round(box[1] * h)),
        int(round(box[2] * w)),
        int(round(box[3] * h)),
    )


def write_alarm(conn, now, persons, sustained):
    camera_id = persons[0][0].get("camera", "demo")
    count = len(persons)
    episode_start = int(float(min(p[0]["start_time"] for p in persons)))
    key = f"crowd-{camera_id}-{episode_start}"
    rep = persons[0][0]

    with conn.cursor() as cur:
        cur.execute(
            "select 1 from kafka_messages where message->>'event_id' = %s limit 1", (key,)
        )
        if cur.fetchone():
            return False

        severity = "high" if count >= MIN_COUNT + 2 else "medium"
        conf = min(1.0, count / float(max(MIN_COUNT * 2, 1)))
        msg = {
            "event_id": key,
            "event_type": "crowd",
            "event_name": "人群聚集",
            "camera_id": camera_id,
            "timestamp": float(rep.get("start_time")),
            "confidence": round(conf, 4),
            "detected_object": "person",
            "description": f"人群聚集：区域内 {count} 人，持续 {sustained:.0f}s",
            "snapshot_url": f"{FRIGATE}/api/events/{rep.get('id')}/snapshot.jpg",
            "bbox": list(REGION),
            "severity": severity,
            "source": "behavior_rule",
            "features": {
                "count": count,
                "region": list(REGION),
                "sustained": round(sustained, 1),
                "persons": [p[0].get("id") for p in persons],
            },
        }
        cur.execute(
            "insert into kafka_messages(topic, message, created_at) values (%s, %s, now()) returning id",
            (TOPIC, json.dumps(msg, ensure_ascii=False)),
        )
        kid = cur.fetchone()[0]

        bx, by, bw, bh = (
            int(REGION[0] * 1280),
            int(REGION[1] * 720),
            int((REGION[2] - REGION[0]) * 1280),
            int((REGION[3] - REGION[1]) * 720),
        )
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
                datetime.fromtimestamp(float(rep.get("start_time"))),
                msg["description"],
                msg["snapshot_url"],
                kid,
                datetime.now(),
                "behavior_rule",
                "crowd",
                camera_id,
                conf,
                json.dumps(list(REGION)),
                json.dumps(msg, ensure_ascii=False),
                severity,
                "人群聚集",
                bx,
                by,
                bw,
                bh,
                "active",
            ),
        )
    conn.commit()
    return True


def run_once(conn, state):
    now = time.time()
    events = http_json(f"/api/events?after={now - 60}&limit=200")
    persons = active_persons(events, now)
    count = len(persons)
    fired = False

    if count >= MIN_COUNT:
        if state.get("first_ts") is None:
            state["first_ts"] = now
        sustained = now - float(state["first_ts"])
        if (
            sustained >= SUSTAIN
            and not state.get("fired")
            and now - float(state.get("last_fire_ts", 0)) >= COOLDOWN
        ):
            if write_alarm(conn, now, persons, sustained):
                state["fired"] = True
                state["last_fire_ts"] = now
                fired = True
                log(f"触发 人群聚集 -> 区域内 {count} 人，持续 {sustained:.0f}s")
        if not fired and count >= MIN_COUNT:
            log(f"聚集观察中：{count} 人，已持续 {sustained:.0f}s")
    else:
        state["first_ts"] = None
        state["fired"] = False

    save_state(state)
    return count, fired


def selftest():
    now = 1000.0
    def ev(i, x, y, s, en):
        return {
            "id": f"p{i}",
            "label": "person",
            "camera": "sim",
            "start_time": s,
            "end_time": en,
            "data": {"path_data": [[[x, y], s]], "box": [x, y, 0.05, 0.1]},
        }
    events = [
        ev(1, 0.4, 0.5, 990, 1010),
        ev(2, 0.5, 0.5, 995, 1015),
        ev(3, 0.6, 0.5, 980, 1005),
        ev(4, 0.7, 0.5, 900, 950),   # 已结束
        ev(5, 0.1, 0.1, 990, 1010),  # 区域内也算(整帧)
    ]
    persons = active_persons(events, now)
    print(f"selftest: active_persons={len(persons)} (期望 4) count>=MIN_COUNT={len(persons) >= MIN_COUNT}")
    print("selftest 完成（未写库）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        selftest()
        return

    log(f"启动人群聚集检测 min_count={MIN_COUNT} sustain={SUSTAIN}s region={REGION}")
    conn = connect_pg()
    state = load_state()
    if args.once:
        c, f = run_once(conn, state)
        log(f"当前区域内人数={c} 触发={f}")
        return
    while True:
        try:
            run_once(conn, state)
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
