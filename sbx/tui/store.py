"""Round-trip YAML storage with atomic writes and validation."""

from __future__ import annotations

import os
import shutil
import tempfile
import io
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from ..loader import ConfigError, load_config
from .profiles import Profile


class StoreError(RuntimeError):
    pass


def _yaml() -> YAML:
    instance = YAML(typ="rt")
    instance.preserve_quotes = True
    instance.width = 4096
    instance.allow_unicode = True
    instance.indent(mapping=2, sequence=4, offset=2)
    return instance


@dataclass
class Document:
    path: Path
    data: Any
    original: str
    dirty: bool = False
    error: str | None = None


class ConfigStore:
    """Owns the YAML files of one profile."""

    def __init__(self, profile: Profile) -> None:
        self.profile = profile
        self._documents: dict[Path, Document] = {}

    # ------------------------------------------------------------------ files
    def files(self, *, include_secrets: bool = True) -> list[Path]:
        base = self.profile.config_dir
        if not base.is_dir():
            return []
        files = sorted(path for path in base.rglob("*.yaml") if path.is_file())
        files += sorted(path for path in base.rglob("*.yml") if path.is_file())
        if not include_secrets:
            files = [path for path in files if "secrets" not in path.parts]
        return files

    def relative(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.profile.root))
        except ValueError:
            return str(path)

    # --------------------------------------------------------------- documents
    def load(self, path: Path) -> Document:
        path = path.resolve()
        cached = self._documents.get(path)
        if cached is not None:
            return cached
        if not path.is_file():
            raise StoreError(f"file is absent: {path}")
        text = path.read_text(encoding="utf-8")
        try:
            data = _yaml().load(text)
        except Exception as error:  # noqa: BLE001 - surface YAML errors in the UI
            raise StoreError(f"{self.relative(path)}: {error}") from error
        if data is None:
            data = CommentedMap()
        document = Document(path=path, data=data, original=text)
        self._documents[path] = document
        return document

    def reload(self) -> None:
        self._documents.clear()

    def create(self, path: Path, data: Any) -> Document:
        path = path.resolve()
        if path.exists():
            raise StoreError(f"file already exists: {self.relative(path)}")
        path.parent.mkdir(parents=True, exist_ok=True)
        document = Document(path=path, data=data, original="", dirty=True)
        self._documents[path] = document
        self.save(document)
        return document

    def save(self, document: Document) -> None:
        path = document.path
        buffer = _yaml()
        text_io = io.StringIO()
        buffer.dump(document.data, text_io)
        text = text_io.getvalue()
        backup = path.with_suffix(path.suffix + ".bak")
        if path.is_file():
            shutil.copy2(path, backup)
        _atomic_write(path, text)
        previous = document.original
        document.original = text
        document.dirty = False
        document.error = None
        try:
            self.validate()
        except StoreError as error:
            _atomic_write(path, previous)
            document.original = previous
            document.error = str(error)
            raise StoreError(str(error)) from error

    def save_text(self, path: Path, text: str) -> None:
        """Save raw YAML text (used by the full-file editor)."""

        path = path.resolve()
        data = _yaml().load(text)
        if data is None:
            data = CommentedMap()
        document = Document(path=path, data=data, original=text, dirty=True)
        backup = path.with_suffix(path.suffix + ".bak")
        previous = path.read_text(encoding="utf-8") if path.is_file() else ""
        if path.is_file():
            shutil.copy2(path, backup)
        _atomic_write(path, text)
        try:
            self.validate()
        except StoreError:
            _atomic_write(path, previous)
            raise
        document.original = text
        document.dirty = False
        self._documents[path] = document

    def archive(self, path: Path) -> Path:
        path = path.resolve()
        trash = self.profile.config_dir / ".trash"
        trash.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = trash / f"{stamp}-{path.name}"
        shutil.move(str(path), str(target))
        self._documents.pop(path, None)
        return target

    # -------------------------------------------------------------- validation
    def validate(self) -> None:
        secrets = self.profile.secrets if self.profile.secrets.is_file() else None
        try:
            load_config(self.profile.config_dir, secrets)
        except (ConfigError, ValueError, OSError) as error:
            raise StoreError(str(error)) from error

    # ------------------------------------------------------------- convenience
    def subscriptions(self) -> list[Document]:
        folder = self.profile.subscriptions_dir
        if not folder.is_dir():
            return []
        return [self.load(path) for path in sorted(folder.glob("*.yaml"))]

    def selectors(self) -> Document:
        path = self.profile.selectors_file
        if not path.is_file():
            raise StoreError("selectors.yaml is absent")
        return self.load(path)

    def secrets(self) -> Document | None:
        path = self.profile.secrets
        if not path.is_file():
            return None
        return self.load(path)

    def secrets_entries(self) -> list[tuple[str, str]]:
        document = self.secrets()
        if document is None:
            return []
        return list(_flatten(document.data))


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".sbx-", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _flatten(value: Any, prefix: str = "") -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            name = f"{prefix}.{key}" if prefix else str(key)
            result.extend(_flatten(item, name))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            result.extend(_flatten(item, f"{prefix}[{index}]"))
    else:
        result.append((prefix, "" if value is None else str(value)))
    return result


def mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 6:
        return "*" * len(value)
    return f"{value[:3]}{'*' * min(12, len(value) - 6)}{value[-3:]}"


def lookup(data: Any, path: tuple[str, ...]) -> Any:
    current = data
    for part in path:
        if isinstance(current, list):
            current = current[int(part)]
        else:
            current = current[part]
    return current


def assign(data: Any, path: tuple[str, ...], value: Any) -> None:
    if not path:
        raise StoreError("empty path")
    current = data
    for part in path[:-1]:
        if isinstance(current, list):
            current = current[int(part)]
        else:
            current = current[part]
    last = path[-1]
    if isinstance(current, list):
        current[int(last)] = value
    else:
        current[last] = value


def coerce(text: str) -> Any:
    lowered = text.strip().lower()
    if lowered in {"true", "yes", "on"}:
        return True
    if lowered in {"false", "no", "off"}:
        return False
    if lowered in {"null", "none", "~"}:
        return None
    try:
        return int(text, 10)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text


__all__ = [
    "ConfigStore",
    "Document",
    "StoreError",
    "CommentedMap",
    "CommentedSeq",
    "mask",
    "lookup",
    "assign",
    "coerce",
]
