#!/usr/bin/env python3
"""
匿名 ReID：从 Frigate 事件快照裁人 -> OSNet 512 维嵌入 -> 存 PG -> 计算跨时段/跨镜关联
只做匿名外观关联，不做身份识别。
"""
import argparse
import json
import os
import time
import urllib.request
from datetime import datetime

import cv2
import numpy as np
import psycopg2
from boxmot import ReIDConfig
from boxmot.reid.factory import create_reid_encoder

FRIGATE = os.getenv("FRIGATE_URL", "http://127.0.0.1:5000")
PG_DSN = os.getenv(
    "PG_DSN",
    "host=127.0.0.1 port=5432 dbname=prod_db user=prod_user password=SecurePwd@2025",
)
POLL = float(os.getenv("POLL_INTERVAL", "20"))
BATCH = int(os.getenv("BATCH_SIZE", "20"))
MIN_GAP = float(os.getenv("REID_MIN_GAP", "60"))
SIM_THR = float(os.getenv("REID_SIM_THRESHOLD", "0.8"))
TOP_K = int(os.getenv("REID_TOP_K", "3"))
MIN_CROP = 12


def log(*a):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}]", *a, flush=True)


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


def fetch_event(eid):
    with urllib.request.urlopen(f"{FRIGATE}/api/events/{eid}", timeout=8) as r:
        return json.loads(r.read().decode())


def fetch_clean(eid):
    with urllib.request.urlopen(f"{FRIGATE}/api/events/{eid}/snapshot-clean.webp", timeout=8) as r:
        return cv2.imdecode(np.frombuffer(r.read(), np.uint8), cv2.IMREAD_COLOR)


def load_encoder():
    log("加载 OSNet ReID ...")
    model_path = os.getenv(
        "REID_MODEL",
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bridge", "models", "osnet_x0_25_msmt17.pt"),
    )
    enc = create_reid_encoder(ReIDConfig(model=model_path, device="cuda"))
    log(f"ReID 就绪 dim={enc.embedding_dim} model={model_path}")
    return enc


def embed(enc, img, box):
    H, W = img.shape[:2]
    x, y, w, h = [float(v) for v in box]
    x1, y1 = max(0, int(x * W)), max(0, int(y * H))
    x2, y2 = min(W, int((x + w) * W)), min(H, int((y + h) * H))
    if x2 - x1 < MIN_CROP or y2 - y1 < MIN_CROP:
        return None
    b = np.array([[x1, y1, x2, y2, 0.9]], dtype=float)
    f = np.asarray(enc._runtime.get_features(b, img)).ravel()
    n = float(np.linalg.norm(f))
    return f / n if n > 0 else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()

    enc = load_encoder()
    conn = connect_pg()
    log(f"启动 ReID 嵌入 min_gap={MIN_GAP}s sim>={SIM_THR} top_k={TOP_K}")

    while True:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "select t.trace_id, t.camera_id, t.start_time from tracks t "
                    "left join track_embeddings e on e.trace_id = t.trace_id "
                    "where t.end_time is not null and e.trace_id is null "
                    "order by t.start_time asc limit %s",
                    (BATCH,),
                )
                pending = cur.fetchall()

                if not pending:
                    if args.once:
                        log("没有待嵌入轨迹")
                        return
                    time.sleep(POLL)
                    continue

                # 载入已有嵌入
                cur.execute(
                    "select trace_id, camera_id, extract(epoch from start_time), embedding "
                    "from track_embeddings where failed = false and embedding is not null"
                )
                known = [
                    (r[0], r[1], float(r[2]), np.asarray(r[3], dtype=np.float32))
                    for r in cur.fetchall()
                ]

                ok = fail = links = 0
                for trace_id, camera_id, start_time in pending:
                    eid = trace_id.split(":", 1)[1] if ":" in trace_id else ""
                    vec = None
                    try:
                        ev = fetch_event(eid)
                        box = (ev.get("data") or {}).get("box")
                        if box:
                            img = fetch_clean(eid)
                            vec = embed(enc, img, box)
                    except Exception:
                        vec = None

                    ts = start_time.timestamp() if start_time else time.time()
                    if vec is None:
                        cur.execute(
                            "insert into track_embeddings(trace_id,camera_id,start_time,embedding,failed) "
                            "values(%s,%s,%s,null,true) on conflict (trace_id) do nothing",
                            (trace_id, camera_id, start_time),
                        )
                        fail += 1
                        continue

                    cur.execute(
                        "insert into track_embeddings(trace_id,camera_id,start_time,embedding,failed) "
                        "values(%s,%s,%s,%s,false) on conflict (trace_id) do nothing",
                        (trace_id, camera_id, start_time, json.dumps([round(float(x), 6) for x in vec])),
                    )

                    # 跨时段/跨镜关联
                    matches = []
                    for tid, cam, tsk, vk in known:
                        if tid == trace_id:
                            continue
                        gap = abs(ts - tsk)
                        same = cam == camera_id
                        if same and gap < MIN_GAP:
                            continue
                        sim = float(np.dot(vec, vk))
                        if sim >= SIM_THR:
                            matches.append((sim, tid, gap, same))
                    matches.sort(reverse=True)
                    for sim, b_trace, gap, same in matches[:TOP_K]:
                        cur.execute(
                            "insert into reid_links(a_trace,b_trace,similarity,gap_s,same_camera) "
                            "values(%s,%s,%s,%s,%s) on conflict (a_trace,b_trace) do nothing",
                            (trace_id, b_trace, round(sim, 4), round(gap, 1), same),
                        )
                        links += 1
                    known.append((trace_id, camera_id, ts, vec))
                    ok += 1

                conn.commit()
            if ok or fail:
                log(f"嵌入 ok={ok} fail={fail} links={links}")
            if args.once:
                return
        except Exception as e:
            log("循环异常:", repr(e))
            try:
                conn.rollback()
            except Exception:
                pass
            time.sleep(5)
        time.sleep(POLL)


if __name__ == "__main__":
    main()
