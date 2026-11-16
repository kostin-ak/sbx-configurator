"""Configuration v2 loader translated into the proven internal models."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


API_VERSION = "sbx.shtorm/1"


class ConfigError(ValueError):
    pass


@dataclass
class LoadedConfig:
    subscriptions: dict[str, Any]
    routing: dict[str, Any]
    stats: dict[str, int]


def read_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise ConfigError(f"{path} must contain a mapping")
    if value.get("apiVersion") != API_VERSION:
        raise ConfigError(f"{path}: expected apiVersion {API_VERSION}")
    return value


def yaml_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted([*directory.glob("*.yaml"), *directory.glob("*.yml")])


def secret_value(secrets: dict[str, Any], dotted: str) -> Any:
    current: Any = secrets
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            raise ConfigError(f"secret is not defined: {dotted}")
        current = current[part]
    return current


def resolve_secrets(value: Any, secrets: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {key: resolve_secrets(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_secrets(item, secrets) for item in value]
    if isinstance(value, str) and value.startswith("${secret:") and value.endswith("}"):
        return secret_value(secrets, value[9:-1])
    return value


def load_templates(root: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    path = root / "selectors.yaml"
    if not path.is_file():
        return [], {}
    document = read_yaml(path)
    if document.get("kind") != "Selectors":
        raise ConfigError(f"{path}: expected kind Selectors")
    result: list[dict[str, Any]] = []
    named: dict[str, dict[str, Any]] = {}
    for template in document.get("templates", []):
        name = template.get("name")
        if not name:
            raise ConfigError(f"{path}: selector template requires name")
        definition = {key: deepcopy(value) for key, value in template.items() if key != "name"}
        named[name] = definition
        result.append(definition)
    return result, named


def load_subscription(path: Path, secrets: dict[str, Any], global_selectors: list[dict[str, Any]], named: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    document = read_yaml(path)
    if document.get("kind") != "Subscription":
        raise ConfigError(f"{path}: expected kind Subscription")
    metadata = document.get("metadata", {})
    if not metadata.get("enabled", True):
        return None
    document = resolve_secrets(document, secrets)
    name = metadata.get("name")
    if not name:
        raise ConfigError(f"{path}: metadata.name is required")
    fetch = document.get("fetch", {})
    subscription: dict[str, Any] = {"name": name}
    if fetch.get("url"):
        subscription["url"] = fetch["url"]
    if fetch.get("file"):
        subscription["file"] = fetch["file"]
    if fetch.get("folder"):
        subscription["folder"] = deepcopy(fetch["folder"])
    if not subscription.get("url") and not subscription.get("file") and not subscription.get("folder"):
        raise ConfigError(f"{path}: fetch.url, fetch.file or fetch.folder is required")
    cache = fetch.get("cache", {})
    if cache.get("enabled"):
        subscription["enable_cache"] = True
    subscription["rules"] = deepcopy(document.get("transforms", []))
    if document.get("naming"):
        subscription["naming"] = deepcopy(document["naming"])
    if document.get("tls"):
        subscription["tls"] = deepcopy(document["tls"])

    selector_config = document.get("selectors", {})
    selectors: list[dict[str, Any]] = []
    if selector_config.get("global", True):
        selectors.extend(deepcopy(global_selectors))
    for local in selector_config.get("local", []):
        if "template" in local:
            template_name = local["template"]
            if template_name not in named:
                raise ConfigError(f"{path}: unknown selector template {template_name}")
            selectors.append(deepcopy(named[template_name]))
        elif local.get("expand") == "all":
            selectors.append({
                "tag": "",
                "type": local.get("type", "selector"),
                "filter": local.get("filter", ""),
                "regex": True,
            })
        else:
            selectors.append(deepcopy(local))
    if selectors:
        subscription["selectors"] = selectors
    if document.get("outbounds"):
        subscription["outbounds"] = deepcopy(document["outbounds"])
    if document.get("endpoints"):
        subscription["endpoints"] = deepcopy(document["endpoints"])
    return subscription


def render_protocol(path: Path, secrets: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    document = read_yaml(path)
    if document.get("kind") != "Protocol":
        raise ConfigError(f"{path}: expected kind Protocol")
    metadata = document.get("metadata", {})
    if not metadata.get("enabled", True):
        return None
    document = resolve_secrets(document, secrets)
    protocol = deepcopy(document.get("protocol", {}))
    section = protocol.pop("section", None)
    if section not in {"outbounds", "endpoints"}:
        raise ConfigError(f"{path}: protocol.section must be outbounds or endpoints")
    if not protocol.get("type") or not protocol.get("tag"):
        raise ConfigError(f"{path}: protocol.type and protocol.tag are required")
    for block in ("connection", "credentials", "tunnel", "profile", "options"):
        for key, value in document.get(block, {}).items():
            protocol[key] = deepcopy(value)
    return section, protocol


def load_routing(root: Path) -> dict[str, Any]:
    categories_document = read_yaml(root / "routing/categories.yaml")
    devices_document = read_yaml(root / "routing/devices.yaml")
    groups_document = read_yaml(root / "routing/groups.yaml")
    policies_document = read_yaml(root / "routing/policies.yaml")
    rules_document = read_yaml(root / "routing/rule-sets.yaml")

    displays: dict[str, str] = {}
    categories: list[dict[str, Any]] = []
    for category in categories_document.get("categories", []):
        key = category["name"]
        display = category["display"]
        displays[key] = display
        data: Any = deepcopy(category.get("rules", []))
        if category.get("disable_default"):
            data = [{"disable_default": True}, *data]
        categories.append({display: data})

    policies: dict[str, list[str]] = {}
    for policy in policies_document.get("policies", []):
        alias = policy["alias"]
        category_names = policy.get("categories", [])
        unknown = [name for name in category_names if name not in displays]
        if unknown:
            raise ConfigError(f"policy {alias} references unknown categories: {unknown}")
        policies[alias] = [displays[name] for name in category_names]

    defaults = policies_document.get("defaults", {})
    catch_all = defaults.get("catch_all")
    if catch_all:
        if catch_all not in displays:
            raise ConfigError(f"defaults.catch_all references unknown category {catch_all}")
        categories.append({displays[catch_all]: [{}]})
    final = defaults.get("final")
    settings = policies_document.get("settings", {})
    if final:
        if final not in displays:
            raise ConfigError(f"defaults.final references unknown category {final}")
        settings["final_outbound"] = f"{displays[final]} [Default]"

    return {
        "settings": settings,
        "pre_rules": deepcopy(rules_document.get("pre_rules", [])),
        "devices": {
            name: deepcopy(value.get("ipv4") if isinstance(value, dict) else value)
            for name, value in devices_document.get("devices", {}).items()
        },
        "groups": {
            name: deepcopy(value.get("members", []) if isinstance(value, dict) else value)
            for name, value in groups_document.get("groups", {}).items()
        },
        "categories": categories,
        "policies": policies,
        "post_rules": deepcopy(rules_document.get("post_rules", [])),
        "rule_sets": deepcopy(rules_document.get("rule_sets", [])),
    }


def load_config(root: Path, secrets_path: Path | None = None) -> LoadedConfig:
    secrets: dict[str, Any] = {}
    if secrets_path and secrets_path.is_file():
        secrets = yaml.safe_load(secrets_path.read_text(encoding="utf-8")) or {}
    global_selectors, named = load_templates(root)
    subscriptions: list[dict[str, Any]] = []
    for path in yaml_files(root / "subscriptions.d"):
        subscription = load_subscription(path, secrets, global_selectors, named)
        if subscription:
            subscriptions.append(subscription)

    native_outbounds: list[dict[str, Any]] = []
    native_endpoints: list[dict[str, Any]] = []
    for path in yaml_files(root / "protocols.d"):
        rendered = render_protocol(path, secrets)
        if rendered:
            section, protocol = rendered
            (native_outbounds if section == "outbounds" else native_endpoints).append(protocol)
    if native_outbounds or native_endpoints:
        extended: dict[str, Any] = {
            "name": "Extended",
            "content": "",
            "selectors": deepcopy(global_selectors),
        }
        if native_outbounds:
            extended["outbounds"] = native_outbounds
        if native_endpoints:
            extended["endpoints"] = native_endpoints
        subscriptions.append(extended)

    return LoadedConfig(
        subscriptions={"settings": {"force_cache": False}, "selectors": [], "subscriptions": subscriptions},
        routing=load_routing(root),
        stats={
            "subscriptions": len(subscriptions),
            "native_outbounds": len(native_outbounds),
            "native_endpoints": len(native_endpoints),
        },
    )
