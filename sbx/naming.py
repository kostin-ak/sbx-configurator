"""Optional, configurable outbound naming.

The pipeline never invents names unless a subscription asks for it. Two modes are
supported:

* ``template`` — build a name from fields (flag, provider, transport, regex
  captures, a counter or a stable id);
* ``regex`` — a plain regular-expression substitution, i.e. the classic rename
  transform, applied as a final naming step.

Set ``enabled: false`` (or omit the block) to keep whatever the ``transforms``
produced.
"""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass, field
from typing import Any, Pattern

_FLAG_PAIR = re.compile("([\U0001F1E6-\U0001F1FF])([\U0001F1E6-\U0001F1FF])")
_FLAG_BASE = 0x1F1E6
_BRACKETS = re.compile(r"\[[^\]]*\]")

_TRANSPORTS = {
    "tcp": "TCP",
    "ws": "WS",
    "grpc": "gRPC",
    "xhttp": "XHTTP",
    "httpupgrade": "HTTPU",
    "quic": "QUIC",
    "kcp": "mKCP",
}

DEFAULT_TEMPLATE = "{flag}{cc} {provider}{marker} {transport}{reality} {index:02d}"
DEFAULT_MARKER_PATTERN = r"\bWL\b|Whitelist|Обход"


@dataclass
class NamingSpec:
    enabled: bool = False
    mode: str = "template"
    template: str = DEFAULT_TEMPLATE
    fallback_template: str = ""
    fields: dict[str, str] = field(default_factory=dict)
    marker: str = " WL"
    marker_pattern: str = DEFAULT_MARKER_PATTERN
    strip_pattern: str = ""
    max_length: int = 48
    unique: bool = True
    index: str = "sequence"
    pattern: str = ""
    replacement: str = ""

    @classmethod
    def from_config(cls, config: dict[str, Any] | None) -> "NamingSpec":
        if not config:
            return cls()
        spec = cls()
        spec.enabled = bool(config.get("enabled", False))
        spec.mode = str(config.get("mode", "template")).lower()
        spec.template = str(config.get("template", DEFAULT_TEMPLATE))
        spec.fallback_template = str(config.get("fallback_template", ""))
        fields = config.get("fields") or {}
        if isinstance(fields, dict):
            spec.fields = {str(key): str(value) for key, value in fields.items()}
        spec.marker = str(config.get("marker", " WL"))
        spec.marker_pattern = str(config.get("marker_pattern", DEFAULT_MARKER_PATTERN))
        spec.strip_pattern = str(config.get("strip_pattern", ""))
        spec.max_length = int(config.get("max_length", 48))
        spec.unique = bool(config.get("unique", True))
        spec.index = str(config.get("index", "sequence")).lower()
        spec.pattern = str(config.get("pattern", ""))
        spec.replacement = str(config.get("replacement", ""))
        return spec


def split_flag(tag: str) -> tuple[str, str]:
    """Return (flag emoji, ISO country code) found in the tag, or ('', '')."""
    match = _FLAG_PAIR.search(tag)
    if not match:
        return "", ""
    code = "".join(chr(ord(character) - _FLAG_BASE + ord("A")) for character in match.groups())
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
    return _TRANSPORTS.get(transport, transport.upper())


def stable_id(node: dict[str, Any]) -> int:
    """Stable numeric suffix derived from the server address."""
    if node.get("type") in {"wireguard", "warp"}:
        peers = node.get("peers") or [{}]
        key = f"{peers[0].get('address', '')}:{peers[0].get('port', '')}"
    else:
        key = f"{node.get('server', '')}:{node.get('server_port', '')}"
    return zlib.crc32(key.encode("utf-8")) % 10000


def _field_value(pattern: Pattern[str], tag: str) -> str | None:
    match = pattern.search(tag)
    if not match:
        return None
    if "value" in match.groupdict():
        return match.group("value")
    if match.groups():
        return match.group(1)
    return match.group(0)


