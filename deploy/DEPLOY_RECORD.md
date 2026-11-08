# 步骤 1 环境部署记录

- 部署日期：2026-11-04
- 部署目录：`/home/bjutcv/data/lhb/spacetime-agent/deploy`
- 编排文件：`deploy/docker-compose.yml`
- 目标：按《路径 A 详细执行方案》步骤 1，拉起平台基础中间件（PostgreSQL、Milvus、Kafka、MinIO）

---

## 一、部署结果总览

| 组件 | 容器名 | 镜像 | 版本 | 端口 | 状态 |
|---|---|---|---|---|---|
| PostgreSQL | sp-postgres | postgres:15.4 | 15.4 | 5432 | ✅ healthy |
| MinIO | sp-minio | quay.io/minio/minio:RELEASE.2025-06-13T11-33-47Z | 2025-06-13 | 9000 / 9001 | ✅ healthy |
| etcd | sp-etcd | quay.io/coreos/etcd:v3.5.16 | 3.5.16 | 内部 2379 | ✅ healthy |
| Milvus | sp-milvus | milvusdb/milvus:v2.5.14 | 2.5.14 | 19530 / 9091 | ✅ healthy |
| Kafka | sp-kafka | apache/kafka:3.8.0 | 3.8.0 (KRaft) | 9092 | ✅ healthy |

所有组件均在同一 Docker 网络 `sp-net`，数据使用 Docker 命名卷持久化。

---

## 二、连接信息

### PostgreSQL
- Host: `127.0.0.1` / Port: `5432`
- 用户：`prod_user`
- 密码：`SecurePwd@2025`
- 数据库：`prod_db`
- 初始化：已导入 `videopipe-fastapi/pg/public.sql`，当前 **40 张表**

### MinIO
- API: `http://127.0.0.1:9000`
- Console: `http://127.0.0.1:9001`
- 账号：`minioadmin`
- 密码：`minioadmin`

### Milvus
- 地址：`127.0.0.1:19530`
- 健康检查：`http://127.0.0.1:9091/healthz`
- 当前集合：空（待导入 schema）

### Kafka
- Bootstrap（宿主机）：`127.0.0.1:9092`
- 模式：KRaft 单节点（无 ZooKeeper）
- 已用测试 topic（`sp-healthcheck`）验证创建/列出，验证后已删除

---

## 三、验证记录

| 验证项 | 命令/方式 | 结果 |
|---|---|---|
| 容器健康 | `docker compose ps` | 5 个均 healthy |
| PostgreSQL 建库 | `psql -c "select count(*)..."` | 40 张表 |
| PostgreSQL 日志 | `docker logs sp-postgres` | 无 error/fatal |
| MinIO 健康 | `curl /minio/health/live` | HTTP 200 |
| Milvus 健康 | `curl :9091/healthz` | HTTP 200 |
| Milvus 连接 | pymilvus 连接并 `list_collections` | 连接成功，集合为空 |
| Kafka 可用 | 创建/列出/删除测试 topic | 成功 |

---

## 四、与仓库原始配置的差异（重要）

仓库 `videopipe-fastapi` 自带的两个 compose 文件未直接采用，原因与处理：

1. **`pg/docker-compose.yml`**：把数据挂到 `/opt/pg/*`（需 root 权限），本机无免密 sudo。
   → 改为 Docker 命名卷 `pg_data`，避免动系统目录。
2. **`milvus/docker-compose.yml`**：指定 `milvusdb/milvus:v2.6.7`（需从 Docker Hub 拉 ~2GB）。本机网络慢，且本地已有 `v2.5.14`。
   → 采用本地 `v2.5.14`，使用 etcd+MinIO 后端；未启用 2.6 的 `MQ_TYPE=woodpecker`（2.5 默认 rocksmq）。
3. **Kafka**：仓库未提供 compose 定义。→ 自行补充 `apache/kafka:3.8.0`（KRaft 单节点）。
4. 统一合并为 `deploy/docker-compose.yml`，MinIO 同时供 Milvus 与业务媒体存储复用。

---

## 五、仍未完成的部分（步骤 1 的缺口）

⚠️ **FastAPI 后端与 Vue3 前端未启动**。原因：GitHub 上的 `xuansan/videopipe-fastapi` 是**不完整上传**，仓库内只有：

- `module_alarm/`（报警模块）
- `pg/`（建库 SQL + compose）
- `milvus/`（compose + schema 导入脚本）
- `RuoYi-Vue3-FastAPI/`（仅 2 个脚本 + 3 份 md 文档）
- README（作者注明“AI 写的有问题还没改完”，并给了百度网盘完整包链接）

**缺失**：`requirements.txt`、后端入口 `main.py`/`app.py`、`web/` 前端工程、compose 主文件。因此本步骤只完成了**中间件基础环境**。

其他待办：
- Milvus schema JSON 缺失，`import_milvus_schema.py` 无法执行（缺输入文件）。
- Kafka 业务 topic 尚未创建（等后端确定 topic 名）。
- 仓库 `milvus/etcd.tar` 实为 etcd 镜像 tar 包，非数据备份，未使用。

---

## 六、日常操作

```bash
cd /home/bjutcv/data/lhb/spacetime-agent/deploy

docker compose up -d        # 启动
docker compose ps           # 查看状态
docker compose logs -f milvus
docker compose down         # 停止（保留数据卷）
docker compose down -v      # 停止并删除数据（慎用）
```

---

## 七、下一步建议

