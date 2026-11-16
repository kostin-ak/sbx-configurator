#!/bin/sh
set -eu

ROOT="${SBX_ROOT:-/data/sbx}"
CURRENT="$ROOT/current"
BIN="$CURRENT/bin/sing-box-extended"
RUNTIME_LOG="$ROOT/state/proxy-only-runtime.log"
export PYTHONPATH="$CURRENT"

PID=""
SERVER_PID=""
cleanup() {
  [ -z "$PID" ] || kill "$PID" 2>/dev/null || true
  [ -z "$PID" ] || wait "$PID" 2>/dev/null || true
  [ -z "$SERVER_PID" ] || kill "$SERVER_PID" 2>/dev/null || true
  [ -z "$SERVER_PID" ] || wait "$SERVER_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

python3 -m sbx.cli --root "$CURRENT" proxy-only \
  --config "$CURRENT/build/artifacts/config.json" \
  --output "$CURRENT/build/proxy-only/config.json" \
  --listen 127.0.0.1 --port 7891 --clash-port 9091 \
  --offline-rule-sets \
  --compiler "$BIN" \
  --stub-dir "$ROOT/state/rule-set-stubs"

"$BIN" check -c "$CURRENT/build/proxy-only/config.json" -D "$ROOT/state/proxy-only"
printf '{"status":"offline-loopback-health"}\n' > "$CURRENT/build/proxy-only/api-version.json"
python3 -m http.server 18080 --bind 127.0.0.1 --directory "$CURRENT/build/proxy-only" &
SERVER_PID=$!
"$BIN" run -c "$CURRENT/build/proxy-only/config.json" -D "$ROOT/state/proxy-only" >"$RUNTIME_LOG" 2>&1 &
PID=$!

python3 - <<'PY'
import http.client
import time

for _ in range(30):
    try:
        # An absolute URI forces the request through the mixed proxy inbound.
        connection = http.client.HTTPConnection("127.0.0.1", 7891, timeout=2)
        connection.request("GET", "http://127.0.0.1:18080/api-version.json")
        response = connection.getresponse()
        body = response.read().decode("utf-8", "replace")
        status = response.status
        connection.close()
        if status == 200:
            print(body.strip())
            break
    except Exception:
        pass
    time.sleep(1)
else:
    raise SystemExit("ERROR: proxy-only smoke test did not become ready")
PY

echo "router proxy-only smoke test: OK"
echo "test processes will now stop; legacy service was not touched"
