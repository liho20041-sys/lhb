# 时空记忆智能体 · 上下文恢复摘要

> 更新时间：2026-11-08 / 项目根目录：`/home/bjutcv/data/lhb/spacetime-agent`

## 0. 一句话现状

已在单机 GPU 服务器上跑通 **检测 → 行为规则 → 轨迹记忆 → 正常基线 → 偏离候选 → 匿名 ReID → 线索池** 的最小闭环；用 CUHK Avenue 俯视视频演示，RuoYi + 自有看板可查看。**后端业务模块仍不全、使用示例视频、未接真实摄像头、对外仅 SSH 隧道**。

## 1. 项目背景与目标

- 来源文档：`时空记忆智能体-公共安全监测预警完整方案.html`；执行方案：`路径A-详细执行方案.md`、`路径A2-详细执行方案.md`
- 目标：面向存量摄像头，做低成本智能视觉传感组件，实现「事前预警—事中干预—事后回溯」
- **硬约束：只分析行为，不识别身份**
- 核心升级：单帧目标识别 → **基于时空记忆的持续行为理解**；显性异常 + 历史积累的隐性风险线索

## 2. 运行环境（已验证）

- Ubuntu 20.04；i9-10900X 20 线程；**2× RTX 3090 24GB**；62GB 内存
- 磁盘 916G，当前约 **21G 可用（98%）**，偏紧
- 内网 IP `172.21.13.32`（eno1）/ `10.21.9.206`（wifi）；**NAT 后，无公网 IP**
- Docker 25.0.0 + Compose v2.24.1；nvidia runtime 可用
- 代理 `127.0.0.1:7890`（HTTP）/ `7891`（SOCKS）；dockerd 已配置代理
- **frpc 运行中**：`/etc/frp/frpc.toml` → `106.13.98.182:7001`，当前仅映射 SSH `22 → 106.13.98.182:6022`
- tailscale 已安装但 daemon 未启动

## 3. 架构与数据流

```
Frigate(检测/跟踪/事件)
  ├─ /api/events, latest.jpg, snapshot-clean.webp
  ▼
[raw bridge] Frigate → Kafka(frigate-events) → kafka_messages → alarm_records
[behavior/crowd/fall/cooccur] 读 Frigate → kafka_messages + alarm_records
[track_writer]  Frigate → tracks（长期轨迹记忆）
[baseline_builder] tracks → baselines（区域×小时 median/MAD）
[deviation_scorer] tracks+baselines → deviation_candidates（候选池，非告警）
[reid_embedder]  Frigate干净快照裁人 → OSNet嵌入 → track_embeddings / reid_links
[clue_miner]     tracks/deviations/reid_links/alarm_records → risk_clues
```

## 4. 技术栈与版本（已验证）

**中间件（deploy/docker-compose.yml）**

| 组件 | 容器 | 端口 |
|---|---|---|
| PostgreSQL 15.4 | sp-postgres | `127.0.0.1:5432` |
| Redis 7 | sp-redis | `127.0.0.1:6379` |
| Kafka 3.8.0 (KRaft) | sp-kafka | `127.0.0.1:9092` |
| etcd 3.5.16 | sp-etcd | 内部 2379 |
| Milvus 2.5.14 | sp-milvus | 内部（无宿主端口） |
| MinIO 2025 | sp-minio | 内部（无宿主端口） |

**平台与算法**

- Frigate **0.18.2**，镜像 `ghcr.io/blakeblackshear/frigate:stable-tensorrt`（10.7GB）
- GPU 预留 `capabilities: [gpu, video]`；NVDEC `preset-nvidia-h264`
- ONNX 检测器 `device: GPU`（CUDA EP），`yolo11n.onnx`，`model_type: yolo-generic`
- 视频源：`frigate/media/avenue.mp4`（CUHK Avenue，640×360，25fps，54s 循环）
- 检测：`detect 640×360 @10fps`；实测 camera_fps 10、skipped ~0.2、推理 ~10ms
- 摔倒：torchvision Keypoint R-CNN + ByteTrack（`fall_bridge_bytetrack.py`）
- ReID：BoxMOT 26.0.0 OSNet `osnet-x0-25-msmt17.pt`，512 维，GPU
- RuoYi-FastAPI **v1.6.2** 后端 9099，Vue3+Vite 前端 8081，`admin/admin123`（验证码已关）
- Dashboard FastAPI 8080；CORS `*`

## 5. 目录与关键文件

