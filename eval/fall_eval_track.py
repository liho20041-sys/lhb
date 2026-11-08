#!/usr/bin/env python3
"""
URFD 摔倒评估（跟踪 + 过渡判据）
- 5fps 采样，Keypoint R-CNN
- IoU 关联同一人（track）
- 对每个 track：当前姿态摔倒(score>=2) 且 最近窗口内角度变化>=45° 或 宽高比增加>=0.5
- 再按 sustain 阈值做事件级判定
"""
import csv, glob, json, os, sys, time
import cv2
import torch
from torchvision.models.detection import (
    KeypointRCNN_ResNet50_FPN_Weights,
    keypointrcnn_resnet50_fpn,
)

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bridge"))
from fall_rules import fall_score  # noqa: E402

SAMPLE_FPS = float(os.getenv("SAMPLE_FPS", "5"))
PERSON_THR = float(os.getenv("PERSON_SCORE_THR", "0.5"))
GAP = int(os.getenv("GAP_SAMPLES", "2"))
DESCENT_WINDOW = float(os.getenv("DESCENT_WINDOW", "1.0"))
MIN_ANGLE_DELTA = float(os.getenv("MIN_ANGLE_DELTA", "45"))
MIN_ASPECT_DELTA = float(os.getenv("MIN_ASPECT_DELTA", "0.5"))
SCORE_MIN = int(os.getenv("FALL_SCORE_MIN", "2"))
IOU_THR = float(os.getenv("IOU_THR", "0.2"))
MAX_MISS_S = float(os.getenv("MAX_MISS_S", "1.0"))
THRESHOLDS = [0.4, 0.6, 0.8, 1.0, 1.5, 2.0]
HERE = os.path.dirname(os.path.abspath(__file__))
VIDEO_DIR = os.path.join(HERE, "urfd")
DT = 1.0 / SAMPLE_FPS


def load_model():
    m = keypointrcnn_resnet50_fpn(weights=KeypointRCNN_ResNet50_FPN_Weights.DEFAULT).eval()
    return m.cuda() if torch.cuda.is_available() else m


def iou(a, b):
    x1 = max(a[0], b[0]); y1 = max(a[1], b[1])
    x2 = min(a[2], b[2]); y2 = min(a[3], b[3])
    iw = max(0.0, x2 - x1); ih = max(0.0, y2 - y1)
    inter = iw * ih
    ua = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def infer(model, frame):
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    x = torch.from_numpy(rgb).permute(2, 0, 1).float().div(255.0)
    if torch.cuda.is_available():
        x = x.cuda()
    with torch.inference_mode():
        out = model([x])[0]
    dets = []
    for i in range(len(out["scores"])):
        s = float(out["scores"][i])
        if s < PERSON_THR:
            continue
        box = [float(v) for v in out["boxes"][i]]
        f = fall_score(out["keypoints"][i], box)
        if f:
            dets.append({"box": box, "fall_score": f["fall_score"],
                         "torso_angle": f["torso_angle"], "aspect": f["aspect"],
                         "head_below": f["head_below_hip"], "person_score": s})
    return dets


class Track:
    __slots__ = ("id", "box", "last_t", "hist")
    def __init__(self, tid, box, t, feat):
        self.id = tid; self.box = box; self.last_t = t; self.hist = [(t, feat)]


def update_tracks(tracks, dets, t, next_id):
    used = set()
    for tr in tracks:
        best_i, best_iou = None, 0.0
        for j, d in enumerate(dets):
            if j in used:
                continue
            v = iou(tr.box, d["box"])
            if v > best_iou:
                best_iou, best_i = v, j
        if best_i is not None and best_iou >= IOU_THR:
            d = dets[best_i]
            tr.box = d["box"]; tr.last_t = t; tr.hist.append((t, d))
            used.add(best_i)
    for j, d in enumerate(dets):
        if j not in used:
            tracks.append(Track(next_id, d["box"], t, d)); next_id += 1
    tracks[:] = [tr for tr in tracks if t - tr.last_t <= MAX_MISS_S]
    return next_id


def longest_run(times, flags):
    best = 0.0; start = None; last = None; misses = 0
    for t, f in zip(times, flags):
        if f:
            if start is None: start = t
            last = t; misses = 0
        elif start is not None:
            misses += 1
            if misses > GAP:
                best = max(best, last - start + DT); start = None; misses = 0
    if start is not None:
        best = max(best, last - start + DT)
    return round(best, 2)


