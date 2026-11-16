#!/usr/bin/env python3
"""Verify that a source release contains no local secrets or caches."""

from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path


FORBIDDEN_PARTS = {"local.yaml", "local.yml"}
FORBIDDEN_PREFIXES = ("state/", "snapshot/", "bin/", "build/")
SUSPICIOUS_NAMES = ("cache.txt", ".env", "id_rsa")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pack", type=Path)
    args = parser.parse_args()
    with zipfile.ZipFile(args.pack) as archive:
        names = archive.namelist()
        for name in names:
            if any(part in FORBIDDEN_PARTS for part in Path(name).parts):
                raise SystemExit(f"forbidden local configuration in pack: {name}")
            if name.startswith(FORBIDDEN_PREFIXES):
                raise SystemExit(f"forbidden runtime path in pack: {name}")
            if any(candidate in Path(name).name for candidate in SUSPICIOUS_NAMES):
                raise SystemExit(f"suspicious file name in pack: {name}")
        metadata = json.loads(archive.read("files/release.json"))
    if metadata.get("contains_secrets") is not False:
        raise SystemExit("release metadata does not declare contains_secrets=false")
    print(f"Audited {len(names)} pack entries: no local secrets, caches or binaries included.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
