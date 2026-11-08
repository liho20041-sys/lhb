#!/usr/bin/env bash
# 行为分析桥接：Frigate -> 徘徊/异常逗留规则 -> kafka_messages -> alarm_records
set -e
cd "$(dirname "$0")"
exec .venv/bin/python behavior_bridge.py "$@"
