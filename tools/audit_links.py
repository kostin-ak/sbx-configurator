#!/usr/bin/env python3
"""Audit raw subscription links against the new and legacy parsers."""

from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import urllib.parse
from pathlib import Path
from typing import Any

from sbx.links import decode_base64_payload, parse_link


ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "snapshot/etc/sing-box/configs/cache"
LEGACY_PATH = ROOT / "snapshot/etc/sing-box/scripts/sub2singbox.py"
IGNORED_DIFF_FIELDS = {"uuid", "password"}
SCREENSHOT_TAGS = {
    "ALL VPN Turbo Швейцария",
    "Soda VPN | Финляндия",
    "Дарвин ВПН | Франция",
    "Onion VPN | Финляндия",
    "ShadowNET VPN | Швейцария",
    "VPN RAKETA | Финляндия",
    "Trust VPN | Франция",
    "Батя VPN | Швейцария",
    "Dino VPN | Великобритания",
    "Дарвин ВПН | Италия",
    "FastCom VPN | Финляндия",
    "Soda VPN | Польша",
    "Velvet VPN | Финляндия",
    "HIT VPN | Израиль",
    "Trust VPN | Швейцария",
    "KotVPN | Великобритания",
    "Zefir VPN | Финляндия",
    "Velvet VPN | Польша",
}


def load_legacy_parser():
    spec = importlib.util.spec_from_file_location("legacy_sub2singbox", LEGACY_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load legacy parser: {LEGACY_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def mask(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: mask(item) for key, item in value.items()}
    if key := None:
        return value
    return value


def sanitized(node: dict[str, Any]) -> dict[str, Any]:
    result = {}
    for key, value in node.items():
        if key in IGNORED_DIFF_FIELDS:
            result[key] = "***"
        elif isinstance(value, dict):
            result[key] = sanitized(value)
        else:
            result[key] = value
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=CACHE_DIR)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    legacy = load_legacy_parser()

    links: list[tuple[str, str]] = []
    for path in sorted(args.cache_dir.glob("*_cache.txt")):
        subscription = path.name.removesuffix("_cache.txt")
        for line in decode_base64_payload(path.read_text(encoding="utf-8")).splitlines():
            if line.strip():
                links.append((subscription, line.strip()))

    schemes = collections.Counter()
    new_errors = collections.Counter()
    old_errors = collections.Counter()
    raw_params = {
        "security": collections.Counter(),
        "transport": collections.Counter(),
        "flow": collections.Counter(),
        "sni_missing": collections.Counter(),
        "allow_insecure": collections.Counter(),
        "fingerprint": collections.Counter(),
        "alpn": collections.Counter(),
    }
    parsed_new = parsed_old = parsed_both = identical = 0
    field_diffs = collections.Counter()
    diff_examples: list[dict[str, Any]] = []
    screenshot_rows: list[dict[str, Any]] = []

    for subscription, raw in links:
        parsed = urllib.parse.urlsplit(raw)
        scheme = parsed.scheme
        schemes[scheme] += 1
        query = urllib.parse.parse_qs(parsed.query)
        if scheme in {"vless", "trojan"}:
            raw_params["security"][query.get("security", ["<empty>"])[0]] += 1
            raw_params["transport"][query.get("type", ["tcp"])[0]] += 1
            raw_params["sni_missing"][not bool(query.get("sni", [""])[0])] += 1
            raw_params["allow_insecure"][query.get("allowInsecure", ["0"])[0]] += 1
            raw_params["fingerprint"][query.get("fp", ["<empty>"])[0]] += 1
            raw_params["alpn"][query.get("alpn", ["<empty>"])[0]] += 1
            if scheme == "vless":
                raw_params["flow"][query.get("flow", ["<empty>"])[0]] += 1

        tag = urllib.parse.unquote(parsed.fragment)
        if any(candidate in tag for candidate in SCREENSHOT_TAGS):
            row: dict[str, Any] = {"subscription": subscription, "tag": tag, "raw_security": query.get("security", [""])[0], "raw_transport": query.get("type", ["tcp"])[0]}
        else:
            row = {}

        try:
            new = parse_link(raw)
            if new is None:
                new_errors[f"unsupported:{scheme}"] += 1
        except Exception as error:
            new = None
            new_errors[type(error).__name__] += 1
        try:
            old = legacy.parse_uri(raw)
            if old is None:
                old_errors[f"unsupported:{scheme}"] += 1
        except Exception as error:
            old = None
            old_errors[type(error).__name__] += 1

        if new:
            parsed_new += 1
        if old:
            parsed_old += 1
        if new and old:
            parsed_both += 1
            compare_new = {key: value for key, value in new.items() if key not in IGNORED_DIFF_FIELDS}
            compare_old = {key: value for key, value in old.items() if key not in IGNORED_DIFF_FIELDS}
            if compare_new == compare_old:
                identical += 1
            else:
                for key in sorted(set(compare_new) | set(compare_old)):
                    if compare_new.get(key) != compare_old.get(key):
                        field_diffs[key] += 1
                if len(diff_examples) < 15:
                    diff_examples.append({
                        "subscription": subscription,
                        "tag": tag,
                        "new": sanitized(compare_new),
                        "old": sanitized(compare_old),
                    })
        if row:
            row.update({
                "new_transport": (new or {}).get("transport", {}).get("type", "<none>"),
                "new_tls_server": (new or {}).get("tls", {}).get("server_name", ""),
                "new_reality": bool((new or {}).get("tls", {}).get("reality")),
                "new_packet_encoding": (new or {}).get("packet_encoding", ""),
                "legacy_parsed": bool(old),
                "new_parsed": bool(new),
            })
            screenshot_rows.append(row)

    result = {
        "links": len(links),
        "schemes": dict(schemes),
        "parsed_new": parsed_new,
        "parsed_legacy": parsed_old,
        "parsed_both": parsed_both,
        "identical_structures": identical,
        "new_errors": dict(new_errors),
        "legacy_errors": dict(old_errors),
        "raw_params": {key: dict(value) for key, value in raw_params.items()},
        "top_field_differences": dict(field_diffs.most_common(20)),
        "diff_examples": diff_examples,
        "screenshot_tags": screenshot_rows,
    }
    if args.output:
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
