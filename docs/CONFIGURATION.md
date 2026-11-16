# Конфигурация

## Обзор

Схема отделяет источники, transforms, routing, нативные протоколы и секреты.
Активный pipeline: `config/pipeline.yaml`.

Все пользовательские файлы конфигурации начинаются с:

```yaml
apiVersion: sbx.shtorm/1
kind: ...
```

Неподдерживаемый `kind` или `apiVersion` — ошибка сборки.

## Подписки

Один файл на провайдера в `config/subscriptions.d`.

Пример:

```yaml
apiVersion: sbx.shtorm/1
kind: Subscription
metadata:
  name: Example
  enabled: true
fetch:
  url: ${secret:subscriptions.example.url}
  cache:
    enabled: true
    on_error: use_stale
transforms:
  - action: rename
    pattern: "([\\U0001F1E6-\\U0001F1FF]{2})"
    replacement: "\\1 [Z]"
selectors:
  global: true
  local: []
```

Поля:

- `metadata.enabled` — включение без удаления файла;
- `fetch.url` или `fetch.file` — источник;
- `fetch.cache.enabled` — запись/использование кэша;
- `transforms` — последовательные правила над узлами;
- `selectors.global` — подключать общие шаблоны;
- `selectors.local` — локальные selectors.

## Selector templates

Общие шаблоны находятся в `config/selectors.yaml`.

```yaml
apiVersion: sbx.shtorm/1
kind: Selectors
templates:
  - name: proxy
    tag: "🚀 Proxy"
    type: selector
    filter: "^((?!\\[B\\]).)*$"
    regex: true
```

`filter` фильтрует узлы. `regex` управляет раскрытием имени selector по
базе тегов. Это разные механизмы.

Локальный `expand: all` используется для legacy-совместимого расширения по
всей selector database.

## Устройства и группы

`config/routing/devices.yaml`:

```yaml
apiVersion: sbx.shtorm/1
kind: Devices
devices:
  Laptop:
    ipv4: 192.168.1.10/32
```

`config/routing/groups.yaml`:

```yaml
apiVersion: sbx.shtorm/1
kind: Groups
groups:
  Personal:
    members: [Laptop, Phone, Tablet]
```

Имя ключа стабильно. IP-адрес можно менять, не затрагивая категории или
selector-логику.

## Категории маршрутизации

`config/routing/categories.yaml`:

```yaml
apiVersion: sbx.shtorm/1
kind: Categories
categories:
  - name: youtube
    display: "📺 YouTube"
    rules:
      - rule_set: [custom-youtube, geosite-youtube]
    disable_default: false
```

- `name` — стабильный программный идентификатор;
- `display` — отображаемый тег, сохраняющий совместимость;
- `rules` — шаблоны sing-box rules;
- `disable_default` — запрет автоматического `[Default]`.

## Политики

`config/routing/policies.yaml`:

```yaml
apiVersion: sbx.shtorm/1
kind: Policies
defaults:
  final: proxy
  catch_all: proxy
settings:
  auto_detect_interface: true
  default_domain_resolver: dns-local
policies:
  - alias: Laptop
    categories: [youtube, runet, ai, communication, proxy]
```

`catch_all` задаёт группу для всего, что не попало в правила.

`default_domain_resolver` намеренно указывает на `dns-local` (UDP): адреса
серверов подписок должны резолвиться через надёжный резолвер, а не через DoH,
который может быть недоступен. Имена узлов в подписках публичные и не требуют
DoH; для пользовательских доменов остаётся `dns.final: dns-cf`.

## Rule sets

`config/routing/rule-sets.yaml` содержит:

- `pre_rules`;
- `post_rules`;
- `rule_sets`.

Remote и local rule-set остаются нативными объектами sing-box.

## Нативные протоколы

Файлы `config/protocols.d` имеют `kind: Protocol`.

Пример Mieru:

```yaml
apiVersion: sbx.shtorm/1
kind: Protocol
metadata:
  name: mieru-main
  enabled: true
protocol:
  type: mieru
  section: outbounds
  tag: Mieru main
connection:
  server: mieru.example.com
  server_port: 27017
  transport: TCP
credentials:
  username: ${secret:mieru.username}
  password: ${secret:mieru.password}
options:
  multiplexing: MULTIPLEXING_LOW
  mtu: 1400
```

Пример WARP:

```yaml
apiVersion: sbx.shtorm/1
kind: Protocol
metadata:
  name: warp-main
  enabled: true
protocol:
  type: warp
  section: endpoints
  tag: WARP
  profile:
    detour: direct
```

Важно:

- MASQUE в этом форке — `outbounds`;
- WARP и VPN client — `endpoints`;
- XHTTP — `transport` соответствующего VLESS/другого outbound;
- нельзя выдумывать `mieru://`, `warp://` и похожие URI, если их не понимает
  конкретный parser форка.

`config/protocol-check.json` содержит безопасные dummy-объекты для реального
`sing-box check`.

## Секреты

Файл `config/secrets/local.yaml` игнорируется Git.

Пример структуры:

```yaml
subscriptions:
  example:
    url: https://.../subscription
mieru:
  username: user
  password: secret
```

Ссылка:

```yaml
url: ${secret:subscriptions.example.url}
```

Loader раскрывает только полную строку `${secret:path}`. Отсутствующий секрет —
ошибка. Выключенный `Subscription` или `Protocol` не требует своих секретов.

## Проверка изменений

После правки:

```bash
tools/check_local.sh
```

Для сравнения с предыдущей сборкой сохраните копию JSON и выполните:

```bash
.venv-wsl/bin/python tools/compare_configs.py \
  build/old-config.json build/artifacts/config.json
```

В output должны быть только ожидаемые изменения. Diff не выводит секретные
значения.
