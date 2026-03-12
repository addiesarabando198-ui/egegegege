"""Initialization for task25 module."""

try:
    from .plugin import plugin
except Exception:  # pragma: no cover - optional plugin import
    plugin = None

__all__ = ['plugin']