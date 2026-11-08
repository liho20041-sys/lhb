#!/usr/bin/env python3
"""
URFD 摔倒评估（ByteTrack + 过渡判据）
- 5fps 采样，Keypoint R-CNN
- boxmot ByteTrack 关联同一人（输出列: x1,y1,x2,y2,track_id,conf,cls,det_ind）
- 每个 track：摔倒姿态(score>=2) 且 最近窗口内角度>=45° 或 宽高比>=0.5
"""
import csv, glob, json, os, sys, time
from collections import defaultdict
import cv2
import numpy as np
import torch
from boxmot import ByteTrack
from boxmot.trackers.bytetrack.config import ByteTrackConfig
from torchvision.models.detection import (
    KeypointRCNN_ResNet50_FPN_Weights, keypointrcnn_resnet50_fpn,
)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bridge"))
from fall_rules import fall_score  # noqa: E402

SAMPLE_FPS=float(os.getenv("SAMPLE_FPS","5"))
PERSON_THR=float(os.getenv("PERSON_SCORE_THR","0.5"))
GAP=int(os.getenv("GAP_SAMPLES","2"))
DESCENT_WINDOW=float(os.getenv("DESCENT_WINDOW","1.0"))
MIN_ANGLE_DELTA=float(os.getenv("MIN_ANGLE_DELTA","45"))
MIN_ASPECT_DELTA=float(os.getenv("MIN_ASPECT_DELTA","0.5"))
SCORE_MIN=int(os.getenv("FALL_SCORE_MIN","2"))
BT_MIN_HITS=int(os.getenv("BT_MIN_HITS","1"))
BT_TRACK_THRESH=float(os.getenv("BT_TRACK_THRESH","0.5"))
THRESHOLDS=[0.4,0.6,0.8,1.0,1.5,2.0]
HERE=os.path.dirname(os.path.abspath(__file__))
VIDEO_DIR=os.path.join(HERE,"urfd")
DT=1.0/SAMPLE_FPS


def load_model():
    m=keypointrcnn_resnet50_fpn(weights=KeypointRCNN_ResNet50_FPN_Weights.DEFAULT).eval()
    return m.cuda() if torch.cuda.is_available() else m


def infer(model, frame):
    rgb=cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)
    x=torch.from_numpy(rgb).permute(2,0,1).float().div(255.0)
    if torch.cuda.is_available(): x=x.cuda()
    with torch.inference_mode(): out=model([x])[0]
    dets=[]
    for i in range(len(out["scores"])):
        s=float(out["scores"][i])
        if s<PERSON_THR: continue
        box=[float(v) for v in out["boxes"][i]]
        f=fall_score(out["keypoints"][i],box)
        if f: dets.append({"box":box,**f,"person_score":s})
    return dets


def longest_run(times, flags):
    best=0.0; start=None; last=None; misses=0
    for t,f in zip(times,flags):
        if f:
            if start is None: start=t
            last=t; misses=0
        elif start is not None:
            misses+=1
            if misses>GAP:
                best=max(best,last-start+DT); start=None; misses=0
    if start is not None: best=max(best,last-start+DT)
    return round(best,2)


def track_fall_run(hist):
    times=[h[0] for h in hist]
    flags=[]
    for t,f in hist:
        if f["fall_score"]<SCORE_MIN: flags.append(False); continue
        win=[ff for (tt,ff) in hist if t-DESCENT_WINDOW<=tt<=t]
        ang=[ff["torso_angle"] for ff in win]; asp=[ff["aspect"] for ff in win]
        da=(max(ang)-min(ang)) if len(ang)>=2 else 0
        ds=(max(asp)-min(asp)) if len(asp)>=2 else 0
        flags.append(da>=MIN_ANGLE_DELTA or ds>=MIN_ASPECT_DELTA)
    return longest_run(times,flags)


def eval_video(model, path):
    cap=cv2.VideoCapture(path); fps=cap.get(cv2.CAP_PROP_FPS) or 30.0
    step=max(1,int(round(fps/SAMPLE_FPS)))
    tracker=ByteTrack(ByteTrackConfig(min_hits=BT_MIN_HITS, track_thresh=BT_TRACK_THRESH)); hist=defaultdict(list); idx=0; t0=time.time()
    while True:
        ok,frame=cap.read()
        if not ok: break
        if idx%step==0:
            t=idx/fps; dets=infer(model,frame)
            if dets:
                arr=np.array([[*d["box"],d["person_score"],0] for d in dets],dtype=float)
                out=tracker.update(arr,frame)
                if out is not None and len(out)>0:
                    for row in out:
                        tid=int(row[4]); di=int(row[7])
                        if 0<=di<len(dets):
                            hist[tid].append((t,dets[di]))
        idx+=1
    cap.release()
    runs=[track_fall_run(h) for h in hist.values() if len(h)>=2]
    return {"max_run_s":max(runs) if runs else 0.0,"tracks":len(hist),"elapsed_s":round(time.time()-t0,2)}


def main():
    videos=sorted(glob.glob(os.path.join(VIDEO_DIR,"*.mp4")))
    print(f"videos={len(videos)} ByteTrack + transition")
    model=load_model(); rows=[]
    for i,v in enumerate(videos,1):
        name=os.path.basename(v); r=eval_video(model,v)
        r["file"]=name; r["gt_fall"]=name.startswith("fall-"); rows.append(r)
        if i%10==0 or i==len(videos):
            print(f"[{i}/{len(videos)}] {name} gt={int(r['gt_fall'])} run={r['max_run_s']}s tracks={r['tracks']}",flush=True)
    summary={}
    for th in THRESHOLDS:
        tp=sum(1 for r in rows if r["gt_fall"] and r["max_run_s"]>=th)
        fn=sum(1 for r in rows if r["gt_fall"] and r["max_run_s"]<th)
        fp=sum(1 for r in rows if not r["gt_fall"] and r["max_run_s"]>=th)
        tn=sum(1 for r in rows if not r["gt_fall"] and r["max_run_s"]<th)
        p=tp/(tp+fp) if tp+fp else 0; rec=tp/(tp+fn) if tp+fn else 0
        f1=2*p*rec/(p+rec) if p+rec else 0
        summary[str(th)]={"tp":tp,"fp":fp,"tn":tn,"fn":fn,"precision":round(p,4),
                          "recall":round(rec,4),"f1":round(f1,4),"accuracy":round((tp+tn)/len(rows),4)}
    print("\n=== BYTETRACK + TRANSITION SWEEP ===")
    print(f"{'sustain':>8} {'TP':>4} {'FP':>4} {'TN':>4} {'FN':>4} {'P':>7} {'R':>7} {'F1':>7} {'Acc':>7}")
    for th in THRESHOLDS:
        s=summary[str(th)]
        print(f"{th:>8} {s['tp']:>4} {s['fp']:>4} {s['tn']:>4} {s['fn']:>4} {s['precision']:>7} {s['recall']:>7} {s['f1']:>7} {s['accuracy']:>7}")
    with open(os.path.join(HERE,"fall_eval_bytetrack_results.csv"),"w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    with open(os.path.join(HERE,"fall_eval_bytetrack_summary.json"),"w") as f:
        json.dump({"sample_fps":SAMPLE_FPS,"descent_window":DESCENT_WINDOW,
                   "min_angle_delta":MIN_ANGLE_DELTA,"min_aspect_delta":MIN_ASPECT_DELTA,
                   "thresholds":summary},f,indent=2)
    print("\nsaved fall_eval_bytetrack_results.csv / fall_eval_bytetrack_summary.json")


if __name__=="__main__":
    main()
