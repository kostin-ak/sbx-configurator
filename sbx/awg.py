"""Parsers for WireGuard / AmneziaWG configuration files."""

from __future__ import annotations

import re
from typing import Any

from .links import LinkError

_SECTION = re.compile(r"^\[(Interface|Peer)\]\s*$", re.IGNORECASE)


def _normalize_key(key: str) -> str:
    """Make ``HeaderProtectionKey`` and ``header_protection_key`` equivalent."""
    return re.sub(r"[_\s-]", "", key).lower()


def _parse_ini(text: str) -> list[dict[str, str]]:
    sections: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        match = _SECTION.match(line)
        if match:
            current = {"__section__": match.group(1).lower()}
            sections.append(current)
            continue
        if current is None or "=" not in line:
            raise LinkError(f"unexpected line in wireguard config: {line[:60]}")
        key, value = line.split("=", 1)
        current[_normalize_key(key)] = value.strip()
    return sections


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _int(value: str, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


_AMNEZIA_INTS = ("jc", "jmin", "jmax", "s1", "s2", "s3", "s4")
_AMNEZIA_RANGES = {
    "h1": "h1",
    "h2": "h2",
    "h3": "h3",
    "h4": "h4",
    "contentpaddingaddition": "content_padding_addition",
}
_AMNEZIA_STRINGS = {
    "i1": "i1",
    "i2": "i2",
    "i3": "i3",
    "i4": "i4",
    "i5": "i5",
    "headerprotectionkey": "header_protection_key",
}


def _amnezia_section(values: dict[str, str]) -> dict[str, Any] | None:
    section: dict[str, Any] = {}
    for key in _AMNEZIA_INTS:
        if key in values:
            section[key] = _int(values[key])
    for key, target in _AMNEZIA_RANGES.items():
        if key in values:
            section[target] = values[key]
    for key, target in _AMNEZIA_STRINGS.items():
        if key in values:
            section[target] = values[key]
    return section or None


def parse_wireguard_conf(text: str, tag: str, system: bool = False) -> dict[str, Any]:
    """Convert a wg-quick style config into a sing-box wireguard endpoint."""
    sections = _parse_ini(text)
    interface = next((s for s in sections if s.get("__section__") == "interface"), None)
    peers = [s for s in sections if s.get("__section__") == "peer"]
    if interface is None:
        raise LinkError("wireguard config has no [Interface]")
    if not peers:
        raise LinkError("wireguard config has no [Peer]")
    private_key = interface.get("privatekey")
    if not private_key:
        raise LinkError("wireguard config has no PrivateKey")
    address = _split_csv(interface.get("address", ""))
    if not address:
        raise LinkError("wireguard config has no Address")
    endpoint: dict[str, Any] = {
        "type": "wireguard",
        "tag": tag,
        "name": tag,
        "system": system,
        "address": address,
        "private_key": private_key,
        "peers": [],
    }
    if interface.get("mtu"):
        endpoint["mtu"] = _int(interface["mtu"], 1420)
    amnezia = _amnezia_section(interface)
    if amnezia:
        endpoint["amnezia"] = amnezia
    for peer in peers:
        remote = peer.get("endpoint", "")
        host, _, port = remote.rpartition(":")
        if not host or not port.isdigit():
            raise LinkError(f"wireguard peer has invalid endpoint: {remote[:60]}")
        public_key = peer.get("publickey")
        if not public_key:
            raise LinkError("wireguard peer has no PublicKey")
        item: dict[str, Any] = {
            "address": host.strip("[]"),
            "port": int(port),
            "public_key": public_key,
        }
        if peer.get("allowedips"):
            item["allowed_ips"] = _split_csv(peer["allowedips"])
        if peer.get("persistentkeepalive"):
            item["persistent_keepalive_interval"] = _int(peer["persistentkeepalive"], 25)
        if peer.get("presharedkey"):
            item["pre_shared_key"] = peer["presharedkey"]
        endpoint["peers"].append(item)
    return endpoint
