"""轨迹特征计算（纯 Python，无额外依赖）"""
import math

FEATURE_FLOOR = {
    "reversals": 1.0, "n_points": 5.0, "duration_s": 1.0,
    "path_efficiency": 0.05, "path_ratio": 0.1, "extent_ratio": 0.05,
    "mean_speed": 0.01, "dwell_ratio": 0.05,
}

FEATURES = [
    "n_points", "duration_s", "path_length", "displacement", "path_efficiency",
    "reversals", "extent", "extent_ratio", "path_ratio", "mean_speed", "dwell_ratio",
]


def parse_points(path_data):
    pts = []
    for item in path_data or []:
        try:
            (x, y), t = item
            pts.append((float(x), float(y), float(t)))
        except Exception:
            continue
    pts.sort(key=lambda p: p[2])
    return pts


def compute(pts, start_time, end_time):
    if len(pts) < 2:
        return None
    dur = max(0.0, float(end_time) - float(start_time))
    path_len = 0.0
    segs = []
    for i in range(1, len(pts)):
        dx = pts[i][0] - pts[i - 1][0]
        dy = pts[i][1] - pts[i - 1][1]
        segs.append((dx, dy))
        path_len += math.hypot(dx, dy)
    disp = math.hypot(pts[-1][0] - pts[0][0], pts[-1][1] - pts[0][1])
    eff = disp / path_len if path_len > 0 else 0.0

    rev = 0
    for i in range(1, len(segs)):
        a, b = segs[i - 1], segs[i]
        na = math.hypot(*a)
        nb = math.hypot(*b)
        if na < 1e-6 or nb < 1e-6:
            continue
        cosv = max(-1.0, min(1.0, (a[0] * b[0] + a[1] * b[1]) / (na * nb)))
        if math.degrees(math.acos(cosv)) > 120:
            rev += 1

    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    ext = max(math.hypot(p[0] - cx, p[1] - cy) for p in pts)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    diag = math.hypot(max(xs) - min(xs), max(ys) - min(ys))

    dwell = 0.0
    for i in range(1, len(pts)):
        if math.hypot(pts[i][0] - cx, pts[i][1] - cy) <= 0.05:
            dwell += max(0.0, pts[i][2] - pts[i - 1][2])

    return {
        "n_points": len(pts),
        "duration_s": round(dur, 2),
        "path_length": round(path_len, 4),
        "displacement": round(disp, 4),
        "path_efficiency": round(eff, 3),
        "reversals": rev,
        "extent": round(ext, 4),
        "extent_ratio": round(ext / diag, 3) if diag > 0 else 0.0,
        "path_ratio": round(path_len / diag, 3) if diag > 0 else 0.0,
        "mean_speed": round(path_len / dur, 4) if dur > 0 else 0.0,
        "dwell_ratio": round(dwell / dur, 3) if dur > 0 else 0.0,
    }


def grid_cell(pts):
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    col = min(2, max(0, int(cx * 3)))
    row = min(2, max(0, int(cy * 3)))
    return f"r{row}c{col}"
