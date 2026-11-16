# Naming

Naming is **optional**. Without a `naming` block the tag stays exactly as the
`transforms` produced it, including the classic regex renames.

```yaml
naming:
  enabled: false
```

## Template mode

Builds a name from fields:

```yaml
naming:
  enabled: true
  template: "{flag}{cc} {provider}{marker} {transport}{reality} {index:02d}"
```

Result: `🇩🇪DE Provider gRPC-R 03`, `🇩🇪DE Provider WL WS 07`.

Fields:

| Field | Meaning |
|---|---|
| `{flag}` | leading flag emoji from the original tag |
| `{cc}` | ISO code derived from the flag (`DE`, `NL`, …) |
| `{provider}` | subscription `metadata.name` |
| `{transport}` | `TCP`, `WS`, `gRPC`, `XHTTP`, `HY2`, `AWG`, `WG` |
| `{reality}` | `-R` when the node uses Reality, otherwise empty |
| `{security}` | `reality`, `tls` or `none` |
| `{index}` | counter or stable id (see `index`) |
| `{stable}` | `crc32(server:port) % 10000` |
| `{name}` | original tag with `strip_pattern` applied and `[...]` removed |
| `{marker}` | `marker` text when the tag matches `marker_pattern` |

`index` chooses the numeric suffix:

- `sequence` (default) — 01, 02, … per provider and country; readable, but
  numbers shift when the provider adds or removes nodes;
- `stable` — `crc32(server:port)`; survives refreshes, less readable;
- `none` — no number (duplicates get `(2)` when `unique` is on).

`marker_pattern` defaults to `WL|Whitelist|Обход`; `marker` defaults to `" WL"`.
Use `marker: ""` to drop the marker entirely.

## Keep the provider's own number

Providers often already have a stable, human-readable number (`V2`, `V19`).
Extract it with a regex field:

```yaml
naming:
  enabled: true
  template: "{flag}{cc} {provider} {transport} {num}"
  fallback_template: "{flag}{cc} {provider} {transport} {index:02d}"
  fields:
    num: 'V(\d+)'
```

When `num` does not match, the `fallback_template` is used. Any regex works; a
named group `(?P<value>…)` is preferred, otherwise the first group is taken.

## Regex mode

If you only need the old "rename with a regular expression" behaviour as a final
step:

```yaml
naming:
  enabled: true
  mode: regex
  pattern: '\s*\[[^\]]*\]\s*'
  replacement: ' '
```

This is equivalent to a `rename` transform, but applied after all other
transforms.

## Extra options

```yaml
naming:
  enabled: true
  strip_pattern: '^\s*\[[^\]]*\]\s*'   # remove prefixes before parsing fields
  max_length: 48                        # truncate long titles
  unique: true                          # add " (2)" on duplicates
```

## Notes

- Naming runs after `transforms` and applies to outbounds and endpoints.
- Nodes without a country flag keep their name; that keeps hand-written names
  such as `📱 Home` intact.
- `stable` index and regex `num` keep a Clash UI selection pointing at the same
  server after a refresh; `sequence` does not.