1. 向需求方/作者获取**完整源码包**（百度网盘链接见 README，提取码 `i4cy`），补齐后端与前端。
2. 拿到 `requirements.txt` 后建独立 venv，避免污染 conda base：
   `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
3. 启动后端：`uvicorn main:app --host 0.0.0.0 --port 8000`
4. 启动前端：`cd web && npm install && npm run dev`
5. 按后端配置创建 Kafka topic、导入 Milvus schema。

---

# 更新记录 · 2026-11-04（第二轮：接收网盘包 + 去重 + 补 Redis/Milvus）

## A. 新增中间件 Redis

架构文档要求 Redis（会话/缓存），已补充到 `docker-compose.yml`：

| 组件 | 容器 | 镜像 | 端口 | 状态 |
|---|---|---|---|---|
| Redis | sp-redis | redis:7-alpine | 6379 | ✅ `PING` -> `PONG` |

## B. Milvus schema 已导入

使用网盘包中的 `netdisk/milvus/milvus_schema_export.json` 执行导入：

- 集合：`face_trace`（数据库 `saisi`，描述「人脸轨迹」）
- 字段：id / face_vector / locate / camera_id / create_time / url
- 索引：`face_vector` -> IVF_FLAT (IP)
- 当前实体数：0

## C. 网盘包已解压并去重

新目录结构：

```
spacetime-agent/
├── netdisk/                 # 网盘包解压内容
│   ├── VideoPipe/           # C++ 视频结构化框架（含 build/TensorRT-YOLO）
│   ├── project082608-yolotraining-main/  # YOLO 可视化训练工具
│   ├── milvus/              # compose + schema + etcd/minio 镜像 tar
│   ├── pg/                  # 建库 SQL + compose
│   └── module_alarm0/       # 告警模块（RuoYi-FastAPI 业务模块）
├── docs/                    # 从旧 clone 保留的 README / 架构与修复文档 / 使用手册
├── deploy/                  # 中间件编排 + 本记录
├── 时空白记忆...方案.html
└── 路径A-详细执行方案.md
```

已删除的重复项：

- 旧的不完整 GitHub clone `videopipe-fastapi1/`（其 pg/milvus/module_alarm 与网盘版重复，文档已先备份到 `docs/`）
- 已解压的 5 个原始 zip（约 3.7GB）与临时 `~$...docx`
- `netdisk/milvus/milvus-v2.5.14.tar`（772MB，与已加载镜像 `milvusdb/milvus:v2.5.14` 完全重复）

## D. 关键结论：后端/前端源码仍不完整

对照架构文档要求的模块，网盘包只提供了 `module_alarm0`，其余全部缺失：

| 架构要求模块 | 是否存在 |
|---|---|
| module_admin（系统管理） | ❌ |
| module_ai_inference（AI 推理） | ❌ |
| module_alarm（告警） | ✅ module_alarm0 |
| module_camera_device（摄像头设备） | ❌ |
| module_function_deployment（功能部署） | ❌ |
| module_streaming（流媒体） | ❌ |
| module_face_search（人脸检索） | ❌ |
| module_kafka_bridge（Kafka 桥接） | ❌ |
| module_minio（对象存储） | ❌ |
| module_monitor（系统监控） | ❌ |
| module_vp（视频管道） | ❌ |
| 后端入口 `server.py` | ❌（网盘内只有训练工具的 `backend/main.py`） |
| 前端 Vue3 工程 | ❌ |

即：**中间件（PG/Redis/MinIO/Kafka/Milvus）已全部就绪，但平台后端与前端源码仍然缺失，无法启动**。
网盘包提供的是"支撑资产"（VideoPipe C++ 引擎、Milvus 配置、PG 备份、告警模块、训练工具），不是完整可运行的 FastAPI/Vue3 平台。

## E. 下一步

需要向作者/需求方再索取以下任一项：

1. 完整后端工程（含 `server.py`、`module_admin`、`module_camera_device`、`module_function_deployment`、`module_kafka_bridge`、`module_ai_inference`、`module_face_search`、`module_streaming`、`module_monitor`、`module_vp`、`requirements.txt`）；
2. 或完整前端工程（Vue3，含 `views/device`、`views/alarm`、`views/deployment`、`views/dashboard`）；
3. 若拿不到，可基于公开 `RuoYi-Vue3-FastAPI` 框架 + `module_alarm0` 重建，但业务模块需重新开发，工作量较大。

---

# 更新记录 · 2026-11-04（第三轮：切换到路径 A2 + 资产清理）

## A. 方案切换

当前有效方案改为 `../路径A2-详细执行方案.md`（初版 `路径A-详细执行方案.md` 作为基线保留）。A2 的核心改进：

- 新增 Step 0：源码/资产/合规闸门
- 中间件补 Redis（已部署）
- 启动约定修正：后端 `server.py:9099`、前端 `8080`
- "预置检测"改为"VideoPipe 能力盘点"
- 记忆基座对齐现有 40 张表
- 新增隐私红线决策（`face_trace`）

## B. 本轮清理（释放 1.3GB，netdisk 7.7G → 6.3G）

已删除：
- 480 个 Windows `*Zone.Identifier*` 元数据文件
- VideoPipe 根目录误生成垃圾文件（`how HEAD --name-only`、`rc`、`orRT-YOLO...` 命令残片）
- 0/1 字节空文件（`FINAL_FIX_GUIDE.md`、`REBUILD_INSTRUCTIONS.md`、`MINIO_UPLOAD_FIX.md`、`rebuild.sh`、`rebuild_videoPipe_fixed.bat`）
- `netdisk/VideoPipe/miniotest.zip`（15MB，与已解压 `miniotest/` 重复）
- `netdisk/milvus/etcd.tar`、`minio.tar`（77MB，镜像已在本地/运行，离线 tar 冗余）
- `project082608-yolotraining-main/{app,frontend}/node_modules`（743MB，可 `npm install` 重建）
- `VideoPipe/vcpkg/{buildtrees,packages}`（582MB，构建缓存可重建；`downloads` 保留供离线构建）

保留：
- `netdisk/{VideoPipe, module_alarm0, pg, milvus, project082608-yolotraining-main}`
- `docs/`、`deploy/`、两份方案文档、原始方案 HTML

## C. 清理后复核

- 中间件 6 个容器仍全部 healthy
- PostgreSQL 40 张表未受影响

---

# 更新记录 · 2026-11-04（第四轮：A2 决策落地 + Frigate 跑通）

## A. 决策落地

| 决策 | 选择 | 执行 |
|---|---|---|
| 分析引擎 | 4B：Frigate 快速验证 | 已部署 Frigate 0.18.2 |
| 隐私红线 | 只分析行为、不识别身份 | **已删除 Milvus 集合 `face_trace`**，当前集合为空 |

## B. Frigate 部署（`frigate/` 目录）

| 项目 | 内容 |
|---|---|
| 镜像 | `ghcr.io/blakeblackshear/frigate:stable`（0.18.2），经南大源 `ghcr.nju.edu.cn` 拉取 |
| 容器 | `frigate`，healthy |
| 端口 | 5000（Web/API）、8971（认证端口）、8554（go2rtc） |
| 配置 | `frigate/config/config.yml` |
| 输入 | `frigate/media/sample.mp4`（768×432，12fps，53.9s，循环播放） |
| 检测器 | CPU（演示用，推理 17.85ms/帧） |
| 鉴权 | 关闭（`auth.enabled: false`，仅演示环境） |

**验证结果**
- `GET http://127.0.0.1:5000/api/version` -> `0.18.2-cfa08c5`
- `GET /api/stats`：camera_fps=2.0，process_fps=2.0，detector inference_speed=17.85
- 已检出事件：`person @ demo`，`has_snapshot: true`
- 快照已生成：`frigate/media/frigate/clips/thumbs/demo/*.webp`
- Web UI：`http://<本机IP>:5000` -> HTTP 200