def _compile(pattern: str) -> Pattern[str] | None:
    if not pattern:
        return None
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error:
        return None


def _format(template: str, values: dict[str, Any]) -> str | None:
    try:
        return template.format(**values)
    except (KeyError, IndexError, ValueError):
        return None


def apply_naming(
    nodes: list[dict[str, Any]],
    provider: str,
    config: dict[str, Any] | NamingSpec | None = None,
) -> list[dict[str, Any]]:
    """Rename nodes according to ``config``; no-op when disabled."""

    spec = config if isinstance(config, NamingSpec) else NamingSpec.from_config(config)
    if not spec.enabled:
        return nodes

    if spec.mode == "regex":
        pattern = _compile(spec.pattern)
        if pattern is None:
            return nodes
        for node in nodes:
            tag = node.get("tag", "")
            node["tag"] = pattern.sub(spec.replacement, tag)
            if node.get("type") in {"wireguard", "warp"}:
                node["name"] = node["tag"]
        return nodes

    marker_pattern = _compile(spec.marker_pattern)
    strip_pattern = _compile(spec.strip_pattern)
    field_patterns = {name: _compile(pattern) for name, pattern in spec.fields.items()}

    counters: dict[str, int] = {}
    used: set[str] = set()

    for node in nodes:
        original = node.get("tag", "")
        tag = strip_pattern.sub("", original) if strip_pattern else original
        flag, code = split_flag(tag)
        if not flag:
            used.add(original)
            continue

        key = code
        counters[key] = counters.get(key, 0) + 1
        sequence = counters[key]
        if spec.index == "stable":
            number = stable_id(node) or sequence
        elif spec.index == "none":
            number = 0
        else:
            number = sequence

        values: dict[str, Any] = {
            "flag": flag,
            "cc": code,
            "provider": provider,
            "transport": transport_label(node),
            "reality": "-R" if (node.get("tls") or {}).get("reality") else "",
            "security": "reality" if (node.get("tls") or {}).get("reality") else ("tls" if (node.get("tls") or {}).get("enabled") else "none"),
            "index": number,
            "stable": stable_id(node),
            "name": _BRACKETS.sub("", tag).strip(),
            "marker": spec.marker if marker_pattern and marker_pattern.search(original) else "",
        }

        missing = False
        for name, pattern in field_patterns.items():
            value = _field_value(pattern, original) if pattern else None
            if value is None:
                missing = True
            values[name] = value

        candidate = None
        if not missing:
            candidate = _format(spec.template, values)
        if (candidate is None or not candidate.strip()) and spec.fallback_template:
            candidate = _format(spec.fallback_template, values)
        if candidate is None:
            candidate = _BRACKETS.sub("", tag).strip() or original
        candidate = " ".join(candidate.split())
        if spec.max_length and len(candidate) > spec.max_length:
            candidate = candidate[: spec.max_length].rstrip()

        if spec.unique:
            base = candidate
            suffix = 2
            while candidate in used:
                candidate = f"{base} ({suffix})"
                suffix += 1
        used.add(candidate)
        node["tag"] = candidate
        if node.get("type") in {"wireguard", "warp"}:
            node["name"] = candidate

    return nodes


# Backwards-compatible helper for tests and simple templates.
def unified_tag(node: dict[str, Any], provider: str, number: int) -> str:
    spec = NamingSpec(enabled=True)
    values = {
        "flag": split_flag(node.get("tag", ""))[0],
        "cc": split_flag(node.get("tag", ""))[1],
        "provider": provider,
        "transport": transport_label(node),
        "reality": "-R" if (node.get("tls") or {}).get("reality") else "",
        "security": "reality" if (node.get("tls") or {}).get("reality") else "none",
        "index": number,
        "stable": number,
        "name": node.get("tag", ""),
        "marker": spec.marker if re.search(DEFAULT_MARKER_PATTERN, node.get("tag", ""), re.IGNORECASE) else "",
    }
    return spec.template.format(**values)