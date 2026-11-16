"""Static consistency checks for a configuration tree.

`load_config` validates the schema. This module checks the cross-references the
schema cannot see: categories → rule-sets, policies → categories/devices,
group members, duplicate addresses and selector regexes. The checks read the raw
YAML files, so they also work while the tree is being edited.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .loader import ConfigError, load_config


@dataclass(frozen=True)
class LintIssue:
    level: str
    code: str
    message: str

    def render(self) -> str:
        return f"{self.level}: {self.message} [{self.code}]"


def _read(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _regex(pattern: str) -> str | None:
    try:
        re.compile(pattern)
    except re.error as error:
        return str(error)
    return None


def lint_config(config_dir: Path, secrets: Path | None = None) -> list[LintIssue]:
    issues: list[LintIssue] = []
    routing_dir = config_dir / "routing"

    categories_doc = _read(routing_dir / "categories.yaml")
    categories_list = [item for item in categories_doc.get("categories", []) or [] if isinstance(item, dict)]
    categories = {str(item.get("name")) for item in categories_list if item.get("name")}

    rule_sets_doc = _read(routing_dir / "rule-sets.yaml")
    rule_sets = {
        str(item.get("tag"))
        for item in rule_sets_doc.get("rule_sets", []) or []
        if isinstance(item, dict) and item.get("tag")
    }

    devices = _read(routing_dir / "devices.yaml").get("devices") or {}
    groups = _read(routing_dir / "groups.yaml").get("groups") or {}
    aliases = set(devices) | set(groups)

    policies_doc = _read(routing_dir / "policies.yaml")
    policies = [item for item in policies_doc.get("policies", []) or [] if isinstance(item, dict)]

    for category in categories_list:
        name = category.get("name", "?")
        for rule in category.get("rules", []) or []:
            if not isinstance(rule, dict):
                continue
            for tag in rule.get("rule_set", []) or []:
                if tag not in rule_sets:
                    issues.append(
                        LintIssue("error", "category-rule-set", f"category {name} references unknown rule_set {tag}")
                    )

    for policy in policies:
        alias = str(policy.get("alias", "?"))
        if alias not in aliases:
            issues.append(LintIssue("warning", "policy-alias", f"policy {alias} is neither a device nor a group"))
        for category in policy.get("categories", []) or []:
            if category not in categories:
                issues.append(
                    LintIssue("error", "policy-category", f"policy {alias} references unknown category {category}")
                )

    for name, group in groups.items():
        if not isinstance(group, dict):
            continue
        for member in group.get("members", []) or []:
            if member not in aliases:
                issues.append(LintIssue("error", "group-member", f"group {name} references unknown member {member}"))

    seen: dict[str, str] = {}
    for name, device in devices.items():
        if not isinstance(device, dict):
            continue
        for family in ("ipv4", "ipv6"):
            address = device.get(family)
            if not address:
                continue
            if address in seen:
                issues.append(
                    LintIssue("warning", "duplicate-address", f"{name} and {seen[address]} share {family} {address}")
                )
            else:
                seen[str(address)] = str(name)

    defaults = policies_doc.get("defaults") or {}
    for key in ("final", "catch_all"):
        value = defaults.get(key)
        if value and value not in categories:
            issues.append(LintIssue("error", "defaults-category", f"defaults.{key} references unknown category {value}"))

    selectors_doc = _read(config_dir / "selectors.yaml")
    names: set[str] = set()
    tags: set[str] = set()
    for template in selectors_doc.get("templates", []) or []:
        if not isinstance(template, dict):
            continue
        name = str(template.get("name", ""))
        tag = str(template.get("tag", ""))
        if name in names:
            issues.append(LintIssue("warning", "selector-duplicate", f"duplicate selector name {name}"))
        if tag in tags:
            issues.append(LintIssue("warning", "selector-duplicate", f"duplicate selector tag {tag}"))
        names.add(name)
        tags.add(tag)
        if template.get("regex", True):
            error = _regex(str(template.get("filter", ".*")))
            if error:
                issues.append(LintIssue("error", "selector-regex", f"selector {name}: {error}"))
        if template.get("prefer"):
            error = _regex(str(template["prefer"]))
            if error:
                issues.append(LintIssue("error", "selector-regex", f"selector {name} prefer: {error}"))

    subscriptions_dir = config_dir / "subscriptions.d"
    if subscriptions_dir.is_dir():
        for path in sorted(subscriptions_dir.glob("*.yaml")):
            document = _read(path)
            if document.get("kind") != "Subscription":
                continue
            subscription_name = str((document.get("metadata") or {}).get("name") or path.stem)
            for index, rule in enumerate(document.get("transforms", []) or []):
                if not isinstance(rule, dict):
                    continue
                error = _regex(str(rule.get("pattern", ".*")))
                if error:
                    issues.append(LintIssue("error", "transform-regex", f"{subscription_name} transform #{index + 1}: {error}"))
            local = ((document.get("selectors") or {}).get("local") or [])
            for index, selector in enumerate(local):
                if isinstance(selector, dict) and selector.get("filter"):
                    error = _regex(str(selector["filter"]))
                    if error:
                        issues.append(
                            LintIssue("error", "selector-regex", f"{subscription_name} local selector #{index + 1}: {error}")
                        )

    try:
        load_config(config_dir, secrets)
    except (ConfigError, ValueError, OSError) as error:
        issues.append(LintIssue("error", "schema", str(error)))

    return issues


def has_errors(issues: list[LintIssue]) -> bool:
    return any(issue.level == "error" for issue in issues)


def summarize(issues: list[LintIssue]) -> dict[str, int]:
    return {
        "errors": sum(1 for issue in issues if issue.level == "error"),
        "warnings": sum(1 for issue in issues if issue.level == "warning"),
    }