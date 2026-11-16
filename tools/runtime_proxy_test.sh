#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/.venv-wsl/bin/python"
export PYTHONPATH="$ROOT"

"$PY" -m sbx.cli --root "$ROOT" proxy-only \
  --config "$ROOT/build/artifacts/config.json" \
  --output "$ROOT/build/proxy-only/config.json" \
  --listen 127.0.0.1 --port 7891 --clash-port 9091 \
  --offline-rule-sets

"$ROOT/bin/sing-box-extended" check \
  -c "$ROOT/build/proxy-only/config.json" \
  -D "$ROOT/state/proxy-only"

PID=""
SERVER_PID=""
cleanup() {
  if [[ -n "$PID" ]] && kill -0 "$PID" 2>/dev/null; then
    kill "$PID" 2>/dev/null || true
    wait "$PID" 2>/dev/null || true
  fi
  if [[ -n "$SERVER_PID" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

"$PY" -m http.server 18080 --bind 127.0.0.1 --directory "$ROOT/build/proxy-only" &
SERVER_PID=$!

"$ROOT/bin/sing-box-extended" run \
  -c "$ROOT/build/proxy-only/config.json" \
  -D "$ROOT/state/proxy-only" &
PID=$!

ready=0
for _ in $(seq 1 30); do
  if curl -fsS --max-time 2 -H 'Authorization: Bearer 12345678' \
      http://127.0.0.1:9091/version >"$ROOT/build/proxy-only/api-version.json" 2>/dev/null; then
    ready=1
    break
  fi
  if ! kill -0 "$PID" 2>/dev/null; then
    echo "sing-box exited before becoming ready" >&2
    exit 1
  fi
  sleep 1
done
[[ "$ready" -eq 1 ]] || { echo "Clash API did not become ready" >&2; exit 1; }

code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 30 \
  -x http://127.0.0.1:7891 http://127.0.0.1:18080/api-version.json)"
[[ "$code" == "200" ]] || { echo "proxy smoke test failed: HTTP $code" >&2; exit 1; }

cat "$ROOT/build/proxy-only/api-version.json"
echo
echo "Isolated offline proxy smoke test passed: HTTP 200. Test processes will be stopped."
