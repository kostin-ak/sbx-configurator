#!/usr/bin/env python3
"""Build, verify and test a source-only .sbxpack release."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sbx.pack import create_pack, extract_pack, verify_pack


COPY_DIRECTORIES = ("sbx", "tools", "tests", "config", "protocols", "docs", "examples")
COPY_FILES = ("README.md", "pyproject.toml", "sbxctl", ".gitattributes", "LICENSE", "SECURITY.md")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="0.2.0")
    parser.add_argument("--sing-box-version", default="1.14.3-extended-2.7.3")
    args = parser.parse_args()

    staging = ROOT / "build/release-src"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    for name in COPY_DIRECTORIES:
        shutil.copytree(
            ROOT / name,
            staging / name,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", "local.yaml"),
        )
    for name in COPY_FILES:
        source = ROOT / name
        if source.is_file():
            shutil.copy2(source, staging / name)
    release_metadata = {
        "format": 1,
        "sing_box_version": args.sing_box_version,
        "router_arch": "linux-mipsle-softfloat",
        "target_root": "/data/sbx",
        "auto_restart": False,
        "contains_secrets": False,
    }
    (staging / "release.json").write_text(json.dumps(release_metadata, indent=2) + "\n", encoding="utf-8")

    output = ROOT / "artifacts" / f"sbx-{args.version}.sbxpack"
    create_pack(staging, output, args.version)
    manifest = verify_pack(output)
    check_dir = ROOT / "build/release-check"
    if check_dir.exists():
        shutil.rmtree(check_dir)
    extract_pack(output, check_dir)

    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(check_dir)
    subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", str(check_dir / "tests"), "-v"],
        env=environment,
        check=True,
    )
    binary = ROOT / "bin/sing-box-extended"
    subprocess.run(
        [str(binary), "check", "-c", str(check_dir / "config/protocol-check.json"), "-D", str(ROOT / "state/release-check")],
        check=True,
    )
    print(f"Release: {output}")
    print(f"Version: {manifest['version']}")
    print(f"Files: {len(manifest['files'])}")
    print("Pack verification, isolated tests and protocol schema checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
