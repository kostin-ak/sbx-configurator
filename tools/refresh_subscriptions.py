#!/usr/bin/env python3
"""Refresh local subscription caches from v2 URLs without writing router state."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml

from sbx.artifact import atomic_write_bytes
from sbx.links import decode_base64_payload, parse_link
from sbx.loader import load_config

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-root", type=Path, default=ROOT / "config")
    parser.add_argument("--secrets", type=Path, default=ROOT / "config/secrets/local.yaml")
    parser.add_argument("--cache-dir", type=Path, default=ROOT / "state/subscriptions")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="return success when at least one subscription refreshed (failed ones keep old caches)",
    )
    args = parser.parse_args()

    loaded = load_config(args.config_root, args.secrets)
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for subscription in loaded.subscriptions["subscriptions"]:
        url = subscription.get("url")
        if not url:
            continue
        try:
            response = requests.get(url, timeout=args.timeout, headers={"User-Agent": "router-vpn-sbx/0.1"})
            response.raise_for_status()
        except Exception as error:
            records.append({"name": subscription["name"], "error": str(error)})
            print(f"{subscription['name']}: ERROR {error}")
            continue
        content = response.text.strip()
        try:
            if not content:
                raise RuntimeError(f"empty subscription response: {subscription['name']}")
            if "HWID" in content or "Включите отправку" in content:
                raise RuntimeError(f"subscription requires HWID; keeping previous cache: {subscription['name']}")
            decoded = decode_base64_payload(content)
            parsed = [parse_link(line) for line in decoded.splitlines() if line.strip()]
            parsed = [node for node in parsed if node]
            if not parsed:
                raise RuntimeError(f"no supported nodes in subscription {subscription['name']}")
            if all(node.get("server") in {"0.0.0.0", "127.0.0.1", "::1"} for node in parsed):
                raise RuntimeError(f"subscription returned placeholder nodes: {subscription['name']}")
        except Exception as error:
            records.append({"name": subscription["name"], "error": str(error)})
            print(f"{subscription['name']}: ERROR {error}")
            continue
        cache = args.cache_dir / f"{subscription['name']}_cache.txt"
        atomic_write_bytes(cache, (content + "\n").encode("utf-8"))
        records.append({
            "name": subscription["name"],
            "bytes": len(content.encode("utf-8")),
            "lines": len(content.splitlines()),
            "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        })
    manifest = {
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
        "subscriptions": records,
    }
    atomic_write_bytes(args.cache_dir / "refresh-manifest.json", (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print(f"Refreshed {len(records)} subscription caches into {args.cache_dir}")
    for record in records:
        if "error" in record:
            print(f"{record['name']}: failed, kept previous cache")
        else:
            print(f"{record['name']}: {record['lines']} lines, {record['bytes']} bytes, sha256={record['sha256'][:16]}...")
    failures = sum(1 for record in records if "error" in record)
    if failures:
        if args.allow_partial and failures < len(records):
            print(f"{failures} subscription(s) failed, their previous caches were kept")
            return 0
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
