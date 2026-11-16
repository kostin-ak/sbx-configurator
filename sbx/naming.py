"""Deterministic, Clash-UI friendly outbound naming."""

from __future__ import annotations

import re
import zlib
from typing import Any

_FLAG_PAIR = re.compile("([\U0001F1E6-\U0001F1FF])([\U0001F1E6-\U0001F1FF])")
_WHITELIST = re.compile(r"WL|Whitelist|Обход", re.IGNORECASE)

_TRANSPORTS = {
    "tcp": "TCP",
    "ws": "WS",
    "grpc": "gRPC",
    "xhttp": "XHTTP",
    "httpupgrade": "HTTPU",
    "quic": "QUIC",
    "kcp": "mKCP",
}

_FLAG_BASE = 0x1F1E6


def split_flag(tag: str) -> tuple[str, str]:
    """Return (flag emoji, ISO country code) found in the tag, or ('', '')."""
    match = _FLAG_PAIR.search(tag)
    if not match:
        return "", ""
    code = "".join(chr(ord(character) - 0x1F1E6 + ord("A")) for character in match.groups())
    return match.group(0), code


def flag_for(country: str) -> str:
    """Return the flag emoji for a two-letter country code."""
    code = country.strip().upper()
    if len(code) != 2 or not code.isalpha():
        return ""
    return "".join(chr(_FLAG_BASE + ord(letter) - ord("A")) for letter in code)


def transport_label(node: dict[str, Any]) -> str:
    if node.get("type") in {"hysteria2", "hysteria"}:
        return "HY2"
    if node.get("type") == "warp":
        return "WARP"
    if node.get("type") == "wireguard":
        return "AWG" if node.get("amnezia") else "WG"
    transport = (node.get("transport") or {}).get("type", "tcp")
    label = _TRANSPORTS.get(transport, transport.upper())
    if (node.get("tls") or {}).get("reality"):
        label += "-R"
    return label


def stable_id(node: dict[str, Any]) -> int:
    """Stable per-server suffix so the Clash UI selection survives refreshes."""
    if node.get("type") in {"wireguard", "warp"}:
        peers = node.get("peers") or [{}]
        key = f"{peers[0].get('address', '')}:{peers[0].get('port', '')}"
    else:
        key = f"{node.get('server', '')}:{node.get('server_port', '')}"
    return zlib.crc32(key.encode("utf-8")) % 10000


def unified_tag(node: dict[str, Any], provider: str, number: int) -> str:
    """Build ``🇩🇪DE Example gRPC-R 4821`` / ``🇩🇪DE Example VPN WL WS 0937``.

    Nodes without a country flag keep their original tag so hand-written names
    such as ``📱 Белые списки 1`` survive.
    """
    tag = node.get("tag", "")
    flag, code = split_flag(tag)
    if not flag:
        return tag
    marker = " WL" if _WHITELIST.search(tag) else ""
    return f"{flag}{code} {provider}{marker} {transport_label(node)} {number:04d}"


def apply_naming(nodes: list[dict[str, Any]], provider: str) -> list[dict[str, Any]]:
    """Rename nodes in place; identifiers are stable across subscription refreshes."""
    used: set[str] = set()
    for node in nodes:
        flag, _ = split_flag(node.get("tag", ""))
        if not flag:
            used.add(node.get("tag", ""))
            continue
        number = stable_id(node)
        candidate = unified_tag(node, provider, number)
        guard = 0
        while candidate in used and guard < 10000:
            number = (number + 1) % 10000
            candidate = unified_tag(node, provider, number)
            guard += 1
        used.add(candidate)
        node["tag"] = candidate
        if node.get("type") in {"wireguard", "warp"}:
            node["name"] = candidate
    return nodes
