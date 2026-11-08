#!/usr/bin/env bash
# 共现检测：同相机内两条轨迹持续接近
set -e
cd "$(dirname "$0")"
exec .venv/bin/python cooccur_bridge.py "$@"
