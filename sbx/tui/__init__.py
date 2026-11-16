"""TUI configurator for the sbx pipeline."""

from __future__ import annotations

__all__ = ["main"]


def main() -> int:
    from .app import run

    return run()