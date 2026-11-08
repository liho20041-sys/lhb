#!/usr/bin/env bash
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$DIR/../bridge/.venv/bin/python" "$DIR/track_writer.py" "$@"
