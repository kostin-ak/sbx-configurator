"""Semantic configuration summaries and secret-free differences."""

from __future__ import annotations

from collections import Counter
from typing import Any

from .secrets import mask_config


def _typed(items: Any, kind_key: str = "type") -> dict[str, Counter]:
    by_kind: dict[str, Counter] = {}
    for item in items or []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get(kind_key, "<missing>"))
        tag = item.get("tag", "<no-tag>")
        by_kind.setdefault(kind, Counter())[str(tag)] += 1
    return by_kind


def summary(config: dict[str, Any]) -> dict[str, Any]:
    route = config.get("route", {})
    return {
        "inbounds": _typed(config.get("inbounds")),
        "outbounds": _typed(config.get("outbounds")),
        "endpoints": _typed(config.get("endpoints")),
        "dns_servers": _typed(config.get("dns", {}).get("servers")),
        "selectors": sorted(
            item["tag"] for item in config.get("outbounds", [])
            if isinstance(item, dict) and item.get("type") == "selector"
        ),
        "route_rules": len(route.get("rules", [])),
        "route_rule_set_tags": sorted(item.get("tag") for item in route.get("rule_set", []) if isinstance(item, dict)),
        "final": route.get("final"),
    }


def _counter_delta(old: dict[str, Counter], new: dict[str, Counter]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for kind in sorted(set(old) | set(new)):
        added = new.get(kind, Counter()) - old.get(kind, Counter())
        removed = old.get(kind, Counter()) - new.get(kind, Counter())
        if added or removed:
            result[kind] = {
                "added": sorted(added.elements()),
                "removed": sorted(removed.elements()),
                "count_changed": sorted(added + removed),
            }
    return result


def semantic_diff(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    old_summary = summary(old)
    new_summary = summary(new)
    result: dict[str, Any] = {
        "inbounds": _counter_delta(old_summary["inbounds"], new_summary["inbounds"]),
        "outbounds": _counter_delta(old_summary["outbounds"], new_summary["outbounds"]),
        "endpoints": _counter_delta(old_summary["endpoints"], new_summary["endpoints"]),
        "dns_servers": _counter_delta(old_summary["dns_servers"], new_summary["dns_servers"]),
    }
    for key in ("selectors", "route_rule_set_tags"):
        old_set, new_set = set(old_summary[key]), set(new_summary[key])
        if old_set != new_set:
            result[key] = {"added": sorted(new_set - old_set), "removed": sorted(old_set - new_set)}
    if old_summary["route_rules"] != new_summary["route_rules"]:
        result["route_rules"] = {"old": old_summary["route_rules"], "new": new_summary["route_rules"]}
    if old_summary["final"] != new_summary["final"]:
        result["final"] = {"old": old_summary["final"], "new": new_summary["final"]}
    result["changed"] = bool(result["inbounds"] or result["outbounds"] or result["endpoints"]
                             or result["dns_servers"] or any(key in result for key in
                             ("selectors", "route_rule_set_tags", "route_rules", "final")))
    return result


def masked_json(config: dict[str, Any]) -> dict[str, Any]:
    return mask_config(config)
