#!/usr/bin/env bash
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
echo "=== 中间件 ==="
docker compose -f deploy/docker-compose.yml ps --format "table {{.Name}}\t{{.Status}}" 2>/dev/null
echo "=== Frigate ==="
docker compose -f frigate/docker-compose.yml ps --format "table {{.Name}}\t{{.Status}}" 2>/dev/null
echo "=== 桥接 ==="
pgrep -af "frigate_alarm_bridge.py|behavior_bridge.py|crowd_bridge.py|fall_bridge|cooccur_bridge.py" | grep -v pgrep || echo "  无"
echo "=== 时空记忆 ==="
pgrep -af "track_writer.py|baseline_builder.py|deviation_scorer.py|reid_embedder.py|clue_miner.py" | grep -v pgrep || echo "  无"

echo "=== 看板 / RuoYi / 归档 ==="
pgrep -af "uvicorn app:app|uvicorn server:app|ruoyi-fastapi-frontend/node_modules/.bin/vite|snapshot_archiver.py" | grep -v pgrep || echo "  无"
echo "=== 端口 ==="
for p in 5000 8080 8081 9099; do
  code=$(curl -s -o /dev/null -m 3 -w "%{http_code}" "http://127.0.0.1:$p/" 2>/dev/null || echo "000")
  echo "  $p -> $code"
done