## C. 说明与后续

1. CPU 检测器只适合验证；接真实多路摄像头时需换 GPU/TensorRT/OpenVINO。
2. Frigate 只做通用目标检测（person/bicycle/car），**徘徊/聚集/摔倒/共现等行为语义仍需后补**（规则或 VideoPipe）。
3. 下一步可做：
   - ~~Frigate 事件 → 桥接写入 `kafka_messages` → `alarm_records`（打通告警链路）~~ ✅ 已完成（见第五轮）
   - 或先补 RuoYi-FastAPI 管理底座（A2 Step 1）

---

# 更新记录 · 2026-11-04（第五轮：检测→告警闭环打通）

## A. 新增桥接服务（`bridge/`）

链路：

```
Frigate /api/events
  → Kafka topic: frigate-events
  → PostgreSQL 表: kafka_messages
  → PostgreSQL 表: alarm_records
```

- 脚本：`bridge/frigate_alarm_bridge.py`
- 启动：`bridge/run.sh`（首次自动建 venv 并装 `kafka-python`、`psycopg2-binary`）
- 依赖：独立 venv `bridge/.venv`，不污染 conda base
- 去重：以 `event_id` 去重，重复运行不会产生重复告警
- 字段映射对齐 `module_alarm0/alert_sync_service.py`，并补充写入
  `event_type / camera_id / confidence / bbox_* / alert_level / status / raw_data`

## B. 验证结果（实机）

| 检查项 | 结果 |
|---|---|
| Kafka topic | `frigate-events` 已创建 |
| kafka_messages | 11 条（含 event_id / detected_object / confidence） |
| alarm_records | 共 26 条（15 条种子 + 11 条桥接） |
| 样例 | `person 置信度 0.77 alert_level=high status=active` |
| bbox | 已按 768×432 还原为像素坐标 |
| 桥接进程 | 持续运行，每 3s 轮询 |

## C. 说明

- 该桥接**复刻**了缺失的 `module_kafka_bridge` 的职责，但不是原模块；后续接入 RuoYi 时可替换。
- 行为语义（徘徊/聚集/摔倒/共现）仍未实现；Frigate 事件里已有 `path_data`（轨迹点），可作为"六种线"的输入。
- 生产化建议：将 bridge 做成 systemd 服务或容器，加入失败重试与监控。

---

# 更新记录 · 2026-11-04（第六轮：徘徊 / 异常逗留规则）

## A. 新增行为规则

文件：
- `bridge/behavior_rules.py`：特征计算 + 规则（纯函数）
- `bridge/behavior_bridge.py`：轮询 Frigate → 规则 → `kafka_messages` → `alarm_records`
- `bridge/run_behavior.sh`：启动脚本

特征（基于 Frigate `data.path_data`，只用位置+时间，不涉及人脸）：
`duration / path_length / displacement / path_efficiency / reversals / extent / dwell_time`

规则：
| 规则 | 条件（可调） | 告警名 |
|---|---|---|
| abnormal_dwell | 时长 ≥5s，活动范围 ≤0.06，位移 ≤0.09 | 异常逗留 |
| pacing | 时长 ≥5s，路径长 ≥0.15，效率 ≤0.45，方向反转 ≥2 | 反复徘徊 |

## B. 规则自测（合成轨迹）

| 用例 | 结果 |
|---|---|
| 原地小范围 30s | 触发「异常逗留」 |
| 左右往返 30s | 触发「反复徘徊」 |
| 直线穿行 10s | 不触发（正确） |

## C. 实时验证（Frigate aisle 视频）

已产生的行为告警（`create_by=behavior_rule`）：

| id | event_type | event_name | alert_level | details |
|---|---|---|---|---|
| 5326 | pacing | 反复徘徊 | high | person 持续 9.49s，效率 0.209，反转 2 次 |
| 5327 | abnormal_dwell | 异常逗留 | high | car 停留 8.0s，范围 0.0255 |
| 5330 | pacing | 反复徘徊 | high | person 持续 7.01s，效率 0.225，反转 3 次 |
| 5331 | pacing | 反复徘徊 | high | person 持续 24.0s，效率 0.354，反转 2 次 |
| 5333 | abnormal_dwell | 异常逗留 | high | person 停留 6.99s，范围 0.0026 |

## D. 运行

- 持续运行：`bridge/run_behavior.sh`（后台已启动）
- 单轮：`bridge/run_behavior.sh --once`
- 规则自测：`bridge/run_behavior.sh --selftest`

## E. 说明

- 阈值是为演示设定的较低值（5s），真实场景应按区域和时段调整（对齐方案 A2 的"区域分层阈值"）。
- 当前实现「异常逗留 / 反复徘徊」；「摔倒」需姿态/VideoPipe，「共现」需多轨迹关联，均待后续。
- 去重键为 `event_id:rule`，重复运行不会产生重复告警。

---

# 更新记录 · 2026-11-04（第七轮：人群聚集规则）

## A. 新增人群聚集检测（`bridge/crowd_bridge.py`）

判定：在归一化区域内，同时在场的 `person` 数量 ≥ `CROWD_MIN_COUNT`，
并持续 ≥ `CROWD_SUSTAIN` 秒，触发一次「人群聚集」。

| 参数 | 默认 | 说明 |
|---|---|---|
| CROWD_MIN_COUNT | 3 | 触发人数 |
| CROWD_SUSTAIN | 5s | 持续时长 |
| CROWD_COOLDOWN | 30s | 冷却 |
| CROWD_REGION | 0,0,1,1 | 归一化区域 x1,y1,x2,y2 |

- 同时在场的判定：事件 `start_time <= now <= end_time`，位置取 `path_data` 最后一点或 box 中心
- 输出：`alarm_records.event_type='crowd'`、`event_name='人群聚集'`
- 脚本：`bridge/run_crowd.sh`

## B. 验证