def track_fall_run(tr):
    hist = tr.hist
    times = [h[0] for h in hist]
    flags = []
    for i, (t, f) in enumerate(hist):
        if f["fall_score"] < SCORE_MIN:
            flags.append(False); continue
        win = [ff for (tt, ff) in hist if t - DESCENT_WINDOW <= tt <= t]
        angles = [ff["torso_angle"] for ff in win]
        aspects = [ff["aspect"] for ff in win]
        d_ang = (max(angles) - min(angles)) if len(angles) >= 2 else 0
        d_asp = (max(aspects) - min(aspects)) if len(aspects) >= 2 else 0
        flags.append(d_ang >= MIN_ANGLE_DELTA or d_asp >= MIN_ASPECT_DELTA)
    return longest_run(times, flags)


def eval_video(model, path):
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, int(round(fps / SAMPLE_FPS)))
    idx = 0; tracks = []; next_id = 1
    t0 = time.time()
    while True:
        ok, frame = cap.read()
        if not ok: break
        if idx % step == 0:
            t = idx / fps
            dets = infer(model, frame)
            next_id = update_tracks(tracks, dets, t, next_id)
        idx += 1
    cap.release()
    max_run = max([track_fall_run(tr) for tr in tracks], default=0.0)
    return {"max_run_s": max_run, "tracks": len(tracks), "elapsed_s": round(time.time()-t0, 2)}


def main():
    videos = sorted(glob.glob(os.path.join(VIDEO_DIR, "*.mp4")))
    print(f"videos={len(videos)} fps={SAMPLE_FPS} window={DESCENT_WINDOW}s angle>={MIN_ANGLE_DELTA} aspect>={MIN_ASPECT_DELTA}")
    model = load_model()
    rows = []
    for i, v in enumerate(videos, 1):
        name = os.path.basename(v)
        r = eval_video(model, v)
        r["file"] = name; r["gt_fall"] = name.startswith("fall-")
        rows.append(r)
        if i % 10 == 0 or i == len(videos):
            print(f"[{i}/{len(videos)}] {name} gt={int(r['gt_fall'])} run={r['max_run_s']}s tracks={r['tracks']}", flush=True)

    summary = {}
    for th in THRESHOLDS:
        tp = sum(1 for r in rows if r["gt_fall"] and r["max_run_s"] >= th)
        fn = sum(1 for r in rows if r["gt_fall"] and r["max_run_s"] < th)
        fp = sum(1 for r in rows if not r["gt_fall"] and r["max_run_s"] >= th)
        tn = sum(1 for r in rows if not r["gt_fall"] and r["max_run_s"] < th)
        p = tp/(tp+fp) if tp+fp else 0.0
        rec = tp/(tp+fn) if tp+fn else 0.0
        f1 = 2*p*rec/(p+rec) if p+rec else 0.0
        summary[str(th)] = {"tp":tp,"fp":fp,"tn":tn,"fn":fn,
                            "precision":round(p,4),"recall":round(rec,4),
                            "f1":round(f1,4),"accuracy":round((tp+tn)/len(rows),4)}
    print("\n=== TRACK + TRANSITION SWEEP ===")
    print(f"{'sustain':>8} {'TP':>4} {'FP':>4} {'TN':>4} {'FN':>4} {'P':>7} {'R':>7} {'F1':>7} {'Acc':>7}")
    for th in THRESHOLDS:
        s = summary[str(th)]
        print(f"{th:>8} {s['tp']:>4} {s['fp']:>4} {s['tn']:>4} {s['fn']:>4} "
              f"{s['precision']:>7} {s['recall']:>7} {s['f1']:>7} {s['accuracy']:>7}")
    with open(os.path.join(HERE, "fall_eval_track_results.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    with open(os.path.join(HERE, "fall_eval_track_summary.json"), "w") as f:
        json.dump({"sample_fps":SAMPLE_FPS,"descent_window":DESCENT_WINDOW,
                   "min_angle_delta":MIN_ANGLE_DELTA,"min_aspect_delta":MIN_ASPECT_DELTA,
                   "iou_thr":IOU_THR,"thresholds":summary}, f, indent=2)
    print("\nsaved fall_eval_track_results.csv / fall_eval_track_summary.json")


if __name__ == "__main__":
    main()
