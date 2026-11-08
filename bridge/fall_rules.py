"""
摔倒判定：基于 COCO 17 关键点（torchvision Keypoint R-CNN 输出）

关键点顺序：
0 nose, 1/2 eyes, 3/4 ears,
5/6 shoulders, 7/8 elbows, 9/10 wrists,
11/12 hips, 13/14 knees, 15/16 ankles

判定依据（三选二为摔倒）：
  1. 躯干接近水平（肩中点->髋中点 与竖直方向夹角 >= 55°）
  2. 头低于髋（鼻子 y 明显大于髋中点 y）
  3. 人体框宽高比 >= 1.1（横躺）
"""
import math

KP = {
    "nose": 0,
    "l_shoulder": 5, "r_shoulder": 6,
    "l_hip": 11, "r_hip": 12,
    "l_knee": 13, "r_knee": 14,
    "l_ankle": 15, "r_ankle": 16,
}


def _pt(kps, i, thr=0.25):
    x, y, c = kps[i]
    if c < thr:
        return None
    return float(x), float(y), float(c)


def fall_score(keypoints, box):
    """keypoints: (17,3) list/np; box: [x1,y1,x2,y2] 像素"""
    kps = keypoints.tolist() if hasattr(keypoints, "tolist") else keypoints
    ls, rs = _pt(kps, KP["l_shoulder"]), _pt(kps, KP["r_shoulder"])
    lh, rh = _pt(kps, KP["l_hip"]), _pt(kps, KP["r_hip"])
    nose = _pt(kps, KP["nose"])
    if not (ls and rs and lh and rh):
        return None

    sx = (ls[0] + rs[0]) / 2
    sy = (ls[1] + rs[1]) / 2
    hx = (lh[0] + rh[0]) / 2
    hy = (lh[1] + rh[1]) / 2

    dx, dy = hx - sx, hy - sy
    # 与竖直方向夹角：站立 ~0°，横躺 ~90°
    torso_angle = math.degrees(math.atan2(abs(dx), abs(dy) + 1e-6))

    x1, y1, x2, y2 = [float(v) for v in box]
    w = max(1e-6, x2 - x1)
    h = max(1e-6, y2 - y1)
    aspect = w / h

    head_below = bool(nose and nose[1] > hy + 0.05 * h)

    score = 0
    if torso_angle >= 55:
        score += 1
    if head_below:
        score += 1
    if aspect >= 1.1:
        score += 1

    return {
        "torso_angle": round(torso_angle, 1),
        "head_below_hip": head_below,
        "aspect": round(aspect, 2),
        "fall_score": score,
        "fallen": score >= 2,
        "mid_shoulder": [round(sx, 1), round(sy, 1)],
        "mid_hip": [round(hx, 1), round(hy, 1)],
        "nose": [round(nose[0], 1), round(nose[1], 1)] if nose else None,
    }
