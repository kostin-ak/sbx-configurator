# Releases and packs

## Source pack

```bash
.venv/bin/python tools/make_release.py --version 0.3.0
.venv/bin/python tools/audit_release.py artifacts/sbx-0.3.0.sbxpack
```

The builder:

1. copies only sources (`sbx`, `tools`, `tests`, `config`, `protocols`, `docs`,
   `router`, README, LICENSE);
2. skips secrets, caches, binaries and runtime state;
3. adds `release.json`;
4. writes a ZIP with a per-file manifest;
5. verifies every SHA-256;
6. extracts the pack again and runs the unit tests;
7. runs `sing-box check` against `config/protocol-check.json`.

`audit_release.py` fails if the pack contains secrets, subscription caches,
binaries or logs.

## Versioning

`0.<minor>.<patch>`. The router keeps every release under
`/data/sbx/releases/<version>` and switches a single `current` symlink, so a
rollback is instant:

```sh
/root/sbxctl releases
/root/sbxctl rollback 0.1.0
```

## Artifact

Each build writes:

```text
build/artifacts/config.json
build/artifacts/config.json.manifest.json
build/artifacts/diff.json
```

`config.json.prev` is kept for the automatic rollback performed by
`sbxctl apply`.

## Fork binary

The binary is not part of any pack. Download the version pinned in
`docs/ARCHITECTURE.md` with:

```bash
python tools/fetch_singbox.py --arch linux-amd64   # or linux-mipsle-softfloat
```

The script checks the SHA-256 published by the fork release.