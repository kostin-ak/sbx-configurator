#!/usr/bin/env python3
"""Fetch and verify a pinned sing-box-extended release without installing it."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import tarfile
import tempfile
import urllib.request
from pathlib import Path


DEFAULT_VERSION = "1.14.3-extended-2.7.3"
API_ROOT = "https://api.github.com/repos/shtorm-7/sing-box-extended/releases/tags/v"


def download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "router-vpn-sbx/0.1"})
    with urllib.request.urlopen(request, timeout=90) as response:
        return response.read()


def safe_extract(archive: Path, destination: Path) -> None:
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            target = (destination / member.name).resolve()
            if destination.resolve() not in target.parents and target != destination.resolve():
                raise ValueError(f"unsafe archive member: {member.name}")
        tar.extractall(destination)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default=DEFAULT_VERSION)
    parser.add_argument("--arch", default="linux-amd64", help="for example linux-amd64 or linux-mipsle-softfloat")
    parser.add_argument("--sha256", help="override the digest instead of using GitHub API metadata")
    parser.add_argument("--dest", type=Path, default=Path(__file__).resolve().parents[1] / "bin")
    parser.add_argument("--keep-archive", action="store_true")
    args = parser.parse_args()

    release = json.loads(download(API_ROOT + args.version))
    asset_name = f"sing-box-{args.version}-{args.arch}.tar.gz"
    asset = next((item for item in release["assets"] if item["name"] == asset_name), None)
    if asset is None:
        parser.error(f"release asset not found: {asset_name}")
    expected = args.sha256 or asset.get("digest", "").removeprefix("sha256:")
    if not expected:
        parser.error("no SHA-256 supplied and GitHub API returned no digest")

    args.dest.mkdir(parents=True, exist_ok=True)
    archive = args.dest / asset_name
    archive.write_bytes(download(asset["browser_download_url"]))
    actual = hashlib.sha256(archive.read_bytes()).hexdigest()
    if actual.lower() != expected.lower():
        archive.unlink()
        raise SystemExit(f"SHA-256 mismatch: expected {expected}, got {actual}")

    with tempfile.TemporaryDirectory(prefix="sbx-extract-", dir=args.dest) as temporary:
        extracted = Path(temporary)
        safe_extract(archive, extracted)
        candidates = [path for path in extracted.rglob("sing-box") if path.is_file()]
        if len(candidates) != 1:
            raise SystemExit("expected exactly one sing-box binary in the archive")
        versioned_binary = args.dest / f"sing-box-{args.version}"
        shutil.copy2(candidates[0], versioned_binary)
        versioned_binary.chmod(versioned_binary.stat().st_mode | stat.S_IXUSR)
        active_binary = args.dest / "sing-box-extended"
        if active_binary.exists() or active_binary.is_symlink():
            active_binary.unlink()
        try:
            active_binary.symlink_to(versioned_binary.name)
        except (OSError, NotImplementedError):
            shutil.copy2(versioned_binary, active_binary)
            active_binary.chmod(active_binary.stat().st_mode | stat.S_IXUSR)

    metadata = {
        "version": args.version,
        "arch": args.arch,
        "asset": asset_name,
        "url": asset["browser_download_url"],
        "sha256": actual,
        "binary": str(active_binary),
    }
    (args.dest / f"{args.arch}.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    if not args.keep_archive:
        archive.unlink()
    print(f"Verified and unpacked {active_binary}")
    print(f"SHA-256: {actual}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
