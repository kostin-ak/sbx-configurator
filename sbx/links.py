"""Share-link parsers producing native sing-box outbound objects."""

from __future__ import annotations

import base64
import json
import urllib.parse
from typing import Any


class LinkError(ValueError):
    pass


def decode_base64_payload(content: str) -> str:
    content = content.strip()
    if "://" in content:
        return content
    padding = "=" * (-len(content) % 4)
    return base64.urlsafe_b64decode(content + padding).decode("utf-8", errors="ignore")


def _query(params: urllib.parse.ParseResult, name: str, default: str = "") -> str:
    return params.get(name, [default])[0]


def _xhttp_extra(query: dict[str, list[str]]) -> dict[str, Any]:
    """Decode the base64 ``extra`` JSON Xray puts XHTTP tuning into."""
    raw = _query(query, "extra")
    if not raw:
        return {}
    try:
        decoded = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8", "ignore")
        data = json.loads(decoded)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _xhttp_transport(query: dict[str, list[str]]) -> dict[str, Any]:
    """Build an XHTTP transport.

    The fork rejects the whole config unless ``x_padding_bytes`` is a non-zero
    range, and no known subscription emits it, so fall back to the Xray default.
    """
    extra = _xhttp_extra(query)
    # Xray clients accept the range both as a direct query key and inside `extra`.
    padding = _query(query, "xPaddingBytes") or extra.get("xPaddingBytes")
    transport: dict[str, Any] = {
        "type": "xhttp",
        "path": _query(query, "path", "/"),
        "host": _query(query, "host"),
        "mode": _query(query, "mode", "auto"),
        "x_padding_bytes": padding if isinstance(padding, str) and padding else "100-1000",
    }
    if extra.get("noGRPCHeader") is True:
        transport["no_grpc_header"] = True
    xmux = extra.get("xmux")
    if isinstance(xmux, dict):
        mapped = {
            "max_connections": xmux.get("maxConnections"),
            "max_concurrency": xmux.get("maxConcurrency"),
            "c_max_reuse_times": xmux.get("cMaxReuseTimes"),
            "h_max_request_times": xmux.get("hMaxRequestTimes"),
            "h_max_reusable_secs": xmux.get("hMaxReusableSecs"),
        }
        xmux_payload = {key: value for key, value in mapped.items() if isinstance(value, str) and value}
        if xmux_payload:
            transport["xmux"] = xmux_payload
    for source, target in (
        ("scMaxEachPostBytes", "sc_max_each_post_bytes"),
        ("scMinPostsIntervalMs", "sc_min_posts_interval_ms"),
        ("scStreamUpServerSecs", "sc_stream_up_server_secs"),
    ):
        value = extra.get(source)
        if isinstance(value, str) and value:
            transport[target] = value
    return transport


def _websocket_transport(query: dict[str, list[str]], transport_type: str) -> dict[str, Any]:
    """Build a WS/HTTPUpgrade transport.

    An empty ``Host`` header makes upstream fronts answer 502, so it is omitted
    entirely and the dialer falls back to the server address, as Xray does.
    """
    transport: dict[str, Any] = {"type": transport_type, "path": _query(query, "path", "/")}
    host = _query(query, "host")
    if transport_type == "ws":
        if host:
            transport["headers"] = {"Host": host}
    else:
        transport["host"] = host
    return transport


def _host_port(netloc: str) -> tuple[str, int]:
    if "@" in netloc:
        netloc = netloc.rsplit("@", 1)[1]
    host, separator, port = netloc.rpartition(":")
    if not separator:
        raise LinkError(f"missing port in {netloc}")
    return host.strip("[]"), int(port)


def parse_vless_or_trojan(uri: str, protocol: str) -> dict[str, Any]:
    parsed = urllib.parse.urlsplit(uri)
    if not parsed.hostname or not parsed.port:
        raise LinkError(f"invalid {protocol} endpoint")
    user = urllib.parse.unquote(parsed.username or "")
    outbound: dict[str, Any] = {
        "type": protocol,
        "tag": urllib.parse.unquote(parsed.fragment) or f"{protocol}-proxy",
        "server": parsed.hostname,
        "server_port": parsed.port,
    }
    query = urllib.parse.parse_qs(parsed.query)
    if protocol == "vless":
        outbound.update({"uuid": user, "flow": _query(query, "flow"), "packet_encoding": "xudp"})
        encryption = _query(query, "encryption")
        if encryption and encryption != "none":
            outbound["encryption"] = encryption
    else:
        outbound["password"] = urllib.parse.unquote(user)

    security = _query(query, "security")
    if security in {"tls", "reality"}:
        tls = {"enabled": True, "server_name": _query(query, "sni")}
        insecure = _query(query, "allowInsecure")
        if insecure:
            tls["insecure"] = insecure == "1"
        alpn = _query(query, "alpn")
        if alpn:
            tls["alpn"] = alpn.split(",")
        if security == "reality":
            tls["reality"] = {"enabled": True, "public_key": _query(query, "pbk"), "short_id": _query(query, "sid")}
        fingerprint = _query(query, "fp")
        if fingerprint:
            tls["utls"] = {"enabled": True, "fingerprint": fingerprint}
        outbound["tls"] = tls

    transport_type = _query(query, "type", "tcp")
    if transport_type == "ws":
        outbound["transport"] = _websocket_transport(query, "ws")
    elif transport_type == "grpc":
        outbound["transport"] = {"type": "grpc", "service_name": _query(query, "serviceName")}
    elif transport_type == "xhttp":
        outbound["transport"] = _xhttp_transport(query)
    elif transport_type == "httpupgrade":
        outbound["transport"] = _websocket_transport(query, "httpupgrade")
    return outbound


