#!/usr/bin/env python3
"""Download router backups into an ignored local directory and verify hashes."""

from __future__ import annotations

import argparse
import hashlib
import os
import stat
from pathlib import Path, PurePosixPath

import paramiko

ROOT = Path(__file__).resolve().parents[1]
REMOTE_DIR = PurePosixPath("/data/backup")
DEFAULT_STAMP = "20261115-014131"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("ROUTER_HOST", ""))
    parser.add_argument("--user", default=os.environ.get("ROUTER_USER", "root"))
    parser.add_argument("--password-env", default="ROUTER_PASSWORD")
    parser.add_argument("--remote-dir", default=str(REMOTE_DIR))
    parser.add_argument("--stamp", default=DEFAULT_STAMP)
    parser.add_argument("--out", type=Path, default=ROOT / "backups" / f"router-{DEFAULT_STAMP}")
    args = parser.parse_args()
    if not args.host:
        parser.error("--host or ROUTER_HOST is required")

    password = os.environ.get(args.password_env)
    if not password:
        parser.error(f"set {args.password_env}; never write credentials to disk")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(args.host, username=args.user, password=password, timeout=15, banner_timeout=15)
    try:
        sftp = client.open_sftp()
        remote_root = PurePosixPath(args.remote_dir)
        entries = sftp.listdir_attr(str(remote_root))
        files = [entry.filename for entry in entries if stat.S_ISREG(entry.st_mode)]
        manifest_name = f"backup-manifest-{args.stamp}.txt"
        if manifest_name not in files:
            raise SystemExit(f"manifest not found remotely: {manifest_name}")
        files = [name for name in files if name == manifest_name or name.endswith(f"-{args.stamp}.txt") or args.stamp in name or name.startswith("openwrt-sysupgrade-20261115-")]
        if not files:
            raise SystemExit("no matching backup files found")

        args.out.mkdir(parents=True, exist_ok=False)
        manifest_remote = remote_dir = remote_root / manifest_name
        manifest_text = sftp.open(str(manifest_remote), "rb").read().decode("utf-8", "replace")
        expected: dict[str, str] = {}
        for line in manifest_text.splitlines():
            if not line:
                continue
            digest, _, remote_path = line.partition("  ")
            if remote_path.startswith(str(remote_root)):
                expected[PurePosixPath(remote_path).name] = digest

        downloaded = []
        for name in sorted(files):
            remote = remote_root / name
            local = args.out / name
            partial = local.with_name(local.name + ".part")
            sftp.get(str(remote), str(partial))
            actual = sha256_file(partial)
            expected_hash = expected.get(name)
            if expected_hash and actual != expected_hash:
                partial.unlink()
                raise SystemExit(f"checksum mismatch for {name}")
            partial.rename(local)
            downloaded.append((name, local.stat().st_size, actual, bool(expected_hash)))

        print(f"Downloaded {len(downloaded)} files to {args.out}")
        for name, size, digest, verified in downloaded:
            status = "manifest-verified" if verified else "hash-recorded"
            print(f"{status}: {name} ({size} bytes) sha256={digest}")
        print("No router files were modified.")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
