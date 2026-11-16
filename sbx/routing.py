"""Deterministic route rule and selector-database generator."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


def generate_routing(config_path: Path, routing_output: Path, selectors_output: Path) -> dict[str, int]:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    settings = config.get("settings", {})
    devices: dict[str, Any] = config.get("devices", {})
    groups: dict[str, Any] = config.get("groups", {})
    policies: dict[str, Any] = config.get("policies", {})
    generated: set[str] = set()
    rules: list[dict[str, Any]] = deepcopy(config.get("pre_rules", []))

    def resolve(alias: str) -> list[str]:
        if alias in devices:
            return [devices[alias]]
        return sorted({devices[member] for member in groups.get(alias, []) if member in devices})

    raw_categories = config.get("categories", [])
    if isinstance(raw_categories, dict):
        categories = list(raw_categories.items())
    else:
        categories = [(key, value) for item in raw_categories for key, value in item.items()]

    for category, data in categories:
        category_rules: list[dict[str, Any]]
        disable_default = False
        if isinstance(data, list):
            category_rules = []
            for item in data:
                if isinstance(item, dict) and "disable_default" in item:
                    disable_default = bool(item["disable_default"])
                else:
                    category_rules.append(item)
        elif isinstance(data, dict):
            category_rules = data.get("rules", [])
            disable_default = bool(data.get("disable_default"))
        else:
            continue

        aliases = [alias for alias, requested in policies.items() if category in requested]
        for alias in aliases:
            addresses = resolve(alias)
            if not addresses:
                continue
            target = f"{category} [{alias}]"
            generated.add(target)
            for template in category_rules:
                rule = deepcopy(template)
                rule["source_ip_cidr"] = addresses
                rule["outbound"] = target
                rules.append(rule)

        if not disable_default:
            target = f"{category} [Default]"
            generated.add(target)
            for template in category_rules:
                rule = deepcopy(template)
                rule["outbound"] = target
                rules.append(rule)

    rules.extend(deepcopy(config.get("post_rules", [])))
    route: dict[str, Any] = {"rules": rules}
    if config.get("rule_sets"):
        route["rule_set"] = config["rule_sets"]
    for source, destination in (
        ("final_outbound", "final"),
        ("auto_detect_interface", "auto_detect_interface"),
        ("default_domain_resolver", "default_domain_resolver"),
    ):
        if source in settings:
            route[destination] = settings[source]

    routing_output.parent.mkdir(parents=True, exist_ok=True)
    selectors_output.parent.mkdir(parents=True, exist_ok=True)
    import json
    routing_output.write_text(json.dumps({"route": route}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    selectors_output.write_text(
        yaml.dump({"selectors": [{"tag": tag} for tag in sorted(generated)]}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return {"rules": len(rules), "selectors": len(generated)}
