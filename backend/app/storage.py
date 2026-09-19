"""Pluggable storage backend for photo files.

The diary starts by storing photos on the local server disk, but the server
(an old phone running Linux) has limited capacity. All photo I/O goes through
the ``StorageBackend`` interface so a cloud/remote backend (e.g. Google Drive,
S3, another server) can be added later without touching the rest of the app.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from .config import get_settings


class StorageBackend(ABC):
    """Abstract binary blob store keyed by an opaque string key."""

    @abstractmethod
    def save(self, key: str, data: bytes) -> None: ...

    @abstractmethod
    def load(self, key: str) -> bytes: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...


class LocalStorage(StorageBackend):
    """Stores blobs as files under ``photos_dir``.

    Keys may contain forward slashes to create sub-directories, but are
    sanitized to stay within the base directory.
    """

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # Prevent path traversal: resolve and ensure it stays under base_dir.
        candidate = (self.base_dir / key).resolve()
        base = self.base_dir.resolve()
        if base not in candidate.parents and candidate != base:
            raise ValueError(f"Invalid storage key: {key!r}")
        return candidate

    def save(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def load(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        path = self._path(key)
        if path.exists():
            path.unlink()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()


_backend: StorageBackend | None = None


def get_storage() -> StorageBackend:
    """Return the configured storage backend (currently local disk)."""
    global _backend
    if _backend is None:
        _backend = LocalStorage(get_settings().photos_dir)
    return _backend
