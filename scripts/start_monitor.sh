#!/usr/bin/env bash
# 打开监控：中间件 + Frigate + 5 个桥接 + 时空记忆 + 看板 + RuoYi + 归档器
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "[1/6] 中间件..."
docker compose -f deploy/docker-compose.yml up -d

echo "[2/6] Frigate..."
docker compose -f frigate/docker-compose.yml up -d
sleep 5

start_bridge() {
  local name="$1" py="$2" script="$3" log="$4"
  if pgrep -f "$ROOT/$script" >/dev/null; then
    echo "  $name 已在运行"
  else
    setsid nohup "$py" "$ROOT/$script" > "$ROOT/$log" 2>&1 < /dev/null &
    disown
    echo "  $name 已启动"
  fi
}

start_memory() {
  local name="$1" script="$2" run="$3" log="$4"
  if pgrep -f "$ROOT/memory/$script" >/dev/null; then
    echo "  $name 已在运行"
  else
    setsid nohup "$ROOT/memory/$run" > "$ROOT/$log" 2>&1 < /dev/null &
    disown
    echo "  $name 已启动"
  fi
}

start_cmd() {
  # name, check_pattern, workdir, command, log
  local name="$1" pat="$2" dir="$3" cmd="$4" log="$5"
  if pgrep -f "$pat" >/dev/null; then
    echo "  $name 已在运行"
  else
    setsid nohup bash -c "cd \"$dir\" && exec $cmd" > "$log" 2>&1 < /dev/null &
    disown
    echo "  $name 已启动"
  fi
}

echo "[3/6] 桥接..."
start_bridge "原始检测" "$ROOT/bridge/.venv/bin/python"      "bridge/frigate_alarm_bridge.py" "bridge/bridge.log"
start_bridge "行为分析" "$ROOT/bridge/.venv/bin/python"      "bridge/behavior_bridge.py"      "bridge/behavior.log"
start_bridge "人群聚集" "$ROOT/bridge/.venv/bin/python"      "bridge/crowd_bridge.py"         "bridge/crowd.log"
start_bridge "摔倒(ByteTrack)" "$ROOT/bridge/.venv-fall/bin/python" "bridge/fall_bridge_bytetrack.py" "bridge/fall_bt.log"
start_bridge "共现"     "$ROOT/bridge/.venv/bin/python"      "bridge/cooccur_bridge.py"        "bridge/cooccur.log"

echo "[3.5/6] 时空记忆（轨迹/基线/偏离/ReID/线索）..."
start_memory "轨迹写入" "track_writer.py" "run_writer.sh" "memory/writer.log"
start_memory "基线构建" "baseline_builder.py" "run_baseline.sh" "memory/baseline.log"
start_memory "偏离评分" "deviation_scorer.py" "run_scorer.sh" "memory/scorer.log"
start_memory "匿名ReID" "reid_embedder.py" "run_reid.sh" "memory/reid.log"
start_memory "线索挖掘" "clue_miner.py" "run_clue.sh" "memory/clue.log"

echo "[4/6] 看板 8080..."
start_cmd "看板" "uvicorn app:app" "$ROOT/dashboard" ".venv/bin/python -m uvicorn app:app --host 0.0.0.0 --port 8080" "$ROOT/dashboard/dashboard.log"

echo "[5/6] RuoYi 8081/9099..."
start_cmd "后端" "uvicorn server:app" "$ROOT/ruoyi/ruoyi-fastapi-backend" "env APP_ENV=pg ../backend-venv/bin/python -m uvicorn server:app --host 127.0.0.1 --port 9099" "/tmp/ruoyi.log"
start_cmd "前端" "ruoyi-fastapi-frontend/node_modules/.bin/vite" "$ROOT/ruoyi/ruoyi-fastapi-frontend" "npm run dev -- --host 0.0.0.0" "/tmp/ruoyi-front.log"

echo "[6/6] 归档器..."
start_cmd "归档器" "snapshot_archiver.py" "$ROOT/archive" "./run_archiver.sh" "$ROOT/archive/archiver.log"

echo "完成：监控已开启（看板 8080 / RuoYi 8081 / Frigate 5000）"
