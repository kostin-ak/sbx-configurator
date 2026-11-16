#!/bin/sh
# Create router backups before staging/switch testing.
# Does not stop or modify the running sing-box service.

set -eu

BACKUP_DIR="${BACKUP_DIR:-/data/backup}"
STAMP="$(date +%Y%m%d-%H%M%S)"
SYS_FILE="$BACKUP_DIR/openwrt-sysupgrade-$STAMP.tar.gz"
CFG_FILE="$BACKUP_DIR/sing-box-config-$STAMP.tar.gz"
PKG_FILE="$BACKUP_DIR/opkg-installed-$STAMP.txt"
MANIFEST="$BACKUP_DIR/backup-manifest-$STAMP.txt"

mkdir -p "$BACKUP_DIR"

if [ "${SKIP_SYSUPGRADE:-0}" = "1" ]; then
  SYS_FILE="$(find "$BACKUP_DIR" -maxdepth 1 -name 'openwrt-sysupgrade-*.tar.gz' 2>/dev/null | sort | tail -1 || true)"
  if [ -n "$SYS_FILE" ]; then
    echo "using existing OpenWrt sysupgrade backup: $SYS_FILE"
  else
    echo "skipping new sysupgrade backup; no existing backup found"
  fi
elif command -v sysupgrade >/dev/null 2>&1; then
  echo "creating OpenWrt sysupgrade backup: $SYS_FILE"
  sysupgrade -b "$SYS_FILE"
else
  echo "sysupgrade is not available; skipping OpenWrt backup" >&2
  SYS_FILE=""
fi

FILES=""
for path in \
  /etc/sing-box \
  /etc/config/sing-box \
  /etc/init.d/sing-box \
  /etc/openwrt_release \
  /etc/os-release \
  /etc/crontabs \
  /etc/firewall.user \
  /data/sing-box \
  /usr/share/sing-box/cache.db; do
  if [ -e "$path" ]; then
    FILES="$FILES $path"
  fi
done

if [ -n "$FILES" ]; then
  echo "creating targeted config backup: $CFG_FILE"
  EXCLUDE_FILE="$BACKUP_DIR/.tar-exclude-$STAMP"
  printf '%s\n' '*.log' '*.err' '*.old' >"$EXCLUDE_FILE"
  # BusyBox tar uses -X FILE instead of GNU tar --exclude.
  # shellcheck disable=SC2086
  tar -czf "$CFG_FILE" -X "$EXCLUDE_FILE" $FILES
  rm -f "$EXCLUDE_FILE"
  tar -tzf "$CFG_FILE" >/dev/null
else
  echo "no targeted backup paths exist" >&2
  CFG_FILE=""
fi

if command -v opkg >/dev/null 2>&1; then
  opkg list-installed >"$PKG_FILE"
else
  PKG_FILE=""
fi

{
  echo "created_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "hostname=$(uname -n 2>/dev/null || echo unknown)"
  echo "kernel=$(uname -a)"
  echo "legacy_pid=$(pidof sing-box 2>/dev/null || echo none)"
  for path in \
    /etc/sing-box/config.json \
    /etc/config/sing-box \
    /etc/init.d/sing-box \
    /usr/share/sing-box/cache.db; do
    if [ -f "$path" ]; then
      echo "$(sha256sum "$path")"
    fi
  done
  [ -n "$SYS_FILE" ] && [ -f "$SYS_FILE" ] && echo "$(sha256sum "$SYS_FILE")"
  [ -n "$CFG_FILE" ] && [ -f "$CFG_FILE" ] && echo "$(sha256sum "$CFG_FILE")"
  [ -n "$PKG_FILE" ] && [ -f "$PKG_FILE" ] && echo "$(sha256sum "$PKG_FILE")"
} >"$MANIFEST"

echo
echo "Backup complete:"
[ -f "$SYS_FILE" ] && echo "  OpenWrt backup:   $SYS_FILE"
[ -f "$CFG_FILE" ] && echo "  Targeted config:  $CFG_FILE"
[ -f "$PKG_FILE" ] && echo "  Installed packages: $PKG_FILE"
echo "  Manifest:         $MANIFEST"
