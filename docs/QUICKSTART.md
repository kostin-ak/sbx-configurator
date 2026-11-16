# Quick start

Everything runs from a checkout; nothing is installed system-wide. The workflow
is: describe sources in YAML → build a sing-box config → validate it → deploy a
release to the router.

## Requirements

- Python 3.11+ (the project is developed in WSL2 with Arch Linux);
- a `sing-box-extended` binary for your architecture (`bin/sing-box-extended`);
- for router work: SSH access and an OpenWrt device with enough RAM (~120 MB
  free for a 1300-node config).

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev,router]"
```

Download the matching fork binary with `tools/fetch_singbox.py` or put it into
`bin/sing-box-extended` manually. The binary is ignored by Git.

## Demo build

The repository ships a minimal example so you can try the pipeline without any
real provider:

```bash
cp -r examples/snapshot snapshot
cp examples/secrets/local.example.yaml config/secrets/local.yaml
tools/check_local.sh
```

`examples/snapshot` contains a minimal set of static config parts (inbounds, DNS,
log/API) and two demo files with `example.com` links. The build writes:

```text
build/artifacts/config.json           # the generated config
build/artifacts/config.json.manifest.json
build/artifacts/diff.json             # semantic diff against the previous build
```

## Your own sources

1. Copy `config/secrets/local.example.yaml` to `config/secrets/local.yaml` and
   add your subscription URLs.
2. Add one YAML per provider to `config/subscriptions.d/`:

```yaml
apiVersion: sbx.shtorm/1
kind: Subscription
metadata:
  name: Provider
  enabled: true
fetch:
  url: ${secret:subscriptions.provider.url}
  cache:
    enabled: true
    on_error: use_stale
naming:
  enabled: true
selectors:
  global: true
  local: []
```

3. Capture the router's static parts (`inbounds`, `dns`, `experimental`) with
   `tools/router_snapshot.py --host <router>` into `snapshot/`, or keep using
   the example set.

## Build and check

```bash
.venv/bin/python -m sbx.cli build --check
.venv/bin/python -m sbx.cli check --config build/artifacts/config.json
.venv/bin/python -m sbx.cli lint
```

`--check` runs the structural validator and `sing-box check`. A build that fails
these steps never replaces the previous artifact.

`lint` проверяет перекрёстные ссылки: категории → rule-sets, политики →
категории/устройства, участники групп, дубли адресов и регулярки в селекторах
и transforms.

## Try it without the router TUN

`proxy-only` turns the artifact into a plain local proxy on 7891/9091 with
remote rule-sets stubbed offline:

```bash
.venv/bin/python -m sbx.cli proxy-only \
  --config build/artifacts/config.json \
  --output build/proxy-only/config.json \
  --listen 127.0.0.1 --port 7891 --clash-port 9091 \
  --offline-rule-sets --compiler bin/sing-box-extended \
  --stub-dir state/rule-set-stubs
```

Then start it manually, point a browser or `curl` at `127.0.0.1:7891` and use the
Clash API on `9091` for latency tests. This never touches the running service.

## Deploy

See [ROUTER_DEPLOYMENT.md](ROUTER_DEPLOYMENT.md). Short version:

```bash
.venv/bin/python tools/make_release.py --version 0.2.0
.venv/bin/python tools/audit_release.py artifacts/sbx-0.2.0.sbxpack
ROUTER_HOST=<router> ROUTER_PASSWORD=<password> \
  .venv/bin/python tools/upgrade_router_release.py --version 0.2.0
ROUTER_HOST=<router> ROUTER_PASSWORD=<password> \
  .venv/bin/python tools/push_artifact.py --artifact build/artifacts/config.json --restart
```

The artifact is built on the workstation, uploaded with a SHA-256 check and
installed only if `sing-box check` accepts it. `--restart` activates it
immediately; the previous artifact is restored if the service does not come up.
