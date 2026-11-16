# Examples

Everything here is safe to publish: no real subscriptions, keys or tokens.

```text
snapshot/                 minimal static parts (inbounds, DNS, log/API)
snapshot/.../example_links.txt   demo share links (example.com)
snapshot/.../system_nodes.txt    block/direct nodes used by the System subscription
keys/awg3/example.conf    AmneziaWG config with dummy keys
keys/awg3/example.yaml    sidecar that sets tag/country/provider
keys/links/example.txt    a single Hysteria2 link
local.example.yaml        template for config/secrets/local.yaml
```

## Demo build

```bash
cp -r examples/snapshot snapshot
cp examples/local.example.yaml config/secrets/local.yaml
python -m sbx.cli build --check
```

The result contains six `Example` nodes and the `System` block/direct
outbounds. Nothing connects anywhere: all hosts are `example.com`.

## Real sources

- `config/subscriptions.d/10-example.yaml` — file-based subscription;
  replace it with your provider (`fetch.url`, see the README).
- `config/subscriptions.d/70-example-awg3.yaml` — folder of WireGuard /
  AmneziaWG configs (`enabled: false`).
- `config/subscriptions.d/71-example-links.yaml` — folder of share links
  (`enabled: false`).

Copy your own files into `keys/` (ignored by Git) and set the `keys.*` paths in
`config/secrets/local.yaml`. See [../docs/FOLDER_SOURCES.md](../docs/FOLDER_SOURCES.md).