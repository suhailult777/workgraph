"""Durable graph snapshot storage.

Local development keeps the Relate file on disk. A serverless deployment keeps
the same file in a private Vercel Blob store, copies it to /tmp for Relate, and
writes back with the Blob API's x-if-match conditional header and retry.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

BLOB_API = "https://vercel.com/api/blob"
DEFAULT_BLOB_PATH = "workgraph/workgraph.rl"
BLOB_API_VERSION = "13"


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


def _store_id(token: str) -> str:
    parts = token.split("_")
    if len(parts) < 4 or not parts[3]:
        raise StorageError(
            "blob_token_invalid",
            "BLOB_READ_WRITE_TOKEN does not contain a Vercel Blob store id.",
        )
    return parts[3]


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
        self.store_id = _store_id(token)
        self.pathname = pathname.strip("/")
        self.blob_url = (
            f"https://{self.store_id}.private.blob.vercel-storage.com/"
            f"{quote(self.pathname, safe='/')}"
        )
        self._http = http or httpx.Client(timeout=30)

    def _headers(self, content_type: str | None = None) -> dict[str, str]:
        headers = {
            "authorization": f"Bearer {self.token}",
            "x-api-version": BLOB_API_VERSION,
            "x-vercel-blob-store-id": self.store_id,
        }
        if content_type:
            headers["x-content-type"] = content_type
        return headers

    def _head(self) -> str | None:
        response = self._http.request(
            "GET",
            f"{BLOB_API}/?url={quote(self.blob_url, safe='')}",
            headers=self._headers(),
        )
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise StorageError(
                "blob_head_failed",
                f"Blob storage answered {response.status_code} while reading metadata.",
            )
        try:
            data = response.json()
        except ValueError:
            return None
        etag = data.get("etag") if isinstance(data, dict) else None
        return str(etag) if etag else None

    def load_to(self, path: Path) -> None:
        try:
            response = self._http.request(
                "GET",
                f"{self.blob_url}?cache=0",
                headers={"authorization": f"Bearer {self.token}"},
            )
        except httpx.HTTPError as exc:
            raise StorageError(
                "blob_read_failed",
                "Could not reach Vercel Blob while reading the graph snapshot.",
            ) from exc
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
        for attempt in range(3):
            etag = self._head()
            headers = self._headers("application/octet-stream")
            headers.update(
                {
                    "x-add-random-suffix": "0",
                    "x-allow-overwrite": "1",
                    "x-cache-control-max-age": "60",
                    "x-vercel-blob-access": "private",
                    "x-content-length": str(len(data)),
                    "x-api-blob-request-id": f"{self.store_id}:{uuid.uuid4().hex}",
                    "x-api-blob-request-attempt": str(attempt),
                }
            )
            if etag:
                headers["x-if-match"] = etag
            try:
                response = self._http.request(
                    "PUT",
                    f"{BLOB_API}/?pathname={quote(self.pathname, safe='')}",
                    headers=headers,
                    content=data,
                )
            except httpx.HTTPError as exc:
                raise StorageError(
                    "blob_write_failed",
                    "Could not reach Vercel Blob while saving the graph snapshot.",
                ) from exc
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
