#!/usr/bin/env python3
"""Print generated selector tags without printing node secrets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default="build/generated", type=Path)
    args = parser.parse_args()
    for path in sorted(args.root.glob("20-*/02-selectors.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        tags = [item.get("tag") for item in value.get("outbounds", []) if isinstance(item, dict)]
        print(f"{path}: {tags}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
