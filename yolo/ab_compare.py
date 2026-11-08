import json, sys, time, urllib.request, statistics

BASE = "http://127.0.0.1:5000"

def api(path):
    with urllib.request.urlopen(BASE + path, timeout=15) as r:
        return json.loads(r.read().decode())

def api_text(path):
    with urllib.request.urlopen(BASE + path, timeout=15) as r:
        return r.read().decode().strip()

def wait_ready(timeout=120):
    t0=time.time()
    while time.time()-t0 < timeout:
        try:
            st=api("/api/stats")
            if st.get("detectors") and st.get("cameras"):
                return api_text("/api/version"), st
        except Exception:
            pass
        time.sleep(2)
    raise SystemExit("frigate not ready")

def run(model, window):
    v, st = wait_ready()
    det = list((st.get("detectors") or {}).values())[0]
    cam = list((st.get("cameras") or {}).values())[0]
    t0 = time.time()
    print(f"[{model}] collecting {window}s ...", flush=True)
    time.sleep(window)
    ev = api(f"/api/events?after={t0}&limit=1000")
    persons = [e for e in ev if e.get("label") == "person"]
    scores=[]; areas=[]
    for e in persons:
        d=e.get("data") or {}
        s=d.get("top_score") or d.get("score")
        if isinstance(s,(int,float)): scores.append(float(s))
        b=d.get("box")
        if isinstance(b,list) and len(b)==4: areas.append(float(b[2])*float(b[3]))
    def pct(a,p):
        if not a: return None
        a=sorted(a); return round(a[min(len(a)-1,int(len(a)*p))],4)
    out = {
        "model": model,
        "frigate_version": v.get("service",{}).get("version") if isinstance(v,dict) else v,
        "window_s": window,
        "detector_inference_ms": det.get("inference_speed"),
        "camera_fps": cam.get("camera_fps"),
        "detection_fps": cam.get("detection_fps"),
        "total_events": len(ev),
        "person_events": len(persons),
        "labels": {l: sum(1 for e in ev if e.get("label")==l) for l in sorted({e.get("label") for e in ev})},
        "person_score_mean": round(statistics.mean(scores),4) if scores else None,
        "person_score_p50": pct(scores,0.5),
        "person_score_p90": pct(scores,0.9),
        "person_score_min": round(min(scores),4) if scores else None,
        "box_area_p50": pct(areas,0.5),
        "small_objects(area<1%)": sum(1 for a in areas if a<0.01),
        "large_objects(area>5%)": sum(1 for a in areas if a>0.05),
        "box_area_max": round(max(areas),4) if areas else None,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    path=f"/home/bjutcv/data/lhb/spacetime-agent/yolo/result_{model}.json"
    json.dump(out, open(path,"w"), ensure_ascii=False, indent=2)
    print("saved", path)

if __name__ == "__main__":
    run(sys.argv[1], int(sys.argv[2]) if len(sys.argv)>2 else 120)
