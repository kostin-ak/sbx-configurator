# Security policy

## Reporting

Open a private security advisory on GitHub (Security → Advisories) instead of a
public issue if you find a leak or a vulnerability. Please include the affected
file or command and, if possible, a minimal reproduction.

## What must never be committed

- subscription URLs and tokens;
- WireGuard/AmneziaWG private keys, `*.conf` files from providers;
- router snapshots (`snapshot/`) and runtime state (`state/`);
- generated configs (`build/`) and release archives (`artifacts/`);
- router credentials (`ROUTER_PASSWORD` is read from the environment).

These paths are covered by `.gitignore`. Before publishing a fork, run:

```bash
git status --ignored --short
tools/audit_release.py artifacts/<release>.sbxpack
```

## Secrets at runtime

The pipeline reads `config/secrets/local.yaml` and substitutes `${secret:...}`
references. Values are never written to logs, artifacts or release packs. The
router keeps private material under `/data/sbx/keys` (mode `700`) and
`/data/sbx/state` (caches).

## Supported versions

Only the latest release receives fixes.