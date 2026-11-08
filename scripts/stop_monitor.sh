#!/usr/bin/env bash
# 停止监控：桥接 + 归档器 + Frigate（默认保留看板/RuoYi/中间件，便于查看历史）
# 加 --all 连看板、RuoYi、中间件一起停
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
MODE="${1:-monitor}"

stop_pat() {
  local name="$1" pat="$2"
  local pids
  pids=$(pgrep -f "$pat" | grep -v "^$$\$" || true)
  if [ -n "$pids" ]; then
    kill $pids 2>/dev/null || true
    echo "  已停 $name"
  else
    echo "  $name 未运行"
  fi
}

echo "[1/4] 停止桥接..."
stop_pat "原始检测" "frigate_alarm_bridge.py"
stop_pat "行为分析" "behavior_bridge.py"
stop_pat "人群聚集" "crowd_bridge.py"
stop_pat "摔倒"     "fall_bridge"
stop_pat "共现"     "cooccur_bridge.py"
stop_pat "轨迹写入" "track_writer.py"
stop_pat "基线构建" "baseline_builder.py"
stop_pat "偏离评分" "deviation_scorer.py"
stop_pat "匿名ReID" "reid_embedder.py"
stop_pat "线索挖掘" "clue_miner.py"

echo "[2/4] 停止归档器..."
stop_pat "归档器" "snapshot_archiver.py"

if [ "$MODE" = "--alarms-only" ]; then
  echo "已停止告警生成（桥接+归档器），Frigate 画面仍在运行。"
  exit 0
fi

echo "[3/4] 停止 Frigate..."
docker compose -f frigate/docker-compose.yml stop

if [ "$MODE" = "--all" ]; then
  echo "[4/4] 停止看板 / RuoYi / 中间件..."
  stop_pat "看板" "uvicorn app:app"
  stop_pat "RuoYi 后端" "uvicorn server:app"
  stop_pat "RuoYi 前端" "ruoyi-fastapi-frontend/node_modules/.bin/vite"
  docker compose -f deploy/docker-compose.yml stop
  echo "全部已停止。"
else
  echo "[4/4] 看板/RuoYi/中间件保持运行（可用 --all 全部停止）"
  echo "监控已停止，历史数据仍可在 8080 / 8081 查看。"
fi
