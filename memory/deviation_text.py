"""把偏离 reason(特征/z) 翻译成人类可读的问题描述"""

FEATURE_LABELS = {
    "path_ratio": "路径长度比",
    "path_efficiency": "路径效率",
    "reversals": "方向反转次数",
    "duration_s": "停留时长",
    "extent_ratio": "活动范围",
    "mean_speed": "平均速度",
    "dwell_ratio": "原地停留占比",
    "n_points": "轨迹点数",
}


def _fmt(feature, value):
    if feature in ("reversals", "n_points"):
        return str(int(round(value)))
    if feature == "duration_s":
        return f"{value:.1f}s"
    return f"{value:.2f}"


def describe_reason(reason):
    if not isinstance(reason, list) or not reason:
        return "与历史正常基线差异较大，建议人工核查该轨迹。"

    parts = []
    for r in reason[:3]:
        if not isinstance(r, dict):
            continue
        f = r.get("feature")
        v = r.get("value")
        m = r.get("median")
        if not isinstance(v, (int, float)) or not isinstance(m, (int, float)):
            continue
        label = FEATURE_LABELS.get(f, f or "特征")
        direction = "偏高" if v > m else ("偏低" if v < m else "接近")
        parts.append(f"{label}{direction}（{_fmt(f, v)}，正常约 {_fmt(f, m)}）")

    if not parts:
        return "与历史正常基线差异较大，建议人工核查该轨迹。"

    d = {r.get("feature"): r for r in reason if isinstance(r, dict)}
    pr, pe = d.get("path_ratio"), d.get("path_efficiency")
    rv, dw, du = d.get("reversals"), d.get("dwell_ratio"), d.get("duration_s")

    if pr and pe and pr.get("value", 0) > pr.get("median", 0) and pe.get("value", 1) < pe.get("median", 1):
        hint = "轨迹比正常更绕，可能存在徘徊/绕行，建议核查。"
    elif rv and rv.get("value", 0) > rv.get("median", 0):
        hint = "方向反复，可能存在来回徘徊，建议核查。"
    elif (dw and dw.get("value", 0) > dw.get("median", 0)) or (du and du.get("value", 0) > du.get("median", 0)):
        hint = "停留时间/原地占比偏高，可能存在异常逗留，建议核查。"
    else:
        hint = "建议人工核查该轨迹。"

    return "与历史正常基线差异较大：" + "；".join(parts) + "。" + hint
