#!/usr/bin/env bash
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$DIR/../bridge/.venv-fall/bin/python" "$DIR/reid_embedder.py" "$@"
