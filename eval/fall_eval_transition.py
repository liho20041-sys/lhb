#!/usr/bin/env python3
"""
URFD 摔倒评估（加入"倒下速度"判据）
- 5fps 采样，记录每个采样点最优人体的 fall_score 与 torso_angle
- falling = 当前 score>=2 且 最近 DESCENT_WINDOW 秒内躯干角度变化 >= MIN_DELTA
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
DESCENT_WINDOW = float(os.getenv("DESCENT_WINDOW", "0.6"))
MIN_DELTA = float(os.getenv("MIN_ANGLE_DELTA", "45"))
SCORE_MIN = int(os.getenv("FALL_SCORE_MIN", "2"))
THRESHOLDS = [0.4, 0.6, 0.8, 1.0, 1.5, 2.0]
HERE = os.path.dirname(os.path.abspath(__file__))
VIDEO_DIR = os.path.join(HERE, "urfd")
DT = 1.0 / SAMPLE_FPS


def load_model():
    m = keypointrcnn_resnet50_fpn(weights=KeypointRCNN_ResNet50_FPN_Weights.DEFAULT).eval()
    return m.cuda() if torch.cuda.is_available() else m


def infer_best(model, frame):
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    x = torch.from_numpy(rgb).permute(2, 0, 1).float().div(255.0)
    if torch.cuda.is_available():
        x = x.cuda()
    with torch.inference_mode():
        out = model([x])[0]
    best = None
    for i in range(len(out["scores"])):
        s = float(out["scores"][i])
        if s < PERSON_THR:
            continue
        box = [float(v) for v in out["boxes"][i]]
        f = fall_score(out["keypoints"][i], box)
        if not f:
            continue
        f["person_score"] = s
        if best is None or f["fall_score"] > best["fall_score"]:
            best = f
    return best


def longest_run(times, flags):
    best = 0.0
    start = None
    last = None
    misses = 0
    for t, f in zip(times, flags):
        if f:
            if start is None:
                start = t
            last = t
            misses = 0
        elif start is not None:
            misses += 1
            if misses > GAP:
                best = max(best, last - start + DT)
                start = None
                misses = 0
    if start is not None:
        best = max(best, last - start + DT)
    return round(best, 2)


def eval_video(model, path):
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, int(round(fps / SAMPLE_FPS)))
    idx = 0
    samples = []  # (t, score, angle)
    t0 = time.time()
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if idx % step == 0:
            t = idx / fps
            b = infer_best(model, frame)
            if b:
                samples.append((round(t, 2), b["fall_score"], b["torso_angle"]))
            else:
                samples.append((round(t, 2), 0, None))
        idx += 1
    cap.release()

    times = [s[0] for s in samples]
    flags = []
    for i, (t, score, angle) in enumerate(samples):
        if score < SCORE_MIN or angle is None:
            flags.append(False)
            continue
        win = [a for (tt, _s, a) in samples if t - DESCENT_WINDOW <= tt <= t and a is not None]
        delta = (max(win) - min(win)) if len(win) >= 2 else 0
        flags.append(delta >= MIN_DELTA)

    run = longest_run(times, flags)
    return {
        "max_run_s": run,
        "falling_samples": int(sum(flags)),
        "samples": len(flags),
        "elapsed_s": round(time.time() - t0, 2),
    }


def main():
    videos = sorted(glob.glob(os.path.join(VIDEO_DIR, "*.mp4")))
    print(f"videos={len(videos)} sample_fps={SAMPLE_FPS} descent_window={DESCENT_WINDOW}s min_delta={MIN_DELTA}°")
    model = load_model()
    rows = []
    for i, v in enumerate(videos, 1):
        name = os.path.basename(v)
        r = eval_video(model, v)
        r["file"] = name
        r["gt_fall"] = name.startswith("fall-")
        rows.append(r)
        if i % 10 == 0 or i == len(videos):
            print(f"[{i}/{len(videos)}] {name} gt={int(r['gt_fall'])} run={r['max_run_s']}s", flush=True)

    summary = {}
    for th in THRESHOLDS:
        tp = sum(1 for r in rows if r["gt_fall"] and r["max_run_s"] >= th)
        fn = sum(1 for r in rows if r["gt_fall"] and r["max_run_s"] < th)
        fp = sum(1 for r in rows if not r["gt_fall"] and r["max_run_s"] >= th)
        tn = sum(1 for r in rows if not r["gt_fall"] and r["max_run_s"] < th)
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        summary[str(th)] = {
            "tp": tp, "fp": fp, "tn": tn, "fn": fn,
            "precision": round(prec, 4), "recall": round(rec, 4),
            "f1": round(f1, 4), "accuracy": round((tp + tn) / len(rows), 4),
        }
    print("\n=== THRESHOLD SWEEP (with descent-speed) ===")
    print(f"{'sustain':>8} {'TP':>4} {'FP':>4} {'TN':>4} {'FN':>4} {'P':>7} {'R':>7} {'F1':>7} {'Acc':>7}")
    for th in THRESHOLDS:
        s = summary[str(th)]
        print(f"{th:>8} {s['tp']:>4} {s['fp']:>4} {s['tn']:>4} {s['fn']:>4} "
              f"{s['precision']:>7} {s['recall']:>7} {s['f1']:>7} {s['accuracy']:>7}")

    with open(os.path.join(HERE, "fall_eval_transition_results.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    with open(os.path.join(HERE, "fall_eval_transition_summary.json"), "w") as f:
        json.dump({
            "sample_fps": SAMPLE_FPS, "gap": GAP,
            "descent_window": DESCENT_WINDOW, "min_angle_delta": MIN_DELTA,
            "thresholds": summary,
        }, f, indent=2)
    print("\nsaved fall_eval_transition_results.csv / fall_eval_transition_summary.json")


if __name__ == "__main__":
    main()
