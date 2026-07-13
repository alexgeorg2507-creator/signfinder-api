"""Tenant-scoping proxy over StorageBackend — cabinet template isolation.

signfinder-core's template functions (find_matching_templates, save_template,
list_templates, ...) write into a single flat "templates/" prefix with no
notion of a tenant. The legacy /v1/templates/* router (internal pipeline,
ApiKeyDep) uses that shared pool as-is and must keep doing so.

For the cabinet (/v1/me/*, Firebase JWT) each user's remembered templates
must be isolated from every other user's — and from the legacy pool. This
wrapper redirects only "templates/..." paths to "me/{tenant_id}/templates/...",
without touching signfinder-core. Every other path passes through untouched
(this proxy is only ever handed to template-related core functions).
"""
from __future__ import annotations

from typing import Optional

_SCOPED_PREFIX = "templates/"


class TenantScopedStorage:
    """Wraps a StorageBackend, namespacing "templates/" paths per tenant."""

    def __init__(self, inner, tenant_id: str):
        self._inner = inner
        self._tenant_id = tenant_id

    def _scope(self, path: str) -> str:
        if path.startswith(_SCOPED_PREFIX):
            return f"me/{self._tenant_id}/{path}"
        return path

    def read_bytes(self, path: str) -> Optional[bytes]:
        return self._inner.read_bytes(self._scope(path))

    def write_bytes(self, path: str, data: bytes) -> None:
        self._inner.write_bytes(self._scope(path), data)

    def exists(self, path: str) -> bool:
        return self._inner.exists(self._scope(path))

    def delete(self, path: str) -> bool:
        return self._inner.delete(self._scope(path))

    def list_prefix(self, prefix: str) -> list[str]:
        return self._inner.list_prefix(self._scope(prefix))

    def read_json(self, path: str) -> Optional[dict]:
        return self._inner.read_json(self._scope(path))

    def write_json(self, path: str, data: dict) -> None:
        self._inner.write_json(self._scope(path), data)

    def read_text(self, path: str) -> Optional[str]:
        return self._inner.read_text(self._scope(path))

    def write_text(self, path: str, content: str) -> None:
        self._inner.write_text(self._scope(path), content)