- 自测：4 个活跃 person（含 1 个已结束）-> 正确计为 4
- 实时（aisle 视频，同时在场最高 5 人）：
  - `人群聚集：区域内 4 人，持续 6s`（medium, conf 0.67）
  - `人群聚集：区域内 3 人，持续 9s`（medium, conf 0.50）

## C. 当前全部桥接进程

| 进程 | 职责 |
|---|---|
| frigate_alarm_bridge.py | 目标检测 → Kafka → kafka_messages → alarm_records |
| behavior_bridge.py | 异常逗留 / 反复徘徊 |
| crowd_bridge.py | 人群聚集 |

## D. 尚未实现

- 共现：需多轨迹长期关联（跨时段/跨镜）
- 越线/禁区：可基于 Frigate zones + 规则补充

---

# 更新记录 · 2026-11-04（第八轮：摔倒检测 · 姿态模型）

## A. 方案

- 姿态模型：**torchvision Keypoint R-CNN (ResNet50-FPN)**，BSD 许可，避开 Ultralytics 的 AGPL
- 运行：GPU（2×RTX 3090），从 Frigate `/api/demo/latest.jpg` 取实时帧，约 0.5s/帧
- 文件：
  - `bridge/fall_rules.py`：COCO 17 关键点 → 摔倒判定
  - `bridge/fall_bridge.py`：取帧 → 姿态 → 规则 → `kafka_messages` → `alarm_records`
  - `bridge/run_fall.sh`
  - 独立环境 `bridge/.venv-fall`（`--system-site-packages` 继承 torch）

## B. 判定规则（三选二）

1. 躯干接近水平：肩中点→髋中点 与竖直夹角 ≥ 55°
2. 头低于髋：鼻子 y > 髋中点 y + 5% 人体框高
3. 宽高比 ≥ 1.1（横躺）

持续 ≥ 1.5s 触发一次，冷却 60s。

## C. 验证

| 用例 | 结果 |
|---|---|
| 合成站姿 | `fall_score=0`，未触发 |
| 合成横躺 | `torso_angle=84.3°`，`aspect=2.33`，`fall_score=2`，触发 |
| 实时帧（aisle） | 6 人全部站姿（角度 0.7°–14.1°），fallen=0，无假报 |
| 持续运行 | `cycle=40 persons=4 fallen=0` |

## D. 当前全部桥接进程

| 进程 | 职责 | 环境 |
|---|---|---|
| frigate_alarm_bridge.py | 目标检测 → Kafka → 入库 | .venv |
| behavior_bridge.py | 异常逗留 / 反复徘徊 | .venv |
| crowd_bridge.py | 人群聚集 | .venv |
| fall_bridge.py | 摔倒（姿态） | .venv-fall |

## E. 说明

- 当前示例视频无真实摔倒，故未产生摔倒告警；规则已在合成横躺姿态上验证。
- 如需真实正例验证，可提供 Le2i / URFD / SisFall 的 RGB 视频片段。
- 摔倒为单帧姿态 + 持续判据，后续可加入时序动作模型（如 STS/慢动作）降低"蹲下/弯腰"误报。

---

# 更新记录 · 2026-11-04（第九轮：共现规则）

## A. 新增共现检测（`bridge/cooccur_bridge.py`）

判定：同一相机内两条 person 轨迹，在重叠时段按 1s 采样，
距离 ≤ `CO_DIST` 的连续时长 ≥ `CO_SUSTAIN`，触发「共现」。

| 参数 | 默认 | 说明 |
|---|---|---|
| CO_DIST | 0.08 | 归一化距离阈值 |
| CO_SUSTAIN | 8s | 持续接近时长 |
| CO_MIN_OVERLAP | 8s | 最小重叠时长 |
| EVENT_WINDOW | 90s | 分析窗口 |

- 轨迹插值：在采样时刻对前后轨迹点线性插值
- 去重键：`cooccur-<camera>-<eventA>-<eventB>`（按 ID 排序）
- 输出：`event_type='cooccur'`、`event_name='共现'`
- 脚本：`bridge/run_cooccur.sh`

## B. 验证

| 用例 | 结果 |
|---|---|
| 合成同行（距离 0.036，15s） | 触发，sustained=16s ✅ |
| 合成迎面而过 | 不触发 ✅ |
| 实时 people 视频（180s / 20 人） | 最近一对距离 0.041，仅持续 3s，无 8s 候选 → 0 告警（无误报） |

## C. 当前全部桥接进程（5 个）

| 进程 | 职责 |
|---|---|
| frigate_alarm_bridge.py | 目标检测 → Kafka → 入库 |
| behavior_bridge.py | 异常逗留 / 反复徘徊 |
| crowd_bridge.py | 人群聚集 |
| fall_bridge.py | 摔倒（姿态） |
| cooccur_bridge.py | 共现（短时同相机） |

## D. 说明

- 当前共现是**同相机、短时**版本；跨相机/跨天的长期共现需要 ReID（匿名外观向量），属后续。
- 若需要正例演示，可提供"两人结伴同行"的视频片段，或临时调低 `CO_SUSTAIN`。

---

# 更新记录 · 2026-11-04（第十轮：告警看板 / 接口）

## A. 新增看板服务（`dashboard/`）

- 技术：FastAPI + PostgreSQL + 单页 HTML（无外部 CDN，离线可用）
- 端口：**8080**
- 启动：`dashboard/run.sh`（`.venv` 继承系统 fastapi/uvicorn，安装 psycopg2）
- 文件：
  - `dashboard/app.py`：API
  - `dashboard/static/index.html`：看板页面
  - `dashboard/run.sh`

## B. 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 看板页面 |
| GET | `/api/health` | 健康检查 |
| GET | `/api/stats` | 总数/待处理/已处理/按类型/按等级/近24h |
| GET | `/api/alarms` | 列表，支持 `event_type/status/camera/limit/offset` |
| GET | `/api/alarms/{id}` | 详情 |
| PATCH | `/api/alarms/{id}` | 更新状态 `active/handled/ignored` |

## C. 页面功能

- 顶部统计卡：总数、待处理、已处理、类型数
- 按类型 / 按等级分布条形图
- 近 24h 时间线
- 告警列表：时间、摄像头、类型、详情、等级、状态、快照、处理
- 类型/状态筛选、每 5s 自动刷新、"处理"按钮

## D. 验证

