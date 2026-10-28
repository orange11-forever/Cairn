import hashlib
import io
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from cairn_api.knowledge.object_store import ObjectNotFound, ObjectStoreError
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_objects_survive_reopening_and_cannot_be_overwritten(tmp_path: Path) -> None:
    from cairn_desktop.object_store import LocalObjectStore

    content = "桌面资料\n".encode()
    digest = hashlib.sha256(content).hexdigest()
    store = LocalObjectStore(tmp_path, "http://127.0.0.1:8080", b"test signing key")
    store.put_object(
        object_key="org/project/document",
        source=io.BytesIO(content),
        size_bytes=len(content),
        content_type="text/plain",
        checksum_sha256=digest,
    )
    reopened = LocalObjectStore(tmp_path, "http://127.0.0.1:8081", b"new signing key")
    assert reopened.stat(object_key="org/project/document").checksum_sha256 == digest
    with reopened.open_object(object_key="org/project/document") as source:
        assert source.read() == content
    with pytest.raises(ObjectStoreError):
        reopened.put_object(
            object_key="org/project/document",
            source=io.BytesIO(b"replace"),
            size_bytes=7,
            content_type="text/plain",
            checksum_sha256=hashlib.sha256(b"replace").hexdigest(),
        )
    with reopened.open_object(object_key="org/project/document") as source:
        assert source.read() == content


@pytest.mark.parametrize("key", ["../private", "/private", "a/../../private", "a\\private", "a//b"])
def test_object_keys_cannot_escape_the_managed_directory(tmp_path: Path, key: str) -> None:
    from cairn_desktop.object_store import LocalObjectStore

    store = LocalObjectStore(tmp_path, "http://127.0.0.1:8080", b"test signing key")
    with pytest.raises(ObjectStoreError):
        store.stat(object_key=key)


@pytest.mark.parametrize("size,digest", [(2, hashlib.sha256(b"abc").hexdigest()), (3, "0" * 64)])
def test_invalid_bytes_are_not_published(tmp_path: Path, size: int, digest: str) -> None:
    from cairn_desktop.object_store import LocalObjectStore

    store = LocalObjectStore(tmp_path, "http://127.0.0.1:8080", b"test signing key")
    with pytest.raises(ObjectStoreError):
        store.put_object(
            object_key="org/project/document",
            source=io.BytesIO(b"abc"),
            size_bytes=size,
            content_type="text/plain",
            checksum_sha256=digest,
        )
    with pytest.raises(ObjectNotFound):
        store.stat(object_key="org/project/document")


def test_signed_upload_download_expiry_and_tampering(tmp_path: Path) -> None:
    from cairn_desktop.object_store import LocalObjectStore

    now = datetime.now(UTC)
    store = LocalObjectStore(tmp_path, "http://testserver", b"test signing key", now=lambda: now)
    app = FastAPI()
    app.include_router(store.router())
    content = b"signed desktop upload"
    intent = store.presign_put(
        object_key="org/project/item",
        content_type="text/plain",
        checksum_sha256=hashlib.sha256(content).hexdigest(),
        expires_in=timedelta(minutes=5),
    )
    with TestClient(app) as client:
        uploaded = client.put(intent.url, content=content, headers=intent.headers)
        assert uploaded.status_code == 200, uploaded.text
        assert client.put(intent.url, content=content, headers=intent.headers).status_code == 409
        download = store.presign_get(
            object_key="org/project/item",
            download_name="document.txt",
            expires_in=timedelta(minutes=5),
        )
        result = client.get(download)
        assert result.content == content
        assert "attachment" in result.headers["content-disposition"]
        assert result.headers["cache-control"] == "private, no-store"
        assert client.get(download.replace("/item?", "/other?")).status_code == 403
        assert client.put(
            urlsplit(intent.url).path, content=content, headers=intent.headers
        ).status_code in {403, 422}
        now += timedelta(minutes=6)
        assert client.get(download).status_code == 403


def test_wrong_checksum_and_missing_immutable_header_reject_http_upload(tmp_path: Path) -> None:
    from cairn_desktop.object_store import LocalObjectStore

    store = LocalObjectStore(tmp_path, "http://testserver", b"test signing key")
    app = FastAPI()
    app.include_router(store.router())
    intent = store.presign_put(
        object_key="org/item",
        content_type="text/plain",
        checksum_sha256=hashlib.sha256(b"expected").hexdigest(),
        expires_in=timedelta(minutes=5),
    )
    with TestClient(app) as client:
        assert client.put(intent.url, content=b"wrong", headers=intent.headers).status_code == 422
        headers = {k: v for k, v in intent.headers.items() if k != "If-None-Match"}
        assert client.put(intent.url, content=b"expected", headers=headers).status_code == 422
    with pytest.raises(ObjectNotFound):
        store.stat(object_key="org/item")
