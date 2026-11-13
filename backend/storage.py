"""Durable graph snapshot storage.

Local development keeps the Relate file on disk. A serverless deployment keeps
the same file in Vercel Blob and copies it to a temporary path for Relate. Writes
use the blob's ETag with If-Match and retry once on a conflict.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx

BLOB_BASE = "https://blob.vercel-storage.com"
DEFAULT_BLOB_PATH = "workgraph/workgraph.rl"


class StorageError(Exception):
    def __init__(self, code: str, message: str, status: int = 503):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class LocalStorage:
    kind = "local_file"

    def load_to(self, path: Path) -> None:
        return None

    def save_from(self, path: Path) -> None:
        return None


class BlobStorage:
    kind = "vercel_blob"

    def __init__(
        self,
        token: str,
        pathname: str = DEFAULT_BLOB_PATH,
        http: Any | None = None,
    ):
        if not token:
            raise StorageError("blob_token_missing", "BLOB_READ_WRITE_TOKEN is not set.")
        self.token = token
        self.pathname = pathname.strip("/")
        self.url = f"{BLOB_BASE}/{self.pathname}"
        self._http = http or httpx.Client(timeout=30)

    def _headers(self, content_type: str | None = None) -> dict[str, str]:
        headers = {
            "authorization": f"Bearer {self.token}",
            "x-api-version": "7",
        }
        if content_type:
            headers["x-content-type"] = content_type
        return headers

    def load_to(self, path: Path) -> None:
        response = self._http.request("GET", self.url, headers=self._headers())
        if response.status_code == 404:
            raise StorageError("blob_missing", "The graph snapshot is missing from blob storage.")
        if response.status_code >= 400:
            raise StorageError(
                "blob_read_failed",
                f"Blob storage answered {response.status_code} while reading the snapshot.",
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)

    def save_from(self, path: Path) -> None:
        data = path.read_bytes()
        last_status = None
        for _ in range(3):
            head = self._http.request("HEAD", self.url, headers=self._headers())
            etag = head.headers.get("etag") if head.status_code < 400 else None
            headers = self._headers("application/octet-stream")
            headers["x-add-random-suffix"] = "0"
            headers["x-cache-control-max-age"] = "60"
            if etag:
                headers["if-match"] = etag
            response = self._http.request("PUT", self.url, headers=headers, content=data)
            if response.status_code in (200, 201):
                return
            last_status = response.status_code
            if response.status_code not in (409, 412):
                break
        raise StorageError(
            "blob_write_failed",
            f"Blob storage could not save the graph snapshot (last status {last_status}).",
        )


def build_storage() -> LocalStorage | BlobStorage:
    token = os.environ.get("BLOB_READ_WRITE_TOKEN")
    if token:
        pathname = os.environ.get("BLOB_STORE_PATH", DEFAULT_BLOB_PATH)
        return BlobStorage(token, pathname=pathname)
    return LocalStorage()