- `GET /api/health` -> `{"ok": true}`
- `GET /` -> HTTP 200
- `GET /api/stats` -> total=231, active=230（处理后）
- `GET /api/alarms?limit=3` -> 正常返回
- `GET /api/alarms?event_type=crowd` -> 12 条
- `PATCH /api/alarms/5520 {"status":"handled"}` -> `{"ok":true,...}`，active 从 231 → 230

## E. 访问

- 本机：`http://127.0.0.1:8080`
- 局域网：`http://<本机IP>:8080`

## F. 当前服务

| 服务 | 端口 |
|---|---|
| Frigate | 5000 |
| 告警看板 | 8080 |
| 中间件 | 5432 / 6379 / 9000 / 9092 / 19530 |
| 5 个桥接进程 | 后台 |

---

# 更新记录 · 2026-11-04（第十一轮：接入 RuoYi 管理后台）

## A. 选型

- 框架：**RuoYi-FastAPI v1.6.2**（2025-03-19）
- 原因：`module_alarm0` 的 19 个依赖路径与 v1.6.2 **完全匹配**（`config.constant`、`config.database.AsyncSessionLocal`、`module_admin.annotation.*`、`module_admin.aspect.interface_auth` 等）；v1.8+ 已重构、2.0 差异更大
- 位置：`ruoyi/`（后端 `ruoyi-fastapi-backend`，前端 `ruoyi-fastapi-frontend`）

## B. 后端

| 项 | 值 |
|---|---|
| 运行环境 | `ruoyi/backend-venv`（Python 3.11） |
| 数据库 | 直连现有 `sp-postgres:5432/prod_db`（sys_* 与业务表都在） |
| Redis | `sp-redis:6379`，DB 2 |
| 配置文件 | `ruoyi-fastapi-backend/.env.pg` |
| 端口 | **9099** |
| 启动 | `APP_ENV=pg ../backend-venv/bin/python -m uvicorn server:app --host 0.0.0.0 --port 9099` |

## C. 前端

| 项 | 值 |
|---|---|
| 技术 | Vue3 + Vite 5.3.2 |
| 依赖 | `npm install`（npmmirror），654 包 / 532MB |
| 端口 | **8081**（默认 80 被 ragflow 占用，已改） |
| 代理 | `/dev-api` -> `http://127.0.0.1:9099` |
| 启动 | `npm run dev -- --host 0.0.0.0` |

## D. module_alarm 接入

- 复制 `netdisk/module_alarm0` -> `ruoyi-fastapi-backend/module_alarm`
- 在 `server.py` 注册：
  - `alarmController`（前缀 `/alarm/alarm`）
  - `alarmviewController`（前缀 `/alarmview`）

接口验证：
- `GET /alarmview/list` -> 360 条告警（含快照 URL）
- `GET /alarm/alarm/list?pageNum=1&pageSize=3` -> 正常返回

## E. 启动过程中修复的问题

| 问题 | 处理 |
|---|---|
| `sys_job` 里 `module_task.calibration_cleanup` 不存在导致启动失败 | 将 job_id 100/101 状态置 `1`（暂停） |
| passlib 1.7.4 + bcrypt 5.0 登录报 "password cannot be longer than 72 bytes" | 降级 `bcrypt==4.0.1` |
| 验证码阻碍 API 登录 | DB + Redis 关闭 `sys.account.captchaEnabled`（仅演示） |

## F. 访问

- 前端：`http://172.21.13.32:8081`（或本机 `http://127.0.0.1:8081`）
- 账号：`admin` / `admin123`
- 后端 API：`http://127.0.0.1:9099`
- 已通过前端代理验证：登录成功、菜单含 `Alarm / Device / Keyperson / Push / System`

## G. 已知缺口

- 平台业务模块 `module_camera_device`、`module_function_deployment`、`module_kafka_bridge`、`module_ai_inference` 等仍缺失；`Device / Keyperson / Push` 菜单页面点进去可能 404（后端无对应模块）
- 当前可用：系统管理（用户/角色/菜单/部门/日志）、**告警管理（module_alarm）**
- 演示环境关闭了验证码、使用默认密码，生产必须改回

---

# 更新记录 · 2026-11-04（第十二轮：Frigate 切换 YOLO ONNX + A/B 对比）

## A. 模型导出

- 源权重：`netdisk/project082608-yolotraining-main/backend/yolo11n.pt`
- 导出：Ultralytics `yolo11n.onnx`，imgsz=640，opset=12，`nms=False`
- 输出：`[1, 84, 8400]`（原始 YOLO 输出，由 Frigate 做 NMS）
- 文件：`yolo/yolo11n.onnx`（10.2MB）、`frigate/config/yolo11n.onnx`、`frigate/config/coco80.txt`

## B. Frigate 配置要点

Frigate 0.18 的模型配置必须放在**根级 `model:`**（放在 `detectors.onnx.model` 会被迁移丢弃）：

```yaml
model:
  path: /config/yolo11n.onnx
  model_type: yolo-generic
  width: 640
  height: 640
  input_tensor: nchw
  input_pixel_format: rgb
  input_dtype: float
  labelmap_path: /config/coco80.txt
detectors:
  onnx:
    type: onnx
    device: CPU
```

配置文件：
- `frigate/config/config.yolo.yml`（YOLO，当前启用）
- `frigate/config/config.ssd.yml`（SSD，可回退）

## C. 同视频 A/B 对比（people.mp4，各 120s）

| 指标 | SSD (ssdlite_mobilenet_v2) | YOLO11n ONNX |
|---|---|---|
| 推理耗时 | **15.06 ms** | 42.84 ms |
| detection_fps | **5.47** | 3.60 |
| person 事件数 | 16 | 16 |
| 平均置信度 | 0.830 | **0.891** |
| P50 / P90 | 0.838 / 0.844 | **0.902 / 0.918** |
| 最低置信度 | 0.750 | **0.827** |
| 大目标(>5%) | 14 | 12 |
| 小目标(<1%) | 0 | 0 |

结论：
- 该视频目标大且清晰，两者**检出数量相同**；YOLO 置信度平均高约 6 个百分点
- SSD 在 CPU 上快约 2.8 倍
- 要体现 YOLO 的召回优势，需用**小目标/遮挡**视频再测

## D. 回退方式

```bash
cd frigate
cp config/config.ssd.yml config/config.yml
docker compose restart
```

## E. 说明

