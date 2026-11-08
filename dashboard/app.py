"""
告警看板 / 接口（FastAPI）

接口：
  GET  /                     看板页面
  GET  /api/health           健康检查
  GET  /api/stats            汇总统计
  GET  /api/alarms           告警列表（可按 event_type/status/camera 过滤）
  GET  /api/alarms/{id}      告警详情
  PATCH /api/alarms/{id}     更新状态（handled / ignored / active）
"""
import io
import json
import os
import sys
import time
import urllib.request
from datetime import date, datetime
from decimal import Decimal

import psycopg2
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageDraw, ImageFont
from psycopg2.extras import RealDictCursor

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "memory"))
from deviation_text import describe_reason

FRIGATE = os.getenv("FRIGATE_URL", "http://127.0.0.1:5000")
CAMERA = os.getenv("CAMERA", "demo")
TRACK_LABELS = {"person", "bicycle", "car", "motorcycle", "bus", "truck"}
COLORS = {
    "person": (80, 220, 120),
    "bicycle": (80, 180, 255),
    "car": (255, 90, 90),
    "motorcycle": (255, 160, 60),
    "bus": (255, 220, 80),
    "truck": (200, 120, 255),
}
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

PG_DSN = os.getenv(
    "PG_DSN",
    "host=127.0.0.1 port=5432 dbname=prod_db user=prod_user password=SecurePwd@2025",
)
BASE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(BASE, "static")
SNAP_DIR = os.path.join(BASE, "snapshots")
os.makedirs(SNAP_DIR, exist_ok=True)

app = FastAPI(title="时空记忆 · 告警看板")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory=STATIC), name="static")
app.mount("/snapshots", StaticFiles(directory=SNAP_DIR), name="snapshots")


def get_conn():
    return psycopg2.connect(PG_DSN)


def clean(row):
    out = {}
    for k, v in dict(row).items():
        if isinstance(v, (datetime, date)):
            out[k] = v.isoformat(sep=" ")
        elif isinstance(v, Decimal):
            out[k] = float(v)
        else:
            out[k] = v
    return out


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "monitor.html"))


@app.get("/monitor")
def monitor_page():
    return FileResponse(os.path.join(STATIC, "monitor.html"))


@app.get("/alarms")
def alarms_page():
    return FileResponse(os.path.join(STATIC, "index.html"))


@app.get("/api/health")
def health():
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("select 1")
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/api/stats")
def stats():
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "select count(*) as total, "
            "sum(case when status='active' then 1 else 0 end) as active, "
            "sum(case when status='handled' then 1 else 0 end) as handled "
            "from alarm_records"
        )
        base = clean(cur.fetchone())

        cur.execute(
            "select event_type, event_name, count(*) as count "
            "from alarm_records group by 1,2 order by count desc"
        )
        by_type = [clean(r) for r in cur.fetchall()]

        cur.execute(
            "select alert_level, count(*) as count "
            "from alarm_records group by 1 order by count desc"
        )
        by_level = [clean(r) for r in cur.fetchall()]

        cur.execute(
            "select date_trunc('hour', create_time) as h, count(*) as count "
            "from alarm_records where create_time > now() - interval '24 hours' "
            "group by 1 order by 1"
        )
        timeline = [clean(r) for r in cur.fetchall()]

    return {
        "total": base.get("total") or 0,
        "active": int(base.get("active") or 0),
        "handled": int(base.get("handled") or 0),
        "by_type": by_type,
        "by_level": by_level,
        "timeline": timeline,
    }


@app.get("/api/alarms")
def alarms(
    event_type: str | None = None,
    status: str | None = None,
    camera: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    limit = max(1, min(limit, 500))
    where, params = [], []
    if event_type:
        where.append("event_type = %s")
        params.append(event_type)
    if status:
        where.append("status = %s")
        params.append(status)
    if camera:
        where.append("camera_id = %s")
        params.append(camera)
    clause = ("where " + " and ".join(where)) if where else ""

    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"select id, camera_name, camera_id, location, time, details, snapshot, "
            f"event_type, event_name, alert_level, status, confidence, create_by, "
            f"kafka_msg_id, create_time, bbox_x, bbox_y, bbox_width, bbox_height "
            f"from alarm_records {clause} order by id desc limit %s offset %s",
            params + [limit, offset],
        )
        rows = [clean(r) for r in cur.fetchall()]
        cur.execute(f"select count(*) as n from alarm_records {clause}", params)
        total = cur.fetchone()["n"]
    return {"total": total, "items": rows}


