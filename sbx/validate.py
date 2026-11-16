"""Fast structural validation before invoking the sing-box binary."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


OUTBOUND_TYPES = {
    "direct", "block", "bridge", "socks", "http", "shadowsocks", "vmess", "trojan",
    "wireguard", "hysteria", "shadowtls", "vless", "tuic", "hysteria2", "anytls",
    "snell", "tailcat", "tor", "ssh", "selector", "urltest", "parser", "bond",
    "fallback", "failover", "mieru", "trusttunnel", "sudoku", "call", "masque",
}
ENDPOINT_TYPES = {
    "wireguard", "tailscale", "openconnect", "openvpn-client", "openvpn-server",
    "warp", "vpn-client", "vpn-server", "masque-client", "masque-server",
}


@dataclass(frozen=True)
class Issue:
    severity: str
    code: str
    message: str


def _dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def validate_config(config: dict[str, Any]) -> list[Issue]:
    issues: list[Issue] = []

    inbounds = _dicts(config.get("inbounds"))
    outbound_entries = _dicts(config.get("outbounds"))
    endpoint_entries = _dicts(config.get("endpoints"))
    dns_servers = _dicts(config.get("dns", {}).get("servers"))

    inbound_tags = {item["tag"] for item in inbounds if "tag" in item}
    outbound_tags: dict[str, str] = {}
    for item in outbound_entries:
        tag = item.get("tag")
        kind = item.get("type")
        if not tag:
            if kind == "selector":
                issues.append(Issue("warning", "empty-selector-tag", "selector without tag; generated source should omit it"))
                continue
            issues.append(Issue("error", "missing-tag", f"outbound without tag: type={kind}"))
            continue
        if tag in outbound_tags:
            issues.append(Issue("error", "duplicate-outbound", f"duplicate outbound tag: {tag}"))
            continue
        outbound_tags[tag] = kind or ""
        if kind not in OUTBOUND_TYPES:
            issues.append(Issue("error", "unknown-outbound-type", f"unknown outbound type {kind} for {tag}"))

    endpoint_tags: set[str] = set()
    for item in endpoint_entries:
        tag = item.get("tag")
        kind = item.get("type")
        if not tag:
            issues.append(Issue("error", "missing-tag", f"endpoint without tag: type={kind}"))
            continue
        if tag in endpoint_tags or tag in outbound_tags:
            issues.append(Issue("error", "duplicate-tag", f"duplicate endpoint tag: {tag}"))
            continue
        endpoint_tags.add(tag)
        if kind not in ENDPOINT_TYPES:
            issues.append(Issue("error", "unknown-endpoint-type", f"unknown endpoint type {kind} for {tag}"))

    dns_tags = {item["tag"] for item in dns_servers if "tag" in item}
    route = config.get("route", {})
    rules = _dicts(route.get("rules"))
    rule_set_tags = {item["tag"] for item in _dicts(route.get("rule_set"))}
    final = route.get("final")

    for item in outbound_entries:
        if item.get("type") == "selector":
            members = item.get("outbounds", [])
            if not isinstance(members, list) or not members:
                issues.append(Issue("error", "empty-selector", f"selector has no members: {item.get('tag')}"))
            for member in members:
                if member not in outbound_tags and member not in endpoint_tags:
                    issues.append(Issue("error", "broken-selector", f"selector {item.get('tag')} references missing {member}"))
        detour = item.get("detour")
        if isinstance(detour, str) and detour and detour not in outbound_tags and detour not in endpoint_tags:
            issues.append(Issue("error", "broken-detour", f"outbound {item.get('tag')} detours to missing {detour}"))

    for item in endpoint_entries:
        detour = item.get("detour")
        if isinstance(detour, str) and detour and detour not in outbound_tags and detour not in endpoint_tags:
            issues.append(Issue("error", "broken-detour", f"endpoint {item.get('tag')} detours to missing {detour}"))

    for index, rule in enumerate(rules):
        if "outbound" not in rule:
            continue
        reference = rule["outbound"]
        if reference not in outbound_tags and reference not in endpoint_tags:
            issues.append(Issue("error", "broken-route", f"route rule {index} references missing outbound {reference}"))
        for inbound in rule.get("inbound", []):
            if inbound not in inbound_tags:
                issues.append(Issue("warning", "unused-inbound-reference", f"route rule {index} references absent inbound {inbound}"))
        for rule_set in rule.get("rule_set", []):
            if rule_set not in rule_set_tags:
                issues.append(Issue("error", "missing-rule-set", f"route rule {index} references missing rule-set {rule_set}"))

    if final and final not in outbound_tags and final not in endpoint_tags:
        issues.append(Issue("error", "broken-final", f"route.final references missing outbound {final}"))

    issues.extend(_detect_cycles(outbound_entries, endpoint_entries))

    for item in dns_servers:
        resolver = item.get("domain_resolver")
        if isinstance(resolver, str) and resolver not in dns_tags:
            issues.append(Issue("error", "broken-dns-resolver", f"DNS server {item.get('tag')} references missing resolver {resolver}"))
    for index, rule in enumerate(_dicts(config.get("dns", {}).get("rules"))):
        if rule.get("server") and rule["server"] not in dns_tags:
            issues.append(Issue("error", "broken-dns-route", f"DNS rule {index} references missing server {rule['server']}"))

    for item in _dicts(route.get("rule_set")):
        if item.get("type") == "local":
            path = item.get("path")
            if path and not Path(path).is_file():
                issues.append(Issue("error", "missing-local-rule-set", f"local rule-set file is absent: {path}"))

    return issues


def _detect_cycles(outbound_entries: list[dict[str, Any]], endpoint_entries: list[dict[str, Any]]) -> list[Issue]:
    """Detect selector/detour cycles that sing-box rejects only at startup."""
    edges: dict[str, list[str]] = {}
    for item in [*outbound_entries, *endpoint_entries]:
        tag = item.get("tag")
        if not tag:
            continue
        targets: list[str] = []
        if item.get("type") in {"selector", "urltest", "fallback", "failover", "bond"}:
            targets.extend(member for member in item.get("outbounds") or [] if isinstance(member, str))
        detour = item.get("detour")
        if isinstance(detour, str) and detour:
            targets.append(detour)
        edges[tag] = targets

    issues: list[Issue] = []
    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(tag: str) -> None:
        current = state.get(tag, 0)
        if current == 2:
            return
        if current == 1:
            cycle_start = stack.index(tag) if tag in stack else 0
            cycle = " -> ".join([*stack[cycle_start:], tag])
            issues.append(Issue("error", "outbound-cycle", f"circular outbound dependency: {cycle}"))
            return
        state[tag] = 1
        stack.append(tag)
        for target in edges.get(tag, []):
            if target in edges:
                visit(target)
        stack.pop()
        state[tag] = 2

    for tag in edges:
        visit(tag)
    return issues


def binary_check(binary: Path, config: Path, workdir: Path, timeout: int = 120) -> tuple[int, str]:
    import subprocess

    workdir.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [str(binary), "check", "-c", str(config), "-D", str(workdir)],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return completed.returncode, (completed.stderr or completed.stdout).strip()