- 当前 Frigate 使用 YOLO ONNX（CPU），inference 约 28—43ms
- 生产 8 路 1080p 建议将 YOLO 转 TensorRT / ONNX CUDA，CPU 不够
- Ultralytics YOLO 许可为 **AGPL-3.0**，政务/商业闭源交付需评估，可换 YOLOX/PP-YOLOE(Apache-2.0)

---

# 更新记录 · 2026-11-04（第十三轮：看板加"带框实时画面"）

## A. 新增

- `dashboard/app.py` 新增 `GET /api/live.jpg`：
  - 拉取 Frigate `/api/demo/latest.jpg`（1280×720）
  - 从 `/api/events` 取当前活动目标（person/bicycle/car/motorcycle/bus/truck）
  - 用 Pillow 叠加边界框 + 标签 + 置信度
  - 返回 JPEG，`Cache-Control: no-store`
- `dashboard/static/index.html` 顶部新增「实时画面（带检测框）」面板：
  - 每 1 秒预加载刷新（无闪烁）
  - 右上角「原图」链接

## B. 验证

| 项 | 结果 |
|---|---|
| `GET /api/live.jpg` | HTTP 200，image/jpeg，1280×720，约 136KB |
| 框像素检测 | person 框颜色约 28216 px（已绘制） |
| 页面包含面板 | 是 |
| 看板首页 | HTTP 200 |

## C. 说明

- 这是服务端绘框，**不依赖 Frigate 前端开关**，任何浏览器打开 8080 都能看到框
- Frigate 原面板仍可用 `http://<IP>:5000/?debug=true` 或 UI 里勾选 Bounding boxes
- 每秒刷新一次；多用户访问会增加 Frigate 请求量，生产可加缓存/降频

---

# 更新记录 · 2026-11-04（第十四轮：统一监控首页）

## A. 页面结构（8080）

| 路径 | 页面 | 说明 |
|---|---|---|
| `/` | **统一监控首页** `monitor.html` | 实时画面(带框) + 告警流 + 三入口 |
| `/alarms` | 告警看板 `index.html` | 统计/筛选/处理/快照（原看板） |
| `/api/live.jpg` | 带框实时帧 | 服务端绘框，1s 刷新 |
| `/api/stats`、`/api/alarms` | 数据接口 | 供两个页面使用 |

## B. 统一首页包含

1. **三个入口卡片**（自动按当前 host 生成）：
   - Frigate 实时监控 `http://<host>:5000`
   - 告警看板（详情） `/alarms`
   - RuoYi 管理后台 `http://<host>:8081`
2. **实时画面（带检测框）**：`/api/live.jpg`，每 1s 刷新
3. **实时告警流**：最近 30 条，每 3s 刷新；新告警高亮闪烁；带快照链接
4. **统计条**：总数/待处理/徘徊/逗留/聚集/共现，每 5s 刷新

## C. 验证

- `GET /` -> HTTP 200，含"统一监控首页"
- `GET /alarms` -> HTTP 200
- `GET /api/live.jpg` -> HTTP 200，image/jpeg，约 130KB
- 局域网 `http://172.21.13.32:8080/` -> HTTP 200

## D. 访问

- 统一首页：`http://172.21.13.32:8080`
- 告警详情：`http://172.21.13.32:8080/alarms`
- Frigate：`http://172.21.13.32:5000`
- RuoYi：`http://172.21.13.32:8081`（admin/admin123）

---

# 更新记录 · 2026-11-04（第十五轮：修复 RuoYi "啥也看不了"）

## A. 问题定位

- RuoYi 首页 `dashboard/index.vue` 是**占位演示页**（项目数/团队排名等假数据）
- `sys_menu` 里 Device/Algorithm/Push/Trace 等菜单的 `component` 在前端 **不存在** → 点开空白/404
- 告警菜单 `alarm/alarmview/index` 也没有前端页面

## B. 修复内容

1. **首页改为监控画面**
   - `src/views/dashboard/index.vue` 重写为 iframe，内嵌 `http://<host>:8080/` 统一监控首页
   - 8080 无 `X-Frame-Options`，可正常嵌入
2. **新增告警页面**
   - `src/api/alarm.js`：`listAlarm` → `/alarm/alarm/list`
   - `src/views/alarm/alarmview/index.vue`：Element Plus 表格，5s 自动刷新，快照可预览
3. **告警排序修正**
   - `module_alarm/dao/alarm_dao.py`：`order_by(id)` → `order_by(id.desc())`，**最新在前**
4. **隐藏无页面的菜单（18 个）**
   - 隐藏：系统概况、算法仓库、推送管理(4)、设备管理(摄像头/功能部署/管道监控)、重点人员、数据大屏、关于我们、授权情况、轨迹查询、进程监控
   - 保留：首页、系统管理、系统监控、系统工具、告警管理→告警查看、个人中心

## C. 验证

| 项 | 结果 |
|---|---|
| 8081 首页 | HTTP 200 |
| dashboard/alarmview 模块编译 | HTTP 200 |
| `/alarm/alarm/list?pageNum=1&pageSize=3` | code 200，total 24126，**最新 id 29415 在最前** |
| 8080 可 iframe | 无 X-Frame-Options/CSP |

## D. 使用

1. 打开 `http://172.21.13.32:8081`，**Ctrl+F5 强刷**；若菜单仍为旧版，退出重新登录
2. 首页 = 统一监控（实时画面 + 告警流）
3. 告警管理 → 告警查看 = 最新告警表格（含快照）
4. 隐藏的菜单在补齐对应后端/前端后可恢复（`sys_menu.visible='0'`）

---

# 更新记录 · 2026-11-04（第十六轮：端口收敛）

## A. 改动

### 中间件 `deploy/docker-compose.yml`
| 端口 | 改前 | 改后 |
|---|---|---|
| 5432 PostgreSQL | 0.0.0.0 | **127.0.0.1** |
| 6379 Redis | 0.0.0.0 | **127.0.0.1** |
| 9092 Kafka | 0.0.0.0 | **127.0.0.1** |
| 9000/9001 MinIO | 0.0.0.0 | **不发布**（仅容器内网） |
| 19530/9091 Milvus | 0.0.0.0 | **不发布**（仅容器内网） |

### Frigate `frigate/docker-compose.yml`
- 移除 `8971`（认证 UI，当前 `auth.enabled: false`）
- 保留 `5000`（画面/API）、`8554`（go2rtc RTSP）

### RuoYi 后端
- 启动改为 `--host 127.0.0.1 --port 9099`（由 8081 的 Vite 代理访问）

