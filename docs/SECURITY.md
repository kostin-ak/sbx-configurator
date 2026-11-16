# Безопасность

## Основные принципы

1. Роутерная конфигурация доступна как read-only source, пока пользователь
   отдельно не одобряет deployment.
2. Секреты не фиксируются в Git, source pack или router bundle.
3. Полный конфигурация собирается только на устройстве, где переданы секреты.
4. Тестовый proxy-only runtime работает на отдельных loopback-портах.
5. Никакой сборщик не перезапускает старый сервис.

## Где находятся секреты

Только локально и в ignored-файлах:

```text
snapshot/
config/secrets/local.yaml
config/local.yaml
```

Source release не копирует `local.yaml` и не содержит:

- URL подписок;
- passwords, UUID, tokens;
- cache subscription;
- binary;
- runtime state.

## Masking

`sbx/secrets.py` используется для отчётов. Поля вроде:

- `password`;
- `uuid`;
- `token`;
- `private_key`;
- `join_link`;
- `url`

маскируются в diff/report/reporting-выводах.

Это не заменяет защиту исходных файлов, а снижает риск утечки в консоль или
диагностике.

## Аудит packs

Перед передачей всегда запускайте:

```bash
python tools/audit_release.py artifacts/sbx-0.2.0.sbxpack
```

## Права доступа

На POSIX-системах secrets должны иметь режим `0600`.

На локальном NTFS/WSL-пути режимы могут отображаться как `777`, потому что
filesystem mount не сохраняет POSIX permissions. Это не относится к будущему
router staging на ext4: там `install_staging.sh` выполняет `chmod 600`.

## Supply chain

- Версия форка фиксируется: `1.14.3-extended-2.7.3`.
- Download script проверяет SHA-256 из GitHub API.
- `.sbxpack` содержит manifest с hash каждого файла.
- `latest` не используется.

## Опасные операции, которые не должны выполняться автоматически

- установка форкового `.ipk`;
- `opkg remove sing-box`;
- замена `/usr/bin/sing-box`;
- изменение `/etc/sing-box`;
- перезапуск procd service;
- одновременный запуск двух TUN;
- удаление `/data/sbx`, если внутри важные данные;
- отключение firewall/route rules.

Любая из этих операций требует отдельного согласования.

## Git

Сейчас Git initialized, но commit не создан. Перед первым коммитом проверьте:

```bash
git status --short
git check-ignore -v config/secrets/local.yaml
git check-ignore -v snapshot/etc/sing-box/config.json
git check-ignore -v bin/router/sing-box-extended
```

Не коммитьте secrets. Игнорируемый файл может быть скрыт из `git status`, но
всё равно остаётся на диске.