@app.get("/api/alarms/{aid}")
def alarm_detail(aid: int):
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("select * from alarm_records where id = %s", (aid,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="alarm not found")
    return clean(row)


@app.patch("/api/alarms/{aid}")
def update_alarm(aid: int, body: dict):
    st = body.get("status", "handled")
    if st not in ("active", "handled", "ignored"):
        raise HTTPException(status_code=400, detail="invalid status")
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "update alarm_records set status=%s, handler_user=%s, handle_time=now() "
            "where id=%s returning id",
            (st, body.get("handler", "dashboard"), aid),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="alarm not found")
        conn.commit()
    return {"ok": True, "id": aid, "status": st}


_EVENT_CACHE = {"t": 0.0, "events": []}


def _fetch_frame():
    url = f"{FRIGATE}/api/{CAMERA}/latest.jpg"
    with urllib.request.urlopen(url, timeout=5) as r:
        return Image.open(io.BytesIO(r.read())).convert("RGB")


def _active_events():
    now = time.time()
    url = f"{FRIGATE}/api/events?after={int(now - 60)}&limit=200"
    with urllib.request.urlopen(url, timeout=5) as r:
        events = json.loads(r.read().decode())
    out = []
    for e in events:
        if e.get("label") not in TRACK_LABELS:
            continue
        en = e.get("end_time")
        if en and en < now - 2:
            continue
        d = e.get("data") or {}
        box = d.get("box")
        if not box:
            continue
        score = d.get("top_score") or d.get("score")
        out.append((e.get("label"), box, score))
    return out


def _cached_events(ttl=0.5):
    now = time.time()
    if now - _EVENT_CACHE["t"] > ttl:
        try:
            _EVENT_CACHE["events"] = _active_events()
        except Exception:
            pass
        _EVENT_CACHE["t"] = now
    return _EVENT_CACHE["events"]


