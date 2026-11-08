#!/usr/bin/env python3
"""
告警快照归档 + 保留期清理

功能：
  1. 把 alarm_records 里指向 Frigate 的快照下载到 dashboard/snapshots/<id>.jpg
  2. 成功后把 snapshot 改写为 /snapshots/<id>.jpg（保留原 URL 到 snapshot_original）
  3. 过期/失效 URL 重试 3 次后放弃并清空 snapshot（避免坏图）
  4. 按保留期删除旧 alarm_records / kafka_messages，并清理孤儿快照文件

用法：
  python snapshot_archiver.py            # 持续运行
  python snapshot_archiver.py --once     # 跑一批归档
  python snapshot_archiver.py --cleanup-dry-run
"""
import argparse
import os
import time
import urllib.request
from datetime import datetime

import psycopg2

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAP_DIR = os.getenv("SNAP_DIR", os.path.join(BASE, "dashboard", "snapshots"))
PG_DSN = os.getenv("PG_DSN", "host=127.0.0.1 port=5432 dbname=prod_db user=prod_user password=SecurePwd@2025")
RETENTION_DAYS = int(os.getenv("ALARM_RETENTION_DAYS", "30"))
POLL = int(os.getenv("POLL_INTERVAL", "10"))
BATCH = int(os.getenv("BATCH_SIZE", "200"))
CLEANUP_INTERVAL = int(os.getenv("CLEANUP_INTERVAL", "3600"))
MAX_ATTEMPTS = 3


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


def archive_once(conn):
    ok = fail = skip = 0
    with conn.cursor() as cur:
        cur.execute(
            "select id, snapshot from alarm_records "
            "where snapshot_archived = false and snapshot is not null and snapshot <> '' "
            "and snapshot_attempts < %s order by id asc limit %s",
            (MAX_ATTEMPTS, BATCH),
        )
        rows = cur.fetchall()

        for aid, url in rows:
            if url.startswith("/snapshots/"):
                cur.execute("update alarm_records set snapshot_archived=true where id=%s", (aid,))
                skip += 1
                continue
            # 旧种子数据指向 MinIO，当前无对象，直接放弃
            if "localhost:9000" in url:
                cur.execute(
                    "update alarm_records set snapshot_archived=true, snapshot_attempts=%s, snapshot=null where id=%s",
                    (MAX_ATTEMPTS, aid),
                )
                skip += 1
                continue
            fetch_url = url.replace("localhost", "127.0.0.1")
            try:
                with urllib.request.urlopen(fetch_url, timeout=10) as r:
                    data = r.read()
                if len(data) < 200:
                    raise ValueError("image too small")
                with open(os.path.join(SNAP_DIR, f"{aid}.jpg"), "wb") as f:
                    f.write(data)
                cur.execute(
                    "update alarm_records set snapshot_original=coalesce(snapshot_original, snapshot), "
                    "snapshot=%s, snapshot_archived=true, snapshot_attempts=snapshot_attempts+1 where id=%s",
                    (f"/snapshots/{aid}.jpg", aid),
                )
                ok += 1
            except Exception as e:
                cur.execute(
                    "update alarm_records set snapshot_attempts=snapshot_attempts+1, "
                    "snapshot_archived=(snapshot_attempts+1 >= %s), "
                    "snapshot=case when snapshot_attempts+1 >= %s then null else snapshot end where id=%s",
                    (MAX_ATTEMPTS, MAX_ATTEMPTS, aid),
                )
                fail += 1
        conn.commit()
    return ok, fail, skip


def cleanup(conn, dry=False):
    deleted_alarms = deleted_msgs = deleted_files = 0
    with conn.cursor() as cur:
        if dry:
            cur.execute(
                "select count(*) from alarm_records where create_time is not null "
                "and create_time < now() - make_interval(days => %s)", (RETENTION_DAYS,))
            deleted_alarms = cur.fetchone()[0]
            cur.execute(
                "select count(*) from kafka_messages where created_at is not null "
                "and created_at < now() - make_interval(days => %s)", (RETENTION_DAYS,))
            deleted_msgs = cur.fetchone()[0]
        else:
            cur.execute(
                "delete from alarm_records where create_time is not null "
                "and create_time < now() - make_interval(days => %s)", (RETENTION_DAYS,))
            deleted_alarms = cur.rowcount
            cur.execute(
                "delete from kafka_messages where created_at is not null "
                "and created_at < now() - make_interval(days => %s)", (RETENTION_DAYS,))
            deleted_msgs = cur.rowcount
            conn.commit()

        # 孤儿快照清理
        cur.execute("select snapshot from alarm_records where snapshot like '/snapshots/%%'")
        keep = {os.path.basename(r[0]) for r in cur.fetchall() if r[0]}
        for name in os.listdir(SNAP_DIR):
            if not name.endswith(".jpg"):
                continue
            if name not in keep:
                if not dry:
                    try:
                        os.remove(os.path.join(SNAP_DIR, name))
                    except OSError:
                        pass
                deleted_files += 1
    return deleted_alarms, deleted_msgs, deleted_files


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--cleanup-dry-run", action="store_true")
    args = ap.parse_args()

    os.makedirs(SNAP_DIR, exist_ok=True)
    conn = connect_pg()

    if args.cleanup_dry_run:
        a, m, f = cleanup(conn, dry=True)
        log(f"[dry-run] 将删除 alarms={a}, kafka_messages={m}, snapshot_files={f} (retention={RETENTION_DAYS}d)")
        return

    if args.once:
        ok, fail, skip = archive_once(conn)
        log(f"归档: ok={ok} fail={fail} skip={skip} (pending<{MAX_ATTEMPTS})")
        return

    log(f"启动归档器 dir={SNAP_DIR} retention={RETENTION_DAYS}d batch={BATCH} poll={POLL}s")
    last_cleanup = 0
    while True:
        try:
            ok, fail, skip = archive_once(conn)
            if ok or fail:
                log(f"归档: ok={ok} fail={fail} skip={skip}")
            if time.time() - last_cleanup > CLEANUP_INTERVAL:
                a, m, f = cleanup(conn)
                log(f"清理: alarms={a} kafka_messages={m} snapshot_files={f}")
                last_cleanup = time.time()
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
