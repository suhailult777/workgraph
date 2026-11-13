from pathlib import Path

import pytest

from backend.storage import BlobStorage, LocalStorage, StorageError

TOKEN = "_".join(["vercel_blob", "rw", "store123", "secret"])


class FakeResponse:
    def __init__(self, status_code: int, content: bytes = b"", headers: dict | None = None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}

    def json(self):
        import json

        return json.loads(self.content.decode("utf-8"))


class FakeHttp:
    def __init__(self, stored: bytes = b"graph-v1", conflict_once: bool = False):
        self.stored = stored
        self.etag = "etag-1"
        self.conflict_once = conflict_once
        self.calls: list[tuple[str, str, dict, bytes | None]] = []

    def request(self, method, url, headers=None, content=None):
        headers = headers or {}
        self.calls.append((method, url, dict(headers), content))
        if method == "GET" and url.startswith("https://vercel.com/api/blob"):
            if self.stored is None:
                return FakeResponse(404)
            return FakeResponse(200, b'{"etag": "%s"}' % self.etag.encode())
        if method == "GET":
            if self.stored is None:
                return FakeResponse(404)
            return FakeResponse(200, self.stored, {"etag": self.etag})
        if method == "PUT":
            if self.conflict_once:
                self.conflict_once = False
                self.etag = "etag-2"
                return FakeResponse(412)
            if headers.get("x-if-match") not in (None, self.etag):
                return FakeResponse(412)
            self.stored = content or b""
            self.etag = "etag-3"
            return FakeResponse(200, b"{}")
        return FakeResponse(405)


def test_local_storage_is_a_noop(tmp_path):
    storage = LocalStorage()
    target = tmp_path / "graph.rl"
    target.write_bytes(b"local")
    storage.save_from(target)
    storage.load_to(target)
    assert target.read_bytes() == b"local"
    assert storage.kind == "local_file"


def test_blob_storage_loads_the_snapshot(tmp_path):
    http = FakeHttp(b"remote-graph")
    storage = BlobStorage(TOKEN, http=http)
    target = tmp_path / "nested" / "graph.rl"

    storage.load_to(target)

    assert target.read_bytes() == b"remote-graph"
    assert http.calls[0][0] == "GET"
    assert http.calls[0][1].startswith("https://store123.private.blob.vercel-storage.com/")
    assert http.calls[0][2]["authorization"] == f"Bearer {TOKEN}"


def test_blob_storage_retries_after_an_etag_conflict(tmp_path):
    http = FakeHttp(conflict_once=True)
    storage = BlobStorage(TOKEN, http=http)
    target = tmp_path / "graph.rl"
    target.write_bytes(b"new-graph")

    storage.save_from(target)

    puts = [call for call in http.calls if call[0] == "PUT"]
    assert len(puts) == 2
    assert puts[0][2]["x-if-match"] == "etag-1"
    assert puts[1][2]["x-if-match"] == "etag-2"
    assert puts[0][2]["x-allow-overwrite"] == "1"
    assert puts[0][2]["x-vercel-blob-store-id"] == "store123"
    assert http.stored == b"new-graph"


def test_blob_storage_reports_a_missing_snapshot(tmp_path):
    storage = BlobStorage(TOKEN, http=FakeHttp(stored=None))
    with pytest.raises(StorageError) as error:
        storage.load_to(Path(tmp_path) / "graph.rl")
    assert error.value.code == "blob_missing"
