# Tests and checks

## Requirements

- Python 3.11+;
- the fork binary in `bin/sing-box-extended` for binary checks;
- a `snapshot/` with static parts and `config/secrets/local.yaml` for a full
  build (the demo copies are enough).

```bash
cp -r examples/snapshot snapshot
cp examples/local.example.yaml config/secrets/local.yaml
tools/check_local.sh
```

The script runs the unit tests and, when the binary, snapshot and secrets are
present, a full build with `--check`. Missing pieces are reported and the build
is skipped, so a fresh clone can always run the tests.

## Unit tests

```bash
PYTHONPATH=. python -m unittest discover -s tests -v
```

Covered: link parsing (VLESS/VLESS encryption/XHTTP/Hysteria2), WireGuard and
AmneziaWG conf parsing, folder sources, naming, transforms, routing, selector
generation, cycle detection, release packs, activation/rollback, proxy-only
mode and offline rule-set stubs.

Tests that need a real snapshot or real secrets are skipped explicitly.

## Binary checks

```bash
bin/sing-box-extended check -c build/artifacts/config.json -D state/local
bin/sing-box-extended check -c config/protocol-check.json -D state/protocol-check
```

The second file exercises every native protocol supported by the fork; it uses
dummy endpoints and never connects anywhere.

## Configuration lint

```bash
python -m sbx.cli lint
```

Checks cross-references the schema cannot see: category rule-sets, policy
categories and aliases, group members, duplicate device addresses, selector and
transform regexes. Exit code 1 means there is at least one error.

## Proxy-only runtime

```bash
tools/runtime_proxy_test.sh
```

Builds a config without TUN and DNS hijacking, compiles offline rule-set stubs,
starts an isolated sing-box on 7891/9091, performs an HTTP request through it and
stops the process. No internet access is required.

## Reproducibility

With the same sources and caches the artifact must be byte-identical:

```bash
sha256sum build/artifacts/config.json
python -m sbx.cli build --check
sha256sum build/artifacts/config.json
```

The artifact is affected by changed subscription caches, rule sources, YAML
files and the fork version. `config.json.manifest.json` stores the hash and build
statistics.

## Comparing configs

```bash
python tools/compare_configs.py OLD.json NEW.json
```

Prints semantic changes (types, tags, selectors, DNS servers, route counts).
Secret fields are masked.

## Release checks

```bash
python tools/make_release.py --version 0.2.0
python tools/audit_release.py artifacts/sbx-0.2.0.sbxpack
```

The builder verifies the pack, extracts it again and runs the unit tests; the
auditor fails if the pack contains secrets, caches or binaries.

## Node probes

```bash
python tools/probe_folder.py --folder keys/awg3 --binary bin/sing-box-extended
```

Starts one temporary process per endpoint and measures latency. On the router the
same is available as `sbxctl probe awg3`.
