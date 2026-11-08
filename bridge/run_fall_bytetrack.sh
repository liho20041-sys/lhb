#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
exec .venv-fall/bin/python fall_bridge_bytetrack.py
