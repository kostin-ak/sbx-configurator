"""Pure, testable transformations for the 1.12 -> 1.14 configuration move."""

from __future__ import annotations

from copy import deepcopy
from pathlib import PurePosixPath
from typing import Any


def _rewrite_strings(value: Any, replacements: list[tuple[str, str]]) -> Any:
    if isinstance(value, dict):
        return {key: _rewrite_strings(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [_rewrite_strings(item, replacements) for item in value]
    if isinstance(value, str):
        for old, new in replacements:
            if value == old:
                return new
            if value.startswith(old + "/"):
                return new + value[len(old):]
    return value


def migrate_config(config: dict[str, Any], snapshot_root: str, state_root: str, rules_root: str | None = None) -> tuple[dict[str, Any], list[str]]:
    """Return a relocated candidate and a human-readable list of changes."""

    result = deepcopy(config)
    changes: list[str] = []

    sniff_inbounds: list[str] = []
    for inbound in result.get("inbounds", []):
        if not isinstance(inbound, dict):
            continue
        had_sniff = bool(inbound.pop("sniff", False))
        had_override = bool(inbound.pop("sniff_override_destination", False))
        if had_sniff or had_override:
            sniff_inbounds.append(inbound.get("tag", ""))
    if sniff_inbounds:
        changes.append("moved inbound sniffing to route actions")

    route = result.setdefault("route", {})
    rules = route.setdefault("rules", [])
    for rule in rules:
        if isinstance(rule, dict) and rule.get("outbound") == "DIRECT":
            rule["outbound"] = "direct"
            changes.append("normalized DIRECT outbound reference")
    existing_sniff = {
        (rule.get("inbound"), rule.get("action"))
        for rule in rules
        if isinstance(rule, dict) and isinstance(rule.get("inbound"), str)
    }
    sniff_rules = [
        {"inbound": tag, "action": "sniff"}
        for tag in sniff_inbounds
        if (tag, "sniff") not in existing_sniff
    ]
    rules[:0] = sniff_rules

    cache = result.get("experimental", {}).get("cache_file", {})
    if "store_rdrc" in cache:
        cache.setdefault("store_dns", cache["store_rdrc"])
        del cache["store_rdrc"]
        changes.append("replaced store_rdrc with store_dns")

    replacements = []
    if rules_root:
        replacements.append(("/etc/sing-box/rules", str(PurePosixPath(rules_root))))
    replacements.extend([
        ("/etc/sing-box", str(PurePosixPath(snapshot_root) / "etc/sing-box")),
        ("/usr/share/sing-box", str(PurePosixPath(state_root))),
    ])
    result = _rewrite_strings(result, replacements)
    log = result.get("log", {})
    if isinstance(log.get("output"), str) and log["output"].startswith(str(PurePosixPath(snapshot_root))):
        log["output"] = str(PurePosixPath(state_root) / "logs/sing-box.log")
        changes.append("relocated runtime log outside the immutable snapshot")
    clash = result.get("experimental", {}).get("clash_api", {})
    if isinstance(clash.get("external_ui"), str) and PurePosixPath(clash["external_ui"]).name == "ui":
        clash["external_ui"] = str(PurePosixPath(state_root) / "ui")
        changes.append("relocated external UI directory for local runtime")
    changes.append("relocated router paths for local validation")
    return result, changes