## B. 收敛后的端口

**对外 0.0.0.0（本项目相关）**
- 5000 Frigate 画面/API
- 8080 监控大屏
- 8081 RuoYi 前台
- 8554 go2rtc RTSP（按需）

**仅本机 127.0.0.1**
- 5432 PostgreSQL / 6379 Redis / 9092 Kafka / 9099 RuoYi 后端

**已移除**
- 8971 / 9000 / 9001 / 19530 / 9091

> 80/443/9380-9382/1200 是预装的 ragflow / Elasticsearch，不属于本项目。

## C. 重启与验证

- `deploy` 全部容器已重建，数据卷保留
- Frigate 已重建（无 8971）
- 5 个桥接已重启并恢复：
  - 原始检测 / 行为(逗留·徘徊) / 聚集 / 摔倒 / 共现
- 服务检查：Frigate 5000=200、看板 8080=200、RuoYi 8081=200、后端 9099 本机可用
- 端口检查：8971/9000/9001/19530/9091 已无监听

## D. 注意事项

- Milvus/MinIO 不再对宿主机暴露；如需 `pymilvus` 导入，可临时加回端口或用 `docker exec` 在网络内执行
- 若以后要恢复 Frigate 认证 UI，改回 8971 映射并开启 `auth.enabled`
- 桥接进程目前仍是 setsid 裸进程，建议后续做成 systemd/容器（见改进建议）

---

# 更新记录 · 2026-11-05（第十七轮：告警快照归档 + 保留期清理）

## A. 数据库

`alarm_records` 新增：
- `snapshot_archived boolean default false`
- `snapshot_original varchar(500)`（保留原始 Frigate URL）
- `snapshot_attempts integer default 0`
- 索引 `idx_alarm_snapshot_pending`

## B. 归档器（`archive/`）

- `archive/snapshot_archiver.py`：轮询未归档告警，下载快照到 `dashboard/snapshots/<id>.jpg`，
  成功后把 `snapshot` 改写为 `/snapshots/<id>.jpg`，原始 URL 存 `snapshot_original`
- 失效 URL 重试 3 次后清空 `snapshot`（避免坏图）
- `archive/run_archiver.sh`：启动脚本
- 参数：`ALARM_RETENTION_DAYS=30`、`BATCH_SIZE=200`、`POLL_INTERVAL=10`、`CLEANUP_INTERVAL=3600`

## C. 保留期清理

归档器每小时执行：
- 删除 `create_time < now() - 30 days` 的 `alarm_records`
- 删除 `created_at < now() - 30 days` 的 `kafka_messages`
- 删除不再被任何告警引用的孤儿快照文件

支持 `--cleanup-dry-run` 预演。

## D. 快照访问

- 看板挂载 `/snapshots` 静态目录（`dashboard/snapshots/`）
- RuoYi 首页/告警查看、8080 看板均支持 `/snapshots/<id>.jpg` 相对路径

## E. 验证

| 项 | 结果 |
|---|---|
| 归档器进程 | 运行中 |
| 已归档 | 779+ 条，757+ 张图片 |
| 样例 | id=5305：`snapshot=/snapshots/5305.jpg`，`snapshot_original` 保留 |
| `/snapshots/5305.jpg` | HTTP 200，image/jpeg |
| 清理预演 | alarms=0、kafka_messages=0、孤儿文件=10（保留期 30 天） |
| 前端编译 | dashboard/alarmview 均 200 |

## F. 说明

- 归档器会持续追平历史（约 2.9 万条，部分旧快照可能已过 Frigate 3 天保留期，重试 3 次后置空）
- 旧种子数据的 `localhost:9000` 快照无法下载，直接标记归档并置空

---

# 更新记录 · 2026-11-08（第十八轮：YOLO 上 GPU / TensorRT 镜像）

## A. 背景

实时画面卡：前端原为 1fps JPEG；改为 MJPEG 后仍受 CPU 检测限制。
实测 CPU 下 YOLO ONNX 占 943% CPU，10fps 时 skipped 6.8、源帧率仅 2—3fps。

## B. 改动

1. Frigate 镜像换为 **`ghcr.io/blakeblackshear/frigate:stable-tensorrt`**（amd64，含 CUDA/TensorRT）
2. ONNX 检测器 `device: CPU` → **`device: GPU`**（使用 ONNX Runtime `CUDAExecutionProvider`）
3. 保留 NVDEC：`ffmpeg.hwaccel_args: preset-nvidia-h264`
4. 检测分辨率 1280×720 → **960×540**，`detect.fps: 10`
5. 看板 MJPEG 出帧间隔 0.12s → 0.05s
6. Frigate compose 保留 GPU 预留（`capabilities: [gpu, video]`）

## C. 实测对比

| 指标 | CPU(YOLO) | GPU(CUDA) |
|---|---|---|
| 检测推理 | 35—37 ms | **9—10 ms** |
| detector 进程 CPU | 943% | 75% |
| Frigate 总 CPU | ~1088% | **~270%** |
| camera_fps | 10（skipped 6.8） | **10.1（skipped 0.3）** |
| 源帧率 | 2—3 fps | **9—10 fps** |
| 看板 MJPEG | ~5 fps | **~8 fps** |

GPU 占用：detector 约 392MiB，ffmpeg(NVDEC) 约 298MiB。

## D. 说明

- 当前用的是 **CUDA Execution Provider**（不是 TensorRT EP）；如需 TensorRT EP，可把 `device` 改为 `Tensorrt`，首次会构建 engine 并缓存到 `/config/model_cache/tensorrt/ort/trt-engines`
- 检测分辨率降到 960×540 是为了跑满 10fps；如更看重清晰度可改回 1280×720（约 6—7fps）
- 真正 25fps 需要改用原始视频流（MSE/WebRTC），但那样没有检测框

---

# 更新记录 · 2026-11-08（第十九轮：时空记忆 + 偏离候选 MVP）

## A. 新增数据表（`memory/schema.sql`）

- `tracks`：长期轨迹记忆（trace_id、时间、path、区域、小时、特征、质量分）
- `baselines`：按 区域×小时/全天/全局 的 median/MAD/scale
- `deviation_candidates`：偏离候选池（不是告警）
- `risk_clues`：线索池（Phase 2 预留）

## B. 新增服务（`memory/`）

