# sbx-configurator

Declarative pipeline that turns subscription links and raw configs into a
validated [sing-box](https://sing-box.sagernet.org/) configuration for an
OpenWrt router, without ever touching the running service until you ask.

The project was built around
[shtorm-7/sing-box-extended](https://github.com/shtorm-7/sing-box-extended) and
its extra protocols (XHTTP, VLESS encryption, AmneziaWG, Hysteria2, …), but the
pipeline itself is a plain Python package with no runtime dependency on the
router.

## Why

Hand-editing a 1000+ node config is error-prone: one unsupported field and the
whole service refuses to start. This project separates the moving parts:

```text
subscriptions / folders ─┐
transforms + naming      ├─► merge ─► validate ─► sing-box check ─► artifact
static router parts     ─┘                                      └─► isolated runtime test
```

- **Declarative sources** — one YAML per provider, share links, or folders with
  ready-made `*.conf` files.
- **Deterministic names** — `🇩🇪DE Provider gRPC-R 4821`, stable across
  subscription refreshes, so a Clash UI selection keeps pointing at the same
  server.
- **Fail-safe builds** — structural validation, cycle detection, `sing-box
  check` and an isolated proxy-only run. A broken candidate never replaces a
  working config.
- **Immutable releases on the router** — `/data/sbx/releases/<version>` plus a
  `current` symlink and a single `sbxctl` entry point.
- **No secrets in Git** — `snapshot/`, `state/`, `keys/`, `config/secrets/` and
  build outputs are ignored; release packs are audited for leaks.

## Requirements

- Python 3.11+
- `sing-box-extended` binary for your platform in `bin/sing-box-extended`
  (nothing is bundled: the fork is licensed separately)
- For deployment: an OpenWrt router with SSH and ~120 MB free RAM

## Quick start

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev,router]"

# demo configuration with example.com nodes
cp -r examples/snapshot snapshot
cp examples/local.example.yaml config/secrets/local.yaml
tools/check_local.sh

# generated config
build/artifacts/config.json
```

Replace the demo subscription with your own:

```yaml
# config/subscriptions.d/20-provider.yaml
apiVersion: sbx.shtorm/1
kind: Subscription
metadata:
  name: Provider
  enabled: true
fetch:
  url: ${secret:subscriptions.provider.url}
transforms:
- action: rename
  pattern: ([🇦-🇿]{2})
  replacement: '\1 [P] '
naming:
  enabled: true
selectors:
  global: true
  local: []
```

```yaml
# config/secrets/local.yaml
subscriptions:
  provider:
    url: https://example.com/subscription
```

Then `python -m sbx.cli build --check`.

## Repository layout

```text
sbx/                 pipeline, parsers, validators (Python package)
config/
  pipeline.yaml      pipeline settings
  subscriptions.d/   one YAML per source
  routing/           devices, groups, categories, policies, rule-sets
  selectors.yaml     selector templates
  protocols.d/       native protocols and endpoints
  rules/             local SRS sources
  protocol-check.json  native protocol smoke config
protocols/           declarative registry of native protocol fields
router/              sbxctl and the procd init script
tools/               release, snapshot, audit and probe helpers
tests/               unit tests (no network required)
examples/            demo snapshot, keys, links and secrets template
docs/                architecture, configuration, deployment, testing
```

## Configuration at a glance

- **Subscriptions** — `fetch.url`, `fetch.file` or `fetch.folder` with
  `parser: wireguard-conf | share-links`.
- **Transforms** — `rename`, `exclude`, `patch`, `random_patch` applied per
  subscription before assembly.
- **Naming** — optional and off by default: template mode with regex fields,
  or a plain regex rename. See [docs/NAMING.md](docs/NAMING.md).
- **Routing** — devices, groups, categories and per-device policies under
  `config/routing/`.
- **Selectors** — templates in `config/selectors.yaml`, plus per-subscription
  local selectors with `filter`, `prefer` and `expand: all`.

See [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for the full schema, and
[docs/FOLDER_SOURCES.md](docs/FOLDER_SOURCES.md) for WireGuard/AmneziaWG and raw
link folders.

## CLI

```bash
python -m sbx.cli build --check          # build + validate + sing-box check
python -m sbx.cli check --config FILE    # checks only
python -m sbx.cli srs                    # compile SRS rule-sets only
python -m sbx.cli proxy-only ...         # isolated runtime without TUN
python -m sbx.cli pack / unpack ...      # release archives
```

On the router the same stages are available through `/root/sbxctl`:
`status`, `fetch`, `sync`, `srs`, `build`, `check`, `apply`, `refresh`,
`restart`, `rollback`, `releases`, `probe`, `logs`, `backup`.

## Router deployment

```bash
.venv/bin/python tools/make_release.py --version 0.2.0
.venv/bin/python tools/audit_release.py artifacts/sbx-0.2.0.sbxpack
ROUTER_HOST=<router> ROUTER_PASSWORD=<password> \
  .venv/bin/python tools/upgrade_router_release.py --version 0.2.0
ssh root@<router> /root/sbxctl apply --no-build
```

Do not build on a small MIPS router: parsing 1000+ nodes and merging JSON keeps
the CPU busy for minutes and can reboot the device. Build on a workstation and
push the artifact instead:

```bash
ROUTER_HOST=<router> ROUTER_PASSWORD=<password> \
  .venv/bin/python tools/push_artifact.py --artifact build/artifacts/config.json
```

`apply` restarts the service, waits for 7890/9090 and restores the previous
artifact if the new one does not start. Details:
[docs/ROUTER_DEPLOYMENT.md](docs/ROUTER_DEPLOYMENT.md).

## Security

- Secrets live only in `config/secrets/local.yaml`, `snapshot/`, `state/` and
  `keys/`; all of them are ignored by Git.
- `tools/audit_release.py` verifies that a `.sbxpack` contains no secrets,
  caches or binaries.
- `tests/test_release.py` checks that release packs stay source-only.
- Router credentials are read from `ROUTER_PASSWORD`, never stored.

See [docs/SECURITY.md](docs/SECURITY.md) and [SECURITY.md](SECURITY.md).

## Compatibility

Validated against `sing-box-extended 1.14.3-extended-2.7.3`. The fork is
required for protocols such as XHTTP, `vless` encryption, AmneziaWG endpoints
and `trusttunnel`; a stock sing-box will reject those configs.

## Limitations

- The pipeline optimises for a single router and a static set of providers; it is
  not a control panel.
- Some ISPs drop WireGuard UDP to non-standard ports. The docs explain how to
  detect it and how to route the handshake through an allowed outbound.
- `in-mixed` (127.0.0.1:7890) is intentionally routed `direct`.

## License

MIT — see [LICENSE](LICENSE).
