# Troubleshooting

## `x_padding_bytes cannot be disabled`

The fork refuses to decode an XHTTP transport without a non-zero
`x_padding_bytes` range. The parser always emits `100-1000` when the link has no
padding, but a hand-written protocol file can still miss it:

```json
"transport": {"type": "xhttp", "path": "/", "x_padding_bytes": "100-1000"}
```

## WebSocket nodes answer `502`

An empty `Host` header makes the front return 502. The parser omits the header
when the link has no `host` parameter; do the same in hand-written configs:

```json
"transport": {"type": "ws", "path": "/ws"}
```

## `circular outbound dependency`

A selector contains an endpoint that detours back into the same selector (for
example `detour: 🚀 Proxy [Default]` while the endpoint is a member of that
group). `sing-box check` does not catch it, but the service fails at startup.
`sbx/validate.py` rejects such a build. Point `detour` at a group that does not
contain the endpoint.

## `post-start endpoint: context canceled`

A WireGuard endpoint binds during startup. If the node selected in its `detour`
group is dead, the whole service fails. Keep the bridge's first member alive;
`sbxctl apply` restores the previous artifact when the service does not come up.

## Direct WireGuard/AmneziaWG handshake never completes

Check the UDP path first, with a socket bound to the WAN interface so the TUN
does not interfere:

```python
import socket
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, 25, b"wan\x00")   # SO_BINDTODEVICE
sock.settimeout(5)
sock.sendto(b"\x00" * 64, ("1.1.1.1", 44553))
```

If DNS (53), NTP (123) and QUIC (443) answer but the WG port stays silent, the
ISP filters UDP by port. Use an endpoint on an allowed port or wrap the
handshake with `detour` (see [FOLDER_SOURCES.md](FOLDER_SOURCES.md)).

## DNS resolves but sites do not open

`route.default_domain_resolver` should point to a plain resolver (UDP), not to a
DoH endpoint that may be blocked. Outbound server domains must be resolved
locally; user domains can still use DoH via `dns.final`.

## A node works in another client but not here

Compare the parsed outbound with the source link (`tools/compare_configs.py`,
`tools/audit_links.py`). Common causes: an empty WebSocket `Host`, a missing
`insecure` flag for self-signed certificates, or a fingerprint that the server
rejects.

## The service does not start after an update

```sh
/root/sbxctl status
/root/sbxctl logs 80
/root/sbxctl rollback
```

`rollback` switches `current` to the previous release and restarts the service.
The previous artifact is also kept as `build/artifacts/config.json.prev`.

## `FATAL start service: context canceled`

Usually a side effect of stopping an isolated test process, not a real error.
Look at the lines before it: the actual failure is the first `ERROR` in the log.

## Rule-set download failures

Remote rule-sets are compiled into SRS files during the build. Use
`sbxctl srs` to rebuild them separately, or `proxy-only --offline-rule-sets` for
tests that must not touch the network.