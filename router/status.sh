#!/bin/sh
set -eu

ROOT="${SBX_ROOT:-/data/sbx}"
echo "legacy binary: $(/usr/bin/sing-box version 2>/dev/null | head -1)"
echo "legacy process: $(pidof sing-box 2>/dev/null || echo not-running)"
if [ -L "$ROOT/current" ]; then
  echo "staged current: $(readlink "$ROOT/current")"
else
  echo "staged current: absent"
fi
if [ -x "$ROOT/current/bin/sing-box-extended" ]; then
  "$ROOT/current/bin/sing-box-extended" version
fi
df -h /data