| 服务 | 作用 | 状态 |
|---|---|---|
| `track_writer.py` | Frigate 事件 → tracks（常驻） | 运行中 |
| `baseline_builder.py` | 每 10 分钟重建正常基线 | 运行中 |
| `deviation_scorer.py` | 新轨迹打偏离分，写候选池 | 运行中 |

## C. 新增接口（dashboard 8080）

- `GET /api/tracks` 轨迹列表
- `GET /api/deviations` 偏离候选（含轨迹特征/路径）
- `GET /api/deviation_stats` 统计
- `PATCH /api/deviations/{id}` 标记 reviewed/ignored

## D. RuoYi 首页新增「偏离候选」Tab

- 显示：轨迹总数、基线组、候选数、待核查、最高分
- 表格：时间/摄像头/区域/偏离分/主要偏离/时长/状态/操作
- 支持"已核查/忽略"

## E. 验证

- `tracks` 已写入 469+ 条
- `baselines` 3 组（region×hour、region×全天、全局）
- `deviation_candidates` 43 条（阈值 8.0）
- PATCH 测试：id=256 → reviewed，pending 42 / reviewed 1
- RuoYi 页面编译 200

## F. 说明

- 偏离候选**不是告警**，进候选池由人工核查
- 阈值 `DEVIATION_THRESHOLD=8.0` 可调；数据越多基线越准
- 目前是 MVP：无 ReID、无线索挖掘、无长期媒体存储

---

# 更新记录 · 2026-11-08（第二十轮：偏离候选"问题描述"）

## A. 新增

- `deviation_candidates.description` 字段
- `memory/deviation_text.py`：把 reason(特征/z) 翻译成中文问题描述
- `deviation_scorer.py`：写入候选时生成描述
- `dashboard/app.py`：`/api/deviations` 返回 `description`，旧候选自动兜底生成
- RuoYi 偏离候选表格：列「主要偏离」改为「问题描述」

## B. 描述示例

> 与历史正常基线差异较大：路径长度比偏高（2.88，正常约 1.00）；路径效率偏低（0.32，正常约 0.99）；原地停留占比偏高（0.28，正常约 0.08）。轨迹比正常更绕，可能存在徘徊/绕行，建议核查。

## C. 验证

- 回填旧候选描述 77 条
- `/api/deviations` 返回 `description`
- scorer 已重启并持续写入描述
- Vue 编译 200

---

# 更新记录 · 2026-11-08（第二十一轮：偏离候选悬停放大 + 快照）

## A. 改动

- `/api/deviations` 新增 `snapshot` 字段：由 `trace_id` 推出 Frigate 事件快照
  `http://127.0.0.1:5000/api/events/<event_id>/snapshot.jpg`
- RuoYi 偏离候选表格：
  - 迷你轨迹曲线外包 `el-tooltip`，悬停显示 280×156 放大曲线
  - 新增「快照」列：88×50 缩略图，点击可放大预览
  - 快照加载失败自动显示 "-"

## B. 验证

- 快照本机 / 局域网访问均 HTTP 200
- `/api/deviations` 返回 snapshot
- Vue 编译 200
- dashboard 单进程运行

## C. 注意

- 快照来自 Frigate，默认保留 3 天；归档器之前已停止，过期后缩略图会显示 "-"
- 如需长期保留，可重新启动 `archive/run_archiver.sh`

---

# 更新记录 · 2026-11-08（第二十二轮：匿名 ReID + 线索挖掘）

## A. 匿名 ReID

- 模型：OSNet（`osnet-x0-25-msmt17`，512 维，GPU）
- 数据：`track_embeddings`（trace_id、camera、start_time、embedding）
- 关联：`reid_links`（a_trace、b_trace、similarity、gap_s、same_camera）
- 规则：同相机时间间隔 ≥60s、跨镜可短间隔；余弦相似度 ≥0.8；每新轨迹保留 top-3
- 服务：`memory/reid_embedder.py`（`.venv-fall`），已常驻
- **只做匿名外观关联，不做身份识别**

## B. 线索挖掘（`memory/clue_miner.py`）

四类线索写入 `risk_clues`：

| 类型 | 含义 | 当前数量 |
|---|---|---|
| deviation_cluster | 区域/时段偏离候选聚集 | 2 |
| odd_hour | 历史罕见时段活动 | 0（数据时长不足） |
| return | 同一匿名外观多次出现 | 3 |
| companion | 两名目标长期共同出现 | 0（暂无足够 cooccur） |

## C. 接口与页面

- `GET /api/clues`、`GET /api/clues/stats`、`PATCH /api/clues/{id}`
- RuoYi 首页新增「线索池」Tab：类型/分数/线索说明/状态/核查操作
- 线索说明示例：`demo 在 2:00 左右出现 48 条偏离候选，最高偏离分 18.73`

## D. 验证

- ReID：120 条嵌入、212 条关联（相似度最高 1.000，跨约 109s）
- 线索：5 条（2 偏离聚集 + 3 匿名回流）
- 服务进程：reid_embedder、clue_miner 运行中
- 启停脚本已加入 `memory/run_reid.sh`、`memory/run_clue.sh`
- Vue 编译 200

## E. 说明

- MVP 用 PostgreSQL JSON 存向量 + numpy 计算余弦；后续可换 Milvus
- `odd_hour` 需要更长历史数据；`companion` 需要更多 cooccur 告警
- 跨镜关联需要接入第二路摄像头

---

# 更新记录 · 2026-11-08（第二十三轮：时空记忆服务并入总启停）

## A. 统一入口

- `memory/run_writer.sh` / `run_baseline.sh` / `run_scorer.sh` / `run_reid.sh` / `run_clue.sh`
  均改为**绝对路径**启动（`DIR` + absolute python + absolute script）
- `scripts/start_monitor.sh` 新增 `start_memory()`，5 个记忆服务统一通过 `memory/run_*.sh` 启动
- `scripts/start_monitor.sh` 新增 `start_cmd()`，看板/RuoYi/归档器统一用 `bash -c && exec` + `disown`
- 所有后台启动加 `disown`，总脚本执行完即退出，不再挂住
- `scripts/stop_monitor.sh` 已包含 5 个记忆服务的停止规则
- `scripts/status.sh` 新增「时空记忆」段

## B. 验证

- `start_monitor.sh` 二次运行：全部显示「已在运行」，EXIT=0
- 5 个记忆服务进程正常
- 桥接 5 个、看板 8080、RuoYi 8081/9099、归档器均在
- 清理了历史遗留的父 shell 和重复 dashboard 进程
