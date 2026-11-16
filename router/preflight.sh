#!/bin/sh
set -eu

TARGET="${1:-/data/sbx}"
PYTHON="${PYTHON:-python3}"

echo "== router preflight =="
machine="$(uname -m)"
case "$machine" in
  mips*|mipsel*) echo "architecture: $machine" ;;
  *) 
    if [ "${ALLOW_NON_MIPS:-0}" = "1" ]; then
      echo "architecture: $machine (allowed for local staging test)"
    else
      echo "ERROR: expected MIPS router, got $machine" >&2
      exit 1
    fi
    ;;
esac

"$PYTHON" - <<'PY'
import importlib.util
import sys

missing = [name for name in ("yaml", "requests") if importlib.util.find_spec(name) is None]
if missing:
    raise SystemExit("ERROR: missing Python modules: " + ", ".join(missing))
print("python:", sys.version.split()[0], "modules: yaml, requests")
PY

available_kb="$(df -Pk "${DATA_MOUNT:-/data}" | awk 'NR==2 {print $4}')"
[ "$available_kb" -ge 300000 ] || {
  echo "ERROR: ${DATA_MOUNT:-/data} has less than 300 MB free" >&2
  exit 1
}
echo "data free: ${available_kb} KiB"

[ -w "${DATA_MOUNT:-/data}" ] || { echo "ERROR: ${DATA_MOUNT:-/data} is not writable" >&2; exit 1; }
if [ "${ALLOW_NON_MIPS:-0}" = "1" ]; then
  echo "legacy service checks: skipped for local staging test"
else
  [ -x /usr/bin/sing-box ] || { echo "ERROR: old sing-box binary is absent" >&2; exit 1; }
  [ -f /etc/sing-box/config.json ] || { echo "ERROR: old configuration is absent" >&2; exit 1; }
  echo "legacy service files: present"
fi

if [ -e "$TARGET" ]; then
  echo "staging target already exists: $TARGET"
else
  echo "staging target is absent: $TARGET"
fi

"$PYTHON" - <<'PY'
import socket

for port in (7891, 9091):
    sock = socket.socket()
    try:
        sock.bind(("127.0.0.1", port))
    except OSError as error:
        raise SystemExit(f"ERROR: test port {port} is unavailable: {error}")
    finally:
        sock.close()
print("test ports 7891/9091: free")
PY

echo "preflight: OK"
