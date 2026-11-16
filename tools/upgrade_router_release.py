#!/usr/bin/env python3
"""Update a staged router release and rebuild the candidate without switching runtime."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path, PurePosixPath

import paramiko

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VERSION = "0.2.0"
REMOTE_ROOT = PurePosixPath("/data/sbx")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def remote_hash(client: paramiko.SSHClient, path: PurePosixPath) -> str:
    _, stdout, stderr = client.exec_command(f"sha256sum '{path}'", timeout=60)
    output = stdout.read().decode().strip()
    error = stderr.read().decode().strip()
    if error:
        raise RuntimeError(error)
    return output.split()[0]


def upload(sftp: paramiko.SFTPClient, local: Path, remote: PurePosixPath, mode: int = 0o600) -> None:
    partial = remote.with_name(remote.name + ".part")
    sftp.put(str(local), str(partial))
    sftp.chmod(str(partial), mode)
    try:
        sftp.remove(str(remote))
    except FileNotFoundError:
        pass
    sftp.rename(str(partial), str(remote))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default=DEFAULT_VERSION)
    parser.add_argument("--pack", type=Path, default=ROOT / "artifacts/sbx-0.2.0.sbxpack")
    parser.add_argument("--cache", type=Path, default=ROOT / "state/subscriptions")
    parser.add_argument("--host", default=os.environ.get("ROUTER_HOST", ""))
    parser.add_argument("--password-env", default="ROUTER_PASSWORD")
    parser.add_argument("--caches-only", action="store_true")
    args = parser.parse_args()
    if not args.host:
        parser.error("--host or ROUTER_HOST is required")
    password = os.environ.get(args.password_env)
    if not password:
        parser.error(f"set {args.password_env}; never write credentials to disk")

    pack = args.pack.resolve()
    cache_files = sorted(args.cache.resolve().glob("*_cache.txt"))
    if not cache_files:
        parser.error("no subscription cache files")
    expected_cache = {path.name: sha256_file(path) for path in cache_files}

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(args.host, username="root", password=password, timeout=15, banner_timeout=15)
    try:
        sftp = client.open_sftp()
        _, stdout, _ = client.exec_command(
            "mkdir -p /data/sbx/inbox; "
            "if [ ! -e /data/sbx/snapshot ]; then "
            "  if [ -e /data/sbx/current/snapshot ]; then cp -a /data/sbx/current/snapshot /data/sbx/snapshot; "
            "  else mkdir -p /data/sbx/snapshot; fi; "
            "fi",
            timeout=120,
        )
        stdout.read()
        if not args.caches_only:
            if not pack.is_file():
                parser.error(f"pack not found: {pack}")
            expected_pack = sha256_file(pack)
            pack_remote = REMOTE_ROOT / "inbox" / pack.name
            upload(sftp, pack, pack_remote)
            if remote_hash(client, pack_remote) != expected_pack:
                raise SystemExit("remote source pack hash mismatch")

            script = '''
import hashlib
import json
import os
import shutil
import sys
import zipfile
from pathlib import Path

pack = Path(sys.argv[1])
root = Path(sys.argv[2])
version = sys.argv[3]
current = root / "current"
if not current.is_symlink():
    raise SystemExit("current is not a symlink")
old_current = current.resolve()
release = root / "releases" / version
release.mkdir(parents=True, exist_ok=False)
with zipfile.ZipFile(pack) as archive:
    manifest = json.loads(archive.read("manifest.json"))
    for entry in manifest["files"]:
        content = archive.read("files/" + entry["path"])
        if hashlib.sha256(content).hexdigest() != entry["sha256"]:
            raise SystemExit("pack hash mismatch: " + entry["path"])
        target = release / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
(release / "bin").mkdir(exist_ok=True)
shutil.copy2(old_current / "bin/sing-box-extended", release / "bin/sing-box-extended")
(release / "bin/sing-box-extended").chmod(0o755)
(release / "config/secrets").mkdir(parents=True, exist_ok=True)
shutil.copy2(old_current / "config/secrets/local.yaml", release / "config/secrets/local.yaml")
(release / "config/secrets/local.yaml").chmod(0o600)
for name in ("snapshot", "state", "build"):
    os.symlink("../../" + name, release / name)
next_link = root / "current.next"
if next_link.exists() or next_link.is_symlink():
    next_link.unlink()
os.symlink("releases/" + version, next_link)
os.replace(next_link, current)
print("staged release switched to", version)
'''
            stdin, stdout, stderr = client.exec_command(
                f"python3 - '{pack_remote}' '{REMOTE_ROOT}' '{args.version}'", timeout=240
            )
            stdin.write(script)
            stdin.channel.shutdown_write()
            print(stdout.read().decode().strip())
            error = stderr.read().decode().strip()
            if error:
                raise SystemExit(error)

        for cache_file in cache_files:
            remote = REMOTE_ROOT / "state/subscriptions" / cache_file.name
            upload(sftp, cache_file, remote)
            if remote_hash(client, remote) != expected_cache[cache_file.name]:
                raise SystemExit(f"cache hash mismatch: {cache_file.name}")
        print(f"uploaded {len(cache_files)} subscription caches")

        _, stdout, stderr = client.exec_command("/root/sbxctl build", timeout=900)
        print(stdout.read().decode().strip())
        error = stderr.read().decode().strip()
        if error:
            print(error)
        print("Staged candidate rebuilt and checked. The running service was not restarted.")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