```
spacetime-agent/
├── deploy/            docker-compose.yml, DEPLOY_RECORD.md（23 轮全过程记录）
├── frigate/           docker-compose.yml, media/avenue.mp4,
│                      config/{config.yml, config.yolo.yml, config.ssd.yml, coco80.txt, yolo11n.onnx}
├── bridge/            5 个桥接 + rules + state + .venv / .venv-fall
├── memory/            schema.sql, schema_phase2.sql, features.py, track_writer.py,
│                      baseline_builder.py, deviation_scorer.py, deviation_text.py,
│                      reid_embedder.py, clue_miner.py, run_*.sh
├── dashboard/         app.py, static/{monitor.html,index.html}, .venv, snapshots/
├── ruoyi/             ruoyi-fastapi-backend(v1.6.2), ruoyi-fastapi-frontend(Vue3)
├── archive/           snapshot_archiver.py, run_archiver.sh
├── scripts/           start_monitor.sh, stop_monitor.sh, status.sh
├── eval/              URFD/Loitering 评估脚本+数据+报告
├── yolo/              yolo11n.pt, ab_compare.py, results
├── netdisk/           pg, milvus, module_alarm0, project082608-yolotraining-main
└── docs/              README、架构图、使用手册
```

**已删除**：`netdisk/VideoPipe`(6G)、旧版 fall 脚本、旧示例视频、重复 ONNX、temp 文件。

## 6. 关键配置与参数

- DB DSN：`host=127.0.0.1 port=5432 dbname=prod_db user=prod_user password=SecurePwd@2025`
- Redis DB 2；Kafka topic `frigate-events`
- **Frigate 模型必须放根级 `model:`**（放 `detectors.onnx.model` 会被迁移丢弃）
- 偏离：`DEVIATION_THRESHOLD=8.0`，`MIN_SAMPLES=15`
- ReID：`REID_MIN_GAP=60s`、`REID_SIM_THRESHOLD=0.8`、`REID_TOP_K=3`
- 线索：`CLUE_INTERVAL=300s`，`CLUE_MIN_DEVIATION=3`
- 摔倒：`FALL_SUSTAIN=0.8s`、ByteTrack `min_hits=1, track_thresh=0.5`
- 归档：`ALARM_RETENTION_DAYS=30`（alarm_records / kafka_messages / 孤儿快照）

## 7. 主要接口（8080）

- `GET /` 统一监控首页；`GET /alarms` 告警详情页
- `GET /api/live.jpg`、`GET /api/live.mjpg`（MJPEG，~8fps）
- `GET /api/stats`、`GET /api/alarms`
- `GET /api/tracks`、`GET /api/deviations`、`GET /api/deviation_stats`、`PATCH /api/deviations/{id}`
- `GET /api/clues`、`GET /api/clues/stats`、`PATCH /api/clues/{id}`

RuoYi 页面：首页 Tab = **总览 / 实时监控 / 告警看板 / 偏离候选 / 线索池**；偏离候选含分数趋势曲线、选中轨迹曲线、每行迷你轨迹（悬停放大）、快照缩略图、问题描述。

## 8. 服务与启停命令

```bash
# 总启动/停止/状态
bash /home/bjutcv/data/lhb/spacetime-agent/scripts/start_monitor.sh
bash .../scripts/stop_monitor.sh            # 停监控，保留看板/RuoYi/DB
bash .../scripts/stop_monitor.sh --alarms-only   # 停桥接+记忆+归档，保留 Frigate 画面
bash .../scripts/stop_monitor.sh --all
bash .../scripts/status.sh
```

当前运行：5 个桥接 + 5 个记忆服务（track_writer/baseline_builder/deviation_scorer/reid_embedder/clue_miner）+ dashboard 8080 + RuoYi 8081/9099 + archiver + Frigate。

访问：
- 看板 `http://172.21.13.32:8080`
- RuoYi `http://172.21.13.32:8081`（admin/admin123）
- Frigate `http://172.21.13.32:5000`

外部访问：走 frp SSH `106.13.98.182:6022`，再 SSH 隧道转发 8081/8080/5000。

## 9. 已完成工作与关键决策

