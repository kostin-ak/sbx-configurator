#!/usr/bin/env python3
"""Upload a locally built config.json and install it on the router.

Builds are intentionally not performed on the router: a full build is CPU and
memory heavy for a small MIPS device. Build here, then push the artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[1]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, default=ROOT / "build/artifacts/config.json")
    parser.add_argument("--host", default=os.environ.get("ROUTER_HOST", ""))
    parser.add_argument("--password-env", default="ROUTER_PASSWORD")
    parser.add_argument("--remote", default="/data/sbx/inbox/config.json")
    parser.add_argument("--restart", action="store_true", help="activate immediately")
    args = parser.parse_args()

    if not args.host:
        parser.error("--host or ROUTER_HOST is required")
    if not args.artifact.is_file():
        parser.error(f"artifact is absent: {args.artifact}")
    password = os.environ.get(args.password_env)
    if not password:
        parser.error(f"set {args.password_env}; never write credentials to disk")

    local_hash = sha256_file(args.artifact)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(args.host, username="root", password=password, timeout=15, banner_timeout=15)
    try:
        sftp = client.open_sftp()
        partial = args.remote + ".part"
        sftp.put(str(args.artifact), partial)
        sftp.chmod(partial, 0o600)
        try:
            sftp.remove(args.remote)
        except FileNotFoundError:
            pass
        sftp.rename(partial, args.remote)

        _, stdout, _ = client.exec_command(f"sha256sum '{args.remote}'", timeout=60)
        remote_hash = stdout.read().decode().split()[0]
        if remote_hash != local_hash:
            print(f"hash mismatch: local {local_hash}, remote {remote_hash}", file=sys.stderr)
            return 1

        command = f"/root/sbxctl deploy-artifact '{args.remote}'"
        if args.restart:
            command += " --restart"
        _, stdout, stderr = client.exec_command(command, timeout=300)
        output = stdout.read().decode()
        error = stderr.read().decode()
        if output:
            print(output, end="")
        if error:
            print(error, end="", file=sys.stderr)
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())