def _render_jpeg(quality=78):
    img = _fetch_frame()
    events = _cached_events()
    draw = ImageDraw.Draw(img)
    W, H = img.size
    fsize = max(16, W // 60)
    try:
        font = ImageFont.truetype(FONT_PATH, fsize)
    except Exception:
        font = ImageFont.load_default()
    stroke = max(2, W // 400)

    for label, box, score in events:
        x, y, w, h = [float(v) for v in box]
        x1, y1 = int(x * W), int(y * H)
        x2, y2 = int((x + w) * W), int((y + h) * H)
        color = COLORS.get(label, (80, 220, 120))
        draw.rectangle([x1, y1, x2, y2], outline=color, width=stroke)
        text = f"{label} {score:.2f}" if isinstance(score, (int, float)) else str(label)
        tb = draw.textbbox((0, 0), text, font=font)
        tw, th = tb[2] - tb[0], tb[3] - tb[1]
        ty = max(0, y1 - th - 6)
        draw.rectangle([x1, ty, x1 + tw + 10, ty + th + 6], fill=color)
        draw.text((x1 + 5, ty + 3), text, fill=(0, 0, 0), font=font)

    draw.text((10, 8), f"{CAMERA}  {W}x{H}  objects={len(events)}", fill=(255, 255, 255), font=font)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


@app.get("/api/live.jpg")
def live_jpg():
    try:
        return Response(
            content=_render_jpeg(80),
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store, max-age=0"},
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/api/live.mjpg")
def live_mjpg():
    def gen():
        while True:
            try:
                frame = _render_jpeg(75)
                yield (
                    b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                    + str(len(frame)).encode()
                    + b"\r\n\r\n"
                    + frame
                    + b"\r\n"
                )
            except Exception:
                pass
            time.sleep(0.05)

    return StreamingResponse(
        gen(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


# ---------------- 轨迹记忆 / 偏离候选 ----------------

@app.get("/api/tracks")
def api_tracks(limit: int = 50, offset: int = 0):
    limit = max(1, min(limit, 500))
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "select trace_id, camera_id, label, start_time, end_time, duration_s, "
            "region_id, hour_bucket, features, scored "
            "from tracks order by start_time desc limit %s offset %s",
            (limit, offset),
        )
        items = [clean(r) for r in cur.fetchall()]
        cur.execute("select count(*) as n from tracks")
        total = cur.fetchone()["n"]
    return {"total": total, "items": items}


@app.get("/api/deviations")
def api_deviations(status: str | None = None, limit: int = 100, offset: int = 0):
    limit = max(1, min(limit, 500))
    where, params = [], []
    if status:
        where.append("d.status = %s")
        params.append(status)
    clause = ("where " + " and ".join(where)) if where else ""
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"select d.id, d.trace_id, d.score, d.reason, d.status, d.created_at, "
            f"t.camera_id, t.region_id, t.start_time, t.end_time, t.duration_s, "
            f"t.features, t.path, d.description "
            f"from deviation_candidates d join tracks t on t.trace_id = d.trace_id "
            f"{clause} order by d.score desc, d.id desc limit %s offset %s",
            params + [limit, offset],
        )
        items = [clean(r) for r in cur.fetchall()]
        for it in items:
            if not it.get("description"):
                it["description"] = describe_reason(it.get("reason"))
            tid = it.get("trace_id") or ""
            eid = tid.split(":", 1)[1] if ":" in tid else ""
            it["snapshot"] = f"{FRIGATE}/api/events/{eid}/snapshot.jpg" if eid else ""
        cur.execute(f"select count(*) as n from deviation_candidates d {clause}", params)
        total = cur.fetchone()["n"]
    return {"total": total, "items": items}


@app.get("/api/deviation_stats")
def api_deviation_stats():
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "select count(*) as total, "
            "count(*) filter (where status='pending') as pending, "
            "count(*) filter (where status='reviewed') as reviewed, "
            "count(*) filter (where status='ignored') as ignored, "
            "coalesce(max(score),0) as max_score from deviation_candidates"
        )
        s = clean(cur.fetchone())
        cur.execute("select count(*) as n from tracks")
        s["tracks"] = cur.fetchone()["n"]
        cur.execute("select count(*) as n from baselines")
        s["baselines"] = cur.fetchone()["n"]
    return s


@app.patch("/api/deviations/{did}")
def api_update_deviation(did: int, body: dict):
    st = body.get("status", "reviewed")
    if st not in ("pending", "reviewed", "ignored"):
        raise HTTPException(status_code=400, detail="invalid status")
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "update deviation_candidates set status=%s where id=%s returning id",
            (st, did),
        )
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="not found")
        conn.commit()
    return {"ok": True, "id": did, "status": st}


# ---------------- 线索池 ----------------

@app.get("/api/clues")
def api_clues(status: str | None = None, clue_type: str | None = None, limit: int = 100, offset: int = 0):
    limit = max(1, min(limit, 500))
    where, params = [], []
    if status:
        where.append("status = %s"); params.append(status)
    if clue_type:
        where.append("clue_type = %s"); params.append(clue_type)
    clause = ("where " + " and ".join(where)) if where else ""
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"select id, clue_type, score, evidence, evidence_summary, status, created_at "
            f"from risk_clues {clause} order by score desc, id desc limit %s offset %s",
            params + [limit, offset],
        )
        items = [clean(r) for r in cur.fetchall()]
        cur.execute(f"select count(*) as n from risk_clues {clause}", params)
        total = cur.fetchone()["n"]
    return {"total": total, "items": items}


@app.get("/api/clues/stats")
def api_clue_stats():
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "select count(*) as total, "
            "count(*) filter (where status='pending') as pending, "
            "count(*) filter (where status='reviewed') as reviewed, "
            "count(*) filter (where status='ignored') as ignored, "
            "coalesce(max(score),0) as max_score from risk_clues"
        )
        return clean(cur.fetchone())


@app.patch("/api/clues/{cid}")
def api_update_clue(cid: int, body: dict):
    st = body.get("status", "reviewed")
    if st not in ("pending", "reviewed", "ignored"):
        raise HTTPException(status_code=400, detail="invalid status")
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("update risk_clues set status=%s where id=%s returning id", (st, cid))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="not found")
        conn.commit()
    return {"ok": True, "id": cid, "status": st}
