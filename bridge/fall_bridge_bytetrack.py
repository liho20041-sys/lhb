#!/usr/bin/env python3
"""摔倒检测 v3：ByteTrack + 过渡判据"""
import json, os, sys, time, urllib.request
from collections import defaultdict
from datetime import datetime
import cv2, numpy as np, psycopg2, torch
from boxmot import ByteTrack
from boxmot.trackers.bytetrack.config import ByteTrackConfig
from torchvision.models.detection import (
    KeypointRCNN_ResNet50_FPN_Weights, keypointrcnn_resnet50_fpn,
)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fall_rules import fall_score  # noqa: E402

FRIGATE=os.getenv("FRIGATE_URL","http://127.0.0.1:5000"); CAMERA=os.getenv("CAMERA","demo")
PG_DSN=os.getenv("PG_DSN","host=127.0.0.1 port=5432 dbname=prod_db user=prod_user password=SecurePwd@2025")
POLL=float(os.getenv("POLL_INTERVAL","0.2")); PERSON_THR=float(os.getenv("PERSON_SCORE_THR","0.5"))
FALL_SUSTAIN=float(os.getenv("FALL_SUSTAIN","0.8")); COOLDOWN=float(os.getenv("FALL_COOLDOWN","60"))
DESCENT_WINDOW=float(os.getenv("DESCENT_WINDOW","1.0")); MIN_ANGLE_DELTA=float(os.getenv("MIN_ANGLE_DELTA","45"))
MIN_ASPECT_DELTA=float(os.getenv("MIN_ASPECT_DELTA","0.5")); SCORE_MIN=int(os.getenv("FALL_SCORE_MIN","2"))
GAP=float(os.getenv("GAP_S","0.4")); BT_MIN_HITS=int(os.getenv("BT_MIN_HITS","1")); BT_TRACK_THRESH=float(os.getenv("BT_TRACK_THRESH","0.5"))
TOPIC="行为检测"


def log(*a): print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}]",*a,flush=True)

def connect_pg():
    while True:
        try:
            c=psycopg2.connect(PG_DSN); c.autocommit=False; log("PostgreSQL 已连接"); return c
        except Exception as e: log("PG 连接失败:",e,"5s 后重试"); time.sleep(5)

def fetch_frame():
    with urllib.request.urlopen(f"{FRIGATE}/api/{CAMERA}/latest.jpg",timeout=10) as r:
        return cv2.imdecode(np.frombuffer(r.read(),np.uint8),cv2.IMREAD_COLOR)

def load_model():
    m=keypointrcnn_resnet50_fpn(weights=KeypointRCNN_ResNet50_FPN_Weights.DEFAULT).eval()
    return m.cuda() if torch.cuda.is_available() else m

def infer(model,img):
    rgb=cv2.cvtColor(img,cv2.COLOR_BGR2RGB)
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

def current_falling(hist,t):
    ft=hist[-1][1]
    if ft["fall_score"]<SCORE_MIN: return False
    win=[ff for (tt,ff) in hist if t-DESCENT_WINDOW<=tt<=t]
    ang=[ff["torso_angle"] for ff in win]; asp=[ff["aspect"] for ff in win]
    da=(max(ang)-min(ang)) if len(ang)>=2 else 0
    ds=(max(asp)-min(asp)) if len(asp)>=2 else 0
    return da>=MIN_ANGLE_DELTA or ds>=MIN_ASPECT_DELTA