1. **中间件 + 端口收敛**：对外只留 5000/8080/8081/8554；9099/5432/6379/9092 绑 127.0.0.1；移除 8971/9000/9001/19530/9091。
2. **Frigate 切 YOLO ONNX**：CPU 版 943% CPU、10fps 跑不动 → 换 TensorRT 镜像 + CUDA EP，detect 640×360@10。
3. **直播改造**：1fps JPEG → MJPEG（~8fps）；快照/看板嵌入 RuoYi。
4. **品牌/UI**：RuoYi 改 `spacetime-agent`；登录页深色科技风；首页仪表盘+五 Tab。
5. **5 个行为桥接**：原始检测、逗留/徘徊、聚集、摔倒(ByteTrack)、共现。
6. **时空记忆 Phase 0/1**：tracks/baselines/deviation_candidates；问题描述生成器。
7. **Phase 2**：匿名 ReID（OSNet）+ 线索挖掘（deviation_cluster/odd_hour/return/companion）。
8. **启停统一**：记忆服务通过 `memory/run_*.sh` 并入总脚本，后台 `disown`。
9. **评估**：URFD 摔倒（ByteTrack+过渡 0.8s：P=0.852/R=0.767/F1=0.807）；Loitering（规则 F1=0.521，RF 上限 0.591）。报告在 `eval/*REPORT.md`。
10. **资产清理**：删 VideoPipe、旧脚本/视频、重复 ONNX；磁盘从 15G→21G 可用。

## 10. 当前数据/进度（最近一次核对）

- `tracks`：~500+（持续增长）
- `baselines`：3 组
- `deviation_candidates`：77+（pending，阈值 8.0）
- `track_embeddings`：120+；`reid_links`：212+（最高相似度 1.000，跨 ~109s）
- `risk_clues`：5 条（2 deviation_cluster + 3 return；odd_hour/companion 暂 0）
- Frigate 10fps / skipped ~0.2；8080、8081 均 200

## 11. 遇到的问题与解决

| 问题 | 解决 |
|---|---|
| Docker Hub/ghcr 慢/被墙 | dockerd 配代理；Frigate TensorRT 用 nju 源，Kafka 用 1panel |
| pgrep/pkill 匹配到自身导致工具被杀 | 用 `[f]oo` 括号技巧或脚本文件 |
| Frigate 模型配置迁移丢失 | 模型放根级 `model:` |
| 10fps CPU 跑不动 | TensorRT 镜像 + CUDA EP + 640×360 |
| `ped1080.webm` 解码崩溃 | 转 H.264 MP4 |
| Frigate 被 SIGTERM 停 | `docker compose up -d` 恢复 |
| dashboard 重复进程 | 按 8080 端口 owner 清理非监听者 |
| `el-image` 预览自动跳图 | 独立 ElImageViewer + 预览时暂停刷新 |
| 改 config 不生效 | 必须重启 Frigate |
| ReID 权重按 cwd 找不到 | 用绝对模型路径 |
| `.venv-fall` numpy 2.4.6 | boxmot 升级导致；评测用 base python |

## 12. 未解决 / 待确认

- **RuoYi 业务模块仍缺**：`module_camera_device`、`module_function_deployment`、`module_kafka_bridge`、`module_ai_inference` 等；相关菜单已隐藏。
- Milvus/MinIO 当前未被业务使用；ReID 用 PG JSON + numpy。
- **快照归档状态矛盾**：曾按要求删除全部归档快照并停归档器；但总启动脚本又把 archiver 拉起（PID 417672），现在会继续归档新告警。**需确认是否关闭归档**。
- 未接真实 RTSP；用的是 Avenue 示例（香港，非大陆）。
- `odd_hour` / `companion` 需更长历史与更多 cooccur 数据。
- 跨镜 ReID 需第二路摄像头。
- 安全：admin 默认密码、验证码关闭、看板无鉴权；对外前必须处理。
- 外部目前只有 SSH 隧道，没有公网网址。
- 磁盘 ~21G，偏紧。

## 13. 下一步建议

1. 先确认：**是否保留快照归档**（保留则定期清理；关闭则 `stop_pat snapshot_archiver` 或从总脚本移除）。
2. 接真实 RTSP（改 `frigate/config/config.yml` 的 `path` 并重启 Frigate）。
3. 安全加固：改 admin 密码、开验证码、看板加鉴权、HTTPS。
4. 若要公网访问：frp 增加 8081/8080 web 代理（注意页面写死 `:8080`），或 Cloudflare Tunnel/Tailscale。
5. 若要完整平台：补齐缺失的 RuoYi 业务模块，或基于公开 RuoYi 框架重建。
6. 数据侧：持续积累正常数据，校准偏离/线索阈值；接第二路相机做跨镜。

## 14. 事实分级

- **已验证事实**：端口、版本、接口、启停命令、当前服务/数据计数、Frigate 10fps/skipped、ReID 可用、线索 5 条、URFD/Loitering 指标。
- **暂定方案（可调）**：偏离阈值 8.0、ReID 0.8/60s/top3、线索阈值、Avenue 作为演示视频、PG JSON 向量方案。
- **待确认**：是否保留快照归档、真实摄像头与场景、是否公网、是否补齐 RuoYi 业务模块、是否引入 Milvus。
