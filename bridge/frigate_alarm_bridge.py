#!/usr/bin/env python3
"""
Frigate -> Kafka -> PostgreSQL 告警桥接

链路：
  Frigate /api/events
    -> Kafka topic  frigate-events        (producer)
    -> kafka_messages 表                  (consumer 落库)
    -> alarm_records 表                   (复刻 module_alarm0/alert_sync_service 的同步逻辑)

设计原则：
  - 只分析行为/目标，不涉及人脸身份
  - 消息结构与 alert_sync_service._convert_to_alarm_record 期望的字段一致
  - 以 event_id 去重，重复运行不产生重复告警
"""
import json
import os
import time
import urllib.request
from datetime import datetime

import psycopg2
from kafka import KafkaConsumer, KafkaProducer

FRIGATE = os.getenv("FRIGATE_URL", "http://127.0.0.1:5000")
KAFKA = os.getenv("KAFKA_BOOTSTRAP", "127.0.0.1:9092")
PG_DSN = os.getenv(
    "PG_DSN",
    "host=127.0.0.1 port=5432 dbname=prod_db user=prod_user password=SecurePwd@2025",
)
EVENT_TOPIC = os.getenv("KAFKA_TOPIC", "frigate-events")
ALARM_TOPIC = os.getenv("ALARM_TOPIC", "目标检测")
POLL = float(os.getenv("POLL_INTERVAL", "3"))
FRAME_W, FRAME_H = 1280, 720

BASE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE, "state.json")


def log(*a):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}]", *a, flush=True)


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"last_event_ts": time.time() - 120, "seen": []}


def save_state(s):
    s["seen"] = s["seen"][-800:]
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(s, f)


def http_json(path):
    req = urllib.request.Request(FRIGATE + path, headers={"User-Agent": "frigate-bridge"})
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


def make_producer():
    while True:
        try:
            p = KafkaProducer(
                bootstrap_servers=KAFKA,
                value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8"),
                acks=1,
                retries=3,
                linger_ms=50,
            )
            log("Kafka producer 已连接")
            return p
        except Exception as e:
            log("Kafka producer 未就绪，5s 后重试")
            time.sleep(5)


def make_consumer():
    while True:
        try:
            c = KafkaConsumer(
                EVENT_TOPIC,
                bootstrap_servers=KAFKA,
                group_id="frigate-bridge-v2",
                auto_offset_reset="earliest",
                metadata_max_age_ms=5000,
                enable_auto_commit=True,
                value_deserializer=lambda b: json.loads(b.decode("utf-8")),
            )
            log("Kafka consumer 已连接")
            return c
        except Exception as e:
            log("Kafka consumer 未就绪，5s 后重试")
            time.sleep(5)


def poll_frigate(producer, state):
    after = max(0.0, float(state.get("last_event_ts", 0)) - 2)
    events = http_json(f"/api/events?after={after}&limit=100")
    seen = set(state.get("seen", []))
    new = 0
    for e in events:
        eid = e.get("id")
        if not eid or eid in seen:
            continue
        data = e.get("data") or {}
        msg = {
            "event_id": eid,
            "event_type": e.get("label", "unknown"),
            "camera_id": e.get("camera", ""),
            "timestamp": e.get("start_time"),
            "confidence": data.get("top_score") or data.get("score"),
            "detected_object": e.get("label", "unknown"),
            "description": f"Frigate 检测到 {e.get('label')}",
            "snapshot_url": f"{FRIGATE}/api/events/{eid}/snapshot.jpg",
            "bbox": data.get("box"),
            "severity": data.get("max_severity"),
            "path_points": len(data.get("path_data") or []),
            "source": "frigate",
        }
        producer.send(EVENT_TOPIC, msg)
        seen.add(eid)
        new += 1
        state["last_event_ts"] = max(float(state.get("last_event_ts", 0)), float(e.get("start_time") or 0))
    if new:
        producer.flush()
    state["seen"] = list(seen)
    return new


def kafka_to_table(consumer, conn):
    n = 0
    records = consumer.poll(timeout_ms=500)
    for _tp, msgs in records.items():
        for m in msgs:
            msg = m.value
            eid = msg.get("event_id")
            with conn.cursor() as cur:
                cur.execute(
                    "select 1 from kafka_messages where message->>'event_id' = %s limit 1", (eid,)
                )
                if cur.fetchone():
                    continue
                cur.execute(
                    "insert into kafka_messages(topic, message, created_at) values (%s, %s, now())",
                    (ALARM_TOPIC, json.dumps(msg, ensure_ascii=False)),
                )
            conn.commit()
            n += 1
    return n


def build_details(topic, msg):
    parts = [f"{topic}告警"]
    conf = msg.get("confidence")
    if isinstance(conf, (int, float)):
        parts.append(f"置信度: {conf:.2%}")
    if msg.get("detected_object"):
        parts.append(f"对象: {msg['detected_object']}")
    if msg.get("description"):
        parts.append(msg["description"])
    return " | ".join(parts)


def table_to_alarm(conn):
    n = 0
    with conn.cursor() as cur:
        cur.execute("select id, topic, message, created_at from kafka_messages order by id")
        rows = cur.fetchall()
        for kid, topic, msg, created_at in rows:
            if isinstance(msg, str):
                msg = json.loads(msg)
            cur.execute("select 1 from alarm_records where kafka_msg_id = %s limit 1", (kid,))
            if cur.fetchone():
                continue
            ts = msg.get("timestamp")
            try:
                alarm_time = datetime.fromtimestamp(float(ts))
            except Exception:
                alarm_time = created_at
            box = msg.get("bbox")
            bx = by = bw = bh = None
            if isinstance(box, list) and len(box) == 4:
                bx = int(round(box[0] * FRAME_W))
                by = int(round(box[1] * FRAME_H))
                bw = int(round(box[2] * FRAME_W))
                bh = int(round(box[3] * FRAME_H))
            sev = msg.get("severity")
            alert_level = "high" if sev in ("alert", "critical") else "medium"
            camera_id = msg.get("camera_id", "")
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
                    f"{topic}@{camera_id}",
                    alarm_time,
                    build_details(topic, msg),
                    msg.get("snapshot_url", ""),
                    kid,
                    created_at,
                    "system_sync",
                    msg.get("event_type"),
                    camera_id,
                    msg.get("confidence"),
                    json.dumps(box) if box else None,
                    json.dumps(msg, ensure_ascii=False),
                    alert_level,
                    msg.get("detected_object"),
                    bx,
                    by,
                    bw,
                    bh,
                    "active",
                ),
            )
            conn.commit()
            n += 1
    return n


def main():
    log("启动 Frigate 告警桥接")
    log(f"Frigate={FRIGATE} Kafka={KAFKA} topic={EVENT_TOPIC} alarm_topic={ALARM_TOPIC}")
    state = load_state()
    conn = connect_pg()
    producer = make_producer()
    consumer = make_consumer()
    cycle = 0
    while True:
        try:
            produced = poll_frigate(producer, state)
            inserted = kafka_to_table(consumer, conn)
            synced = table_to_alarm(conn)
            save_state(state)
            cycle += 1
            if produced or inserted or synced or cycle % 20 == 0:
                log(f"cycle={cycle} produced={produced} kafka_to_table={inserted} synced_alarm={synced}")
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
