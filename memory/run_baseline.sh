#!/usr/bin/env bash
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$DIR/../bridge/.venv/bin/python" "$DIR/baseline_builder.py" "$@"
