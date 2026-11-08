#!/usr/bin/env python3
"""
URFD 摔倒事件级评估（复用 fall_rules + Keypoint R-CNN）

对每个视频按 SAMPLE_FPS 采样，检测人体姿态并按摔倒规则判定；
若某个"摔倒"状态持续 >= SUSTAIN 秒，则该视频预测为 fall。
GT：文件名以 fall- 开头为正样本，adl- 为负样本。

输出：逐视频 CSV + 汇总 precision/recall/F1/accuracy。
"""
import csv, glob, json, os, re, sys, time
import cv2
import numpy as np
import torch
from torchvision.models.detection import (
    KeypointRCNN_ResNet50_FPN_Weights,
    keypointrcnn_resnet50_fpn,
)

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bridge"))
from fall_rules import fall_score  # noqa: E402

SAMPLE_FPS = float(os.getenv("SAMPLE_FPS", "3"))
SUSTAIN = float(os.getenv("FALL_SUSTAIN", "1.5"))
PERSON_THR = float(os.getenv("PERSON_SCORE_THR", "0.5"))
HERE = os.path.dirname(os.path.abspath(__file__))
VIDEO_DIR = os.path.join(HERE, "urfd")


def load_model():
    w = KeypointRCNN_ResNet50_FPN_Weights.DEFAULT
    m = keypointrcnn_resnet50_fpn(weights=w).eval()
    if torch.cuda.is_available():
        m = m.cuda()
    return m


def infer(model, frame):
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    x = torch.from_numpy(rgb).permute(2, 0, 1).float().div(255.0)
    if torch.cuda.is_available():
        x = x.cuda()
    with torch.no_grad():
        out = model([x])[0]
    res = []
    for i in range(len(out["scores"])):
        s = float(out["scores"][i])
        if s < PERSON_THR:
            continue
        box = [float(v) for v in out["boxes"][i]]
        f = fall_score(out["keypoints"][i], box)
        if f:
            f["score"] = s
            res.append(f)
    return res


def eval_video(model, path):
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, int(round(fps / SAMPLE_FPS)))
    idx = 0
    fallen_since = None
    first_fall_t = None
    pred = False
    max_fall_score = 0
    n_sampled = 0
    t0 = time.time()
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if idx % step == 0:
            t = idx / fps
            n_sampled += 1
            persons = infer(model, frame)
            for p in persons:
                max_fall_score = max(max_fall_score, p["fall_score"])
            fallen = any(p["fallen"] for p in persons)
            if fallen:
                if fallen_since is None:
                    fallen_since = t
                if t - fallen_since >= SUSTAIN:
                    pred = True
                    first_fall_t = fallen_since
                    break
            else:
                fallen_since = None
        idx += 1
    cap.release()
    return {
        "pred": pred,
        "first_fall_t": first_fall_t,
        "max_fall_score": max_fall_score,
        "sampled": n_sampled,
        "elapsed_s": round(time.time() - t0, 2),
    }


def main():
    videos = sorted(glob.glob(os.path.join(VIDEO_DIR, "*.mp4")))
    if not videos:
        raise SystemExit("no videos in " + VIDEO_DIR)
    print(f"loading model... ({len(videos)} videos)")
    model = load_model()
    rows = []
    for i, v in enumerate(videos, 1):
        name = os.path.basename(v)
        gt = name.startswith("fall-")
        r = eval_video(model, v)
        r.update({"file": name, "gt_fall": gt})
        rows.append(r)
        print(f"[{i}/{len(videos)}] {name:<22} gt={int(gt)} pred={int(r['pred'])} "
              f"t={r['first_fall_t']} score={r['max_fall_score']} ({r['elapsed_s']}s)", flush=True)

    tp = sum(1 for r in rows if r["gt_fall"] and r["pred"])
    fn = sum(1 for r in rows if r["gt_fall"] and not r["pred"])
    fp = sum(1 for r in rows if not r["gt_fall"] and r["pred"])
    tn = sum(1 for r in rows if not r["gt_fall"] and not r["pred"])
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    acc = (tp + tn) / len(rows) if rows else 0.0
    summary = {
        "n": len(rows), "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "precision": round(prec, 4), "recall": round(rec, 4),
        "f1": round(f1, 4), "accuracy": round(acc, 4),
        "sample_fps": SAMPLE_FPS, "sustain_s": SUSTAIN,
    }
    print("\n=== SUMMARY ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    with open(os.path.join(HERE, "fall_eval_results.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    with open(os.path.join(HERE, "fall_eval_summary.json"), "w") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print("saved fall_eval_results.csv / fall_eval_summary.json")


if __name__ == "__main__":
    main()
