#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$ROOT/.venv-wsl/bin/python"
if [ ! -x "$PY" ]; then
    PY="${PYTHON:-python3}"
fi

cd "$ROOT"
exec "$PY" -m sbx.tui "$@"