"""Redaction helpers used by reports, diffs and logs."""

from __future__ import annotations

from typing import Any


SENSITIVE_KEYS = {
    "password",
    "passphrase",
    "private_key",
    "private_key_path",
    "token",
    "auth_token",
    "secret",
    "cookies",
    "uuid",
    "key",
    "join_link",
    "url",
}


def mask_string(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "***"
    return value[:4] + "***" + value[-4:]


def mask_config(value: Any, parent_key: str = "") -> Any:
    key = parent_key.lower()
    if isinstance(value, dict):
        result = {}
        for item_key, item_value in value.items():
            if item_key.lower() in SENSITIVE_KEYS and isinstance(item_value, str):
                result[item_key] = mask_string(item_value)
            else:
                result[item_key] = mask_config(item_value, item_key)
        return result
    if isinstance(value, list):
        return [mask_config(item, parent_key) for item in value]
    if key in SENSITIVE_KEYS and isinstance(value, str):
        return mask_string(value)
    return value
