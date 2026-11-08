"""
行为规则：异常逗留 / 反复徘徊

输入为 Frigate 事件的 data.path_data（归一化轨迹点），只使用位置与时间，
不涉及人脸或身份。

特征：
  - duration        事件持续时长（秒）
  - path_length     轨迹总长度（归一化坐标）
  - displacement    首尾直线距离
  - path_efficiency 位移 / 路径长度（越接近 1 越像直线穿行）
  - reversals       方向反转次数（相邻运动向量夹角 > 120°）
  - extent          轨迹点相对质心的最大半径（衡量活动范围）
  - dwell_time      停留在质心附近的时间
"""
import math

DEFAULT_CONFIG = {
    # 异常逗留：长时间、范围小、几乎没走远
    "dwell_min_duration": 5.0,
    "dwell_radius": 0.06,
    "dwell_displacement": 0.09,
    # 反复徘徊：时长够、路径够长、效率低、方向反复
    "pacing_min_duration": 5.0,
    "pacing_min_length": 0.15,
    "pacing_max_efficiency": 0.45,
    "pacing_min_reversals": 2,
    # 反转判定角度
    "reversal_angle_deg": 120.0,
}


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _parse_points(path_data):
    pts = []
    for item in path_data or []:
        try:
            (x, y), t = item
            pts.append((float(x), float(y), float(t)))
        except Exception:
            continue
    pts.sort(key=lambda p: p[2])
    return pts


def compute_features(path_data, start_time, end_time=None, now=None):
    pts = _parse_points(path_data)
    if len(pts) < 2:
        return None

    if end_time:
        end = float(end_time)
    elif now:
        end = float(now)
    else:
        end = pts[-1][2]

    duration = max(0.0, end - float(start_time))

    path_length = 0.0
    segs = []
    for i in range(1, len(pts)):
        dx = pts[i][0] - pts[i - 1][0]
        dy = pts[i][1] - pts[i - 1][1]
        segs.append((dx, dy))
        path_length += math.hypot(dx, dy)

    displacement = _dist(pts[0], pts[-1])
    efficiency = displacement / path_length if path_length > 0 else 0.0

    reversals = 0
    for i in range(1, len(segs)):
        a, b = segs[i - 1], segs[i]
        na = math.hypot(*a)
        nb = math.hypot(*b)
        if na < 1e-6 or nb < 1e-6:
            continue
        cosv = max(-1.0, min(1.0, (a[0] * b[0] + a[1] * b[1]) / (na * nb)))
        ang = math.degrees(math.acos(cosv))
        if ang > DEFAULT_CONFIG["reversal_angle_deg"]:
            reversals += 1

    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    extent = max(math.hypot(p[0] - cx, p[1] - cy) for p in pts)

    radius = DEFAULT_CONFIG["dwell_radius"]
    dwell_time = 0.0
    for i in range(1, len(pts)):
        if math.hypot(pts[i][0] - cx, pts[i][1] - cy) <= radius:
            dwell_time += max(0.0, pts[i][2] - pts[i - 1][2])

    return {
        "point_count": len(pts),
        "duration": round(duration, 2),
        "path_length": round(path_length, 4),
        "displacement": round(displacement, 4),
        "path_efficiency": round(efficiency, 3),
        "reversals": reversals,
        "extent": round(extent, 4),
        "dwell_time": round(dwell_time, 2),
    }


def analyze(event, cfg=None):
    cfg = {**DEFAULT_CONFIG, **(cfg or {})}
    data = event.get("data") or {}
    feats = compute_features(
        data.get("path_data"), event.get("start_time"), event.get("end_time")
    )
    if not feats:
        return []

    results = []
    label = event.get("label", "object")
    score = data.get("top_score") or data.get("score") or 0.0

    if (
        feats["duration"] >= cfg["dwell_min_duration"]
        and feats["extent"] <= cfg["dwell_radius"]
        and feats["displacement"] <= cfg["dwell_displacement"]
    ):
        results.append(
            {
                "rule": "abnormal_dwell",
                "name": "异常逗留",
                "severity": "high",
                "confidence": round(float(score), 4),
                "description": (
                    f"异常逗留：{label} 停留 {feats['duration']}s，"
                    f"活动范围 {feats['extent']}，位移 {feats['displacement']}"
                ),
                "features": feats,
            }
        )

    if (
        feats["duration"] >= cfg["pacing_min_duration"]
        and feats["path_length"] >= cfg["pacing_min_length"]
        and feats["path_efficiency"] <= cfg["pacing_max_efficiency"]
        and feats["reversals"] >= cfg["pacing_min_reversals"]
    ):
        results.append(
            {
                "rule": "pacing",
                "name": "反复徘徊",
                "severity": "high",
                "confidence": round(float(score), 4),
                "description": (
                    f"反复徘徊：{label} 持续 {feats['duration']}s，"
                    f"路径效率 {feats['path_efficiency']}，方向反转 {feats['reversals']} 次"
                ),
                "features": feats,
            }
        )

    return results
