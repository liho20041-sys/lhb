#!/usr/bin/env bash
# 人群聚集检测：区域内同时在场的 person 数量 + 持续时间
set -e
cd "$(dirname "$0")"
exec .venv/bin/python crowd_bridge.py "$@"
