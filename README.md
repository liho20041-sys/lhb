# spacetime-agent · 时空记忆智能体

公共安全监测预警原型：存量摄像头 → 持续行为理解 → 时空记忆 → 偏离候选 → 匿名 ReID → 线索池。

> **只分析行为，不识别身份。**

## 架构

```
Frigate (YOLO + ByteTrack) ──► 5 个桥接 ──► Kafka / PostgreSQL
        │
        ├── track_writer   → tracks（长期轨迹记忆）
        ├── baseline_builder → baselines（区域×时段正常基线）
        ├── deviation_scorer → deviation_candidates（偏离候选池）
        ├── reid_embedder  → track_embeddings / reid_links（匿名外观关联）
        └── clue_miner     → risk_clues（偏离聚集/异常时段/匿名回流/长期共现）

展示：Dashboard(8080) + RuoYi-FastAPI(8081)
```

## 技术栈

- 视频：Frigate 0.18.2（TensorRT 镜像）+ YOLO11n ONNX（GPU CUDA EP）+ NVDEC
- 中间件：PostgreSQL 15 / Redis 7 / Kafka 3.8 / Milvus 2.5 / MinIO（Docker Compose）
- 应用：FastAPI（看板）、RuoYi-FastAPI v1.6.2（管理后台）、Vue3 + Vite
- 算法：ByteTrack、torchvision Keypoint R-CNN（摔倒）、OSNet（匿名 ReID）

## 快速开始

```bash
# 启动全部服务（中间件 + Frigate + 桥接 + 时空记忆 + 看板 + RuoYi + 归档）
bash scripts/start_monitor.sh

# 停止
bash scripts/stop_monitor.sh                 # 停监控，保留看板/DB
bash scripts/stop_monitor.sh --alarms-only   # 只停告警生成，保留实时画面
bash scripts/stop_monitor.sh --all           # 全部停止

# 状态
bash scripts/status.sh
```

## 访问

- 监控看板：`http://<host>:8080`
- RuoYi 后台：`http://<host>:8081`（默认 `admin/admin123`，演示环境）
- Frigate：`http://<host>:5000`

## 目录

| 目录 | 内容 |
|---|---|
| `deploy/` | 中间件 docker-compose、部署记录 |
| `frigate/` | Frigate 配置、视频源 |
| `bridge/` | 目标检测/行为/聚集/摔倒/共现桥接 |
| `memory/` | 轨迹记忆、基线、偏离、ReID、线索挖掘 |
| `dashboard/` | 监控看板 FastAPI + 页面 |
| `ruoyi/` | 管理后台（RuoYi-FastAPI 后端 + Vue3 前端） |
| `archive/` | 告警快照归档与保留期清理 |
| `scripts/` | 一键启停/状态脚本 |
| `eval/` | 摔倒/徘徊数据集评估脚本与报告 |
| `docs/` | 文档、架构图、使用手册 |

## 说明

- 演示视频使用 CUHK Avenue（俯视校园步道），接真实摄像头请修改 `frigate/config/config.yml` 的 `path` 并重启 Frigate。
- 模型权重（`*.onnx`、`*.pt`）、数据集、媒体文件、venv、node_modules 不纳入仓库；按需重新生成/下载。
- 数据库密码、管理后台默认密码等仅用于演示环境，正式部署请改为环境变量并启用鉴权/验证码/HTTPS。