def write_alarm(conn,tid,feat,since):
    key=f"fall-{CAMERA}-bt{tid}-{int(since)}"
    with conn.cursor() as cur:
        cur.execute("select 1 from kafka_messages where message->>'event_id'=%s limit 1",(key,))
        if cur.fetchone(): return False
        desc=(f"摔倒：躯干 {feat['torso_angle']}°，头低于髋={feat['head_below_hip']}，"
              f"宽高比 {feat['aspect']}（ByteTrack {tid}）")
        msg={"event_id":key,"event_type":"fall","event_name":"摔倒","camera_id":CAMERA,
             "timestamp":since,"confidence":round(min(1.0,0.5+feat["fall_score"]/6.0),4),
             "detected_object":"person","description":desc,
             "snapshot_url":f"{FRIGATE}/api/{CAMERA}/latest.jpg","bbox":feat.get("box"),
             "severity":"high","source":"pose_rule",
             "features":{k:feat.get(k) for k in ("torso_angle","head_below_hip","aspect","fall_score")},
             "track_id":tid}
        cur.execute("insert into kafka_messages(topic,message,created_at) values(%s,%s,now()) returning id",
                    (TOPIC,json.dumps(msg,ensure_ascii=False)))
        kid=cur.fetchone()[0]; x1,y1,x2,y2=feat.get("box")
        cur.execute("""insert into alarm_records
          (camera_name,location,time,details,snapshot,kafka_msg_id,create_time,create_by,
           event_type,camera_id,confidence,bbox_data,raw_data,alert_level,event_name,
           bbox_x,bbox_y,bbox_width,bbox_height,status)
          values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
          (f"摄像头_{CAMERA}",f"{TOPIC}@{CAMERA}",datetime.fromtimestamp(since),desc,
           msg["snapshot_url"],kid,datetime.now(),"pose_rule","fall",CAMERA,msg["confidence"],
           json.dumps(feat.get("box")),json.dumps(msg,ensure_ascii=False),"high","摔倒",
           int(x1),int(y1),int(x2-x1),int(y2-y1),"active"))
    conn.commit(); return True

def main():
    log("加载姿态模型(v3 ByteTrack)...")
    model=load_model(); log(f"模型就绪 cuda={torch.cuda.is_available()}")
    conn=connect_pg()
    tracker=ByteTrack(ByteTrackConfig(min_hits=BT_MIN_HITS, track_thresh=BT_TRACK_THRESH))
    hist=defaultdict(list); state={}
    log(f"sustain={FALL_SUSTAIN}s window={DESCENT_WINDOW}s bt(min_hits={BT_MIN_HITS},track_thresh={BT_TRACK_THRESH})")
    cycle=0
    while True:
        try:
            now=time.time(); img=fetch_frame(); dets=infer(model,img)
            if dets:
                arr=np.array([[*d["box"],d["person_score"],0] for d in dets],dtype=float)
                out=tracker.update(arr,img)
                if out is not None and len(out)>0:
                    for row in out:
                        tid=int(row[4]); di=int(row[7])
                        if 0<=di<len(dets):
                            hist[tid].append((now,dets[di]))
                            hist[tid]=[h for h in hist[tid] if now-h[0]<=2.5]
            for tid,h in hist.items():
                if not h or now-h[-1][0]>1.0: continue
                st=state.setdefault(tid,{"since":None,"fired":False,"last_fire":0.0,"last_falling":0.0})
                if current_falling(h,now):
                    st["last_falling"]=now
                    if st["since"] is None: st["since"]=now
                    if now-st["since"]>=FALL_SUSTAIN and not st["fired"] and now-st["last_fire"]>=COOLDOWN:
                        if write_alarm(conn,tid,h[-1][1],st["since"]):
                            st["fired"]=True; st["last_fire"]=now
                            log(f"触发 摔倒 bt_track={tid} since={datetime.fromtimestamp(st['since']):%H:%M:%S}")
                else:
                    if st["since"] is not None and now-st["last_falling"]>GAP:
                        st["since"]=None; st["fired"]=False
            cycle+=1
            if cycle%100==0: log(f"cycle={cycle} tracks={len(hist)}")
        except Exception as e:
            log("循环异常:",repr(e))
            try: conn.rollback()
            except Exception: pass
            time.sleep(2)
        time.sleep(POLL)

if __name__=="__main__": main()
