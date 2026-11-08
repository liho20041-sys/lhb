#!/usr/bin/env bash
# Frigate -> Kafka -> PostgreSQL 告警桥接启动脚本
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -i https://pypi.tuna.tsinghua.edu.cn/simple kafka-python psycopg2-binary
fi

exec .venv/bin/python frigate_alarm_bridge.py
