"""Generate an isolated proxy-only runtime candidate."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .offline import stub_remote_rule_sets


def make_proxy_only(
    config: dict[str, Any],
    listen: str = "127.0.0.1",
    port: int = 7891,
    clash_port: int | None = None,
    offline_rule_sets: bool = False,
    compiler: Any = None,
    stub_dir: Any = None,
    local_direct: bool = True,
) -> tuple[dict[str, Any], list[str]]:
    """Return a runtime config without TUN, DNS hijack and router interception."""

    result = deepcopy(config)
    changes: list[str] = []
    route = result.get("route", {})

    removed_tags: set[str] = set()
    kept_inbounds: list[dict[str, Any]] = []
    for inbound in result.get("inbounds", []):
        if not isinstance(inbound, dict):
            continue
        if inbound.get("type") == "tun":
            removed_tags.add(inbound.get("tag", ""))
            changes.append("removed TUN inbound")
            continue
        if inbound.get("type") in {"mixed", "socks", "http"} and "listen_port" in inbound:
            inbound["listen"] = listen
            inbound["listen_port"] = port
            changes.append(f"rebound proxy inbound to {listen}:{port}")
        kept_inbounds.append(inbound)
    result["inbounds"] = kept_inbounds

    if local_direct:
        outbound_tags = {
            item.get("tag")
            for item in result.get("outbounds", [])
            if isinstance(item, dict)
        }
        if "direct" in outbound_tags:
            route.setdefault("rules", []).insert(0, {
                "ip_cidr": ["127.0.0.0/8", "::1/128"],
                "outbound": "direct",
            })
            changes.append("routed loopback directly for deterministic tests")

    if offline_rule_sets:
        if compiler is None or stub_dir is None:
            raise ValueError("offline_rule_sets requires compiler and stub_dir")
        result, stub_changes = stub_remote_rule_sets(result, stub_dir, compiler)
        changes.extend(stub_changes)

    route = result.get("route", {})
    kept_rules: list[dict[str, Any]] = []
    for rule in route.get("rules", []):
        if not isinstance(rule, dict):
            continue
        rule_inbounds = rule.get("inbound", [])
        if isinstance(rule_inbounds, str):
            rule_inbounds = [rule_inbounds]
        if rule.get("action") == "hijack-dns":
            changes.append("removed DNS hijack rule")
            continue
        if any(tag in removed_tags for tag in rule_inbounds):
            changes.append("removed rule bound to removed TUN inbound")
            continue
        kept_rules.append(rule)
    route["rules"] = kept_rules

    if clash_port:
        clash = result.get("experimental", {}).get("clash_api", {})
        if clash:
            clash["external_controller"] = f"127.0.0.1:{clash_port}"
            changes.append(f"moved Clash API to 127.0.0.1:{clash_port}")
        for field in ("external_ui", "external_ui_download_url", "external_ui_download_detour"):
            if clash.pop(field, None) is not None:
                changes.append(f"removed optional Clash API {field} for isolated runtime")

    return result, changes
