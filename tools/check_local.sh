#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/.venv-wsl/bin/python"
if [ ! -x "$PY" ]; then
    PY="${PYTHON:-python3}"
fi
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

"$PY" -m unittest discover -s "$ROOT/tests" -v

BINARY="$ROOT/bin/sing-box-extended"
SNAPSHOT="$ROOT/snapshot/etc/sing-box/config.parts"
SECRETS="$ROOT/config/secrets/local.yaml"

if [ ! -x "$BINARY" ]; then
    echo "Skipping pipeline build: put the fork binary into bin/sing-box-extended" >&2
elif [ ! -d "$SNAPSHOT" ]; then
    echo "Skipping pipeline build: copy examples/snapshot to snapshot/" >&2
elif [ ! -f "$SECRETS" ]; then
    echo "Skipping pipeline build: copy examples/local.example.yaml to config/secrets/local.yaml" >&2
else
    "$PY" -m sbx.cli --root "$ROOT" build --check
    echo "Pipeline build and sing-box checks passed."
fi