def parse_vmess(uri: str) -> dict[str, Any]:
    payload = json.loads(decode_base64_payload(uri.removeprefix("vmess://")))
    outbound: dict[str, Any] = {
        "type": "vmess",
        "tag": payload.get("ps", "vmess-proxy"),
        "server": payload.get("add", ""),
        "server_port": int(payload.get("port", 443)),
        "uuid": payload.get("id", ""),
        "security": "auto",
        "packet_encoding": "xudp",
    }
    if payload.get("tls") == "tls":
        outbound["tls"] = {"enabled": True, "server_name": payload.get("sni", payload.get("host", "")), "insecure": True}
    if payload.get("net") == "ws":
        outbound["transport"] = {"type": "ws", "path": payload.get("path", "/"), "headers": {"Host": payload.get("host", "")}}
    elif payload.get("net") == "grpc":
        outbound["transport"] = {"type": "grpc", "service_name": payload.get("path", "")}
    return outbound


def parse_shadowsocks(uri: str) -> dict[str, Any]:
    parsed = urllib.parse.urlsplit(uri)
    tag = urllib.parse.unquote(parsed.fragment) or "ss-proxy"
    if "@" in parsed.netloc:
        encoded, endpoint = parsed.netloc.rsplit("@", 1)
        method_password = decode_base64_payload(encoded)
    else:
        decoded = decode_base64_payload(parsed.netloc)
        method_password, endpoint = decoded.split("@", 1)
    method, password = method_password.split(":", 1)
    server, separator, port = endpoint.rpartition(":")
    if not separator:
        raise LinkError(f"invalid shadowsocks endpoint: {endpoint}")
    return {
        "type": "shadowsocks",
        "tag": tag,
        "server": server.strip("[]"),
        "server_port": int(port),
        "method": method,
        "password": password,
    }


def parse_hysteria2(uri: str) -> dict[str, Any]:
    parsed = urllib.parse.urlsplit(uri)
    if not parsed.hostname:
        raise LinkError("invalid hysteria2 endpoint")
    query = urllib.parse.parse_qs(parsed.query)
    password = urllib.parse.unquote(parsed.username or "")
    if parsed.password:
        password = f"{password}:{urllib.parse.unquote(parsed.password)}"
    outbound: dict[str, Any] = {
        "type": "hysteria2",
        "tag": urllib.parse.unquote(parsed.fragment) or "hysteria2-proxy",
        "server": parsed.hostname,
        "server_port": parsed.port or 443,
        "password": password,
    }
    obfs = _query(query, "obfs")
    if obfs:
        outbound["obfs"] = {"type": obfs, "password": _query(query, "obfs-password")}
    tls: dict[str, Any] = {
        "enabled": True,
        "server_name": _query(query, "sni") or parsed.hostname,
    }
    if _query(query, "insecure") in {"1", "true"} or _query(query, "allowInsecure") in {"1", "true"}:
        tls["insecure"] = True
    pin = _query(query, "pinSHA256")
    if pin:
        tls["certificate_public_key_sha256"] = [pin]
    alpn = _query(query, "alpn")
    if alpn:
        tls["alpn"] = alpn.split(",")
    outbound["tls"] = tls
    up = _query(query, "up") or _query(query, "upmbps")
    down = _query(query, "down") or _query(query, "downmbps")
    if up.isdigit():
        outbound["up_mbps"] = int(up)
    if down.isdigit():
        outbound["down_mbps"] = int(down)
    return outbound


def parse_link(uri: str) -> dict[str, Any] | None:
    text = uri.strip()
    if text.startswith("vless://"):
        return parse_vless_or_trojan(text, "vless")
    if text.startswith("trojan://"):
        return parse_vless_or_trojan(text, "trojan")
    if text.startswith("vmess://"):
        return parse_vmess(text)
    if text.startswith("ss://"):
        return parse_shadowsocks(text)
    if text.startswith("hysteria2://") or text.startswith("hy2://"):
        return parse_hysteria2(text)
    if text.startswith("block://"):
        return {"type": "block", "tag": text.removeprefix("block://").strip()}
    if text.startswith("direct://"):
        return {"type": "direct", "tag": text.removeprefix("direct://").strip()}
    return None
