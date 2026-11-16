#!/usr/bin/env python3
"""Download a read-only router snapshot into the ignored snapshot/ directory.

The router password is read from ROUTER_PASSWORD and is never written to disk.
No remote command installs, removes, restarts or writes anything.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import paramiko


REMOTE_ROOT = PurePosixPath("/etc/sing-box")
REMOTE_DIRECTORIES = ("scripts", "config.parts", "configs", "rules")
REMOTE_FILES = ("config.json", "update.sh")
REMOTE_EXTRA_FILES = ("/etc/config/sing-box", "/etc/init.d/sing-box", "/etc/openwrt_release")
SKIP_SUFFIXES = (".log", ".err", ".old", "-opkg")


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def should_skip(name: str, include_cache: bool, relative: PurePosixPath) -> bool:
    if name.endswith(SKIP_SUFFIXES):
        return True
    if not include_cache and relative.parts[:2] == ("configs", "cache"):
        return True
    return False


def collect_files(sftp, remote: PurePosixPath, include_cache: bool, relative=PurePosixPath("")) -> list[PurePosixPath]:
    result: list[PurePosixPath] = []
    for entry in sftp.listdir_attr(str(remote)):
        name = entry.filename
        child = remote / name
        child_relative = relative / name
        if stat.S_ISDIR(entry.st_mode):
            if child_relative.parts[:2] != ("configs", "cache") or include_cache:
                result.extend(collect_files(sftp, child, include_cache, child_relative))
        elif stat.S_ISREG(entry.st_mode) and not should_skip(name, include_cache, child_relative):
            result.append(child)
    return result


def run_read_only(client, command: str) -> str:
    _, stdout, stderr = client.exec_command(command, timeout=20)
    output = stdout.read().decode("utf-8", "replace").strip()
    error = stderr.read().decode("utf-8", "replace").strip()
    return output if not error else f"{output}\n{error}".strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("ROUTER_HOST", ""))
    parser.add_argument("--user", default=os.environ.get("ROUTER_USER", "root"))
    parser.add_argument("--password-env", default="ROUTER_PASSWORD")
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1] / "snapshot")
    parser.add_argument("--exclude-cache", action="store_true")
    args = parser.parse_args()
    if not args.host:
        parser.error("--host or ROUTER_HOST is required")

    password = os.environ.get(args.password_env)
    if not password:
        parser.error(f"set {args.password_env} in the environment; do not put it in the repository")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(args.host, username=args.user, password=password, timeout=15, banner_timeout=15)
    records = []
    try:
        sftp = client.open_sftp()
        remote_files = [REMOTE_ROOT / name for name in REMOTE_FILES]
        for directory in REMOTE_DIRECTORIES:
            remote_files.extend(collect_files(sftp, REMOTE_ROOT / directory, not args.exclude_cache))
        remote_files.extend(PurePosixPath(path) for path in REMOTE_EXTRA_FILES)

        args.out.mkdir(parents=True, exist_ok=True)
        for remote in sorted(set(remote_files), key=str):
            content = sftp.open(str(remote), "rb").read()
            local_relative = Path(*remote.parts[1:])
            local = args.out / local_relative
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_bytes(content)
            records.append({
                "path": str(local_relative).replace("\\", "/"),
                "remote": str(remote),
                "size": len(content),
                "sha256": sha256_bytes(content),
            })

        environment = {
            "uname": run_read_only(client, "uname -a"),
            "sing_box_version": run_read_only(client, "/usr/bin/sing-box version"),
            "package": run_read_only(client, "opkg status sing-box"),
        }
        (args.out / "environment.json").write_text(
            json.dumps(environment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    finally:
        client.close()

    manifest = {
        "format": 1,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "host": args.host,
        "read_only": True,
        "includes_subscription_cache": not args.exclude_cache,
        "files": records,
    }
    (args.out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Captured {len(records)} files into {args.out}")
    print("Snapshot is ignored by Git and may contain credentials; do not publish it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
