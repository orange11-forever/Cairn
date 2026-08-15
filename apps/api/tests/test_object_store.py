import base64
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Any, cast
from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError, ReadTimeoutError
from cairn_api.knowledge.dependencies import get_object_store
from cairn_api.knowledge.object_store import (
    Boto3ObjectStore,
    ObjectStoreUnavailable,
    bootstrap_object_store,
)
from fastapi import FastAPI, Request


class FakeS3Client:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.head_response: dict[str, Any] = {
            "ContentLength": 7,
            "ContentType": "text/plain",
        }
        self.object_bytes = b"content"
        self.object_body: Any | None = None
        self.head_bucket_error: ClientError | None = None
        self.head_bucket_errors: list[ClientError | None] = []
        self.create_bucket_error: ClientError | None = None
        self.put_cors_error: ClientError | None = None
        self.failure: Exception | None = None
        self.close_error: Exception | None = None

    def generate_presigned_url(
        self,
        operation: str,
        *,
        Params: dict[str, Any],
        ExpiresIn: int,
        HttpMethod: str | None = None,
    ) -> str:
        self.calls.append(
            (
                "generate_presigned_url",
                {
                    "operation": operation,
                    "Params": Params,
                    "ExpiresIn": ExpiresIn,
                    "HttpMethod": HttpMethod,
                },
            )
        )
        return f"https://objects.example/{operation}"

    def head_object(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("head_object", kwargs))
        if self.failure is not None:
            raise self.failure
        return self.head_response

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("get_object", kwargs))
        if self.failure is not None:
            raise self.failure
        return {"Body": self.object_body or BytesIO(self.object_bytes)}

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("put_object", kwargs))
        if self.failure is not None:
            raise self.failure
        return {}

    def delete_object(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("delete_object", kwargs))
        if self.failure is not None:
            raise self.failure
        return {}

    def head_bucket(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("head_bucket", kwargs))
        error = self.head_bucket_errors.pop(0) if self.head_bucket_errors else self.head_bucket_error
        if error is not None:
            raise error
        return {}

    def create_bucket(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("create_bucket", kwargs))
        if self.create_bucket_error is not None:
            raise self.create_bucket_error
        return {}

    def put_bucket_cors(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("put_bucket_cors", kwargs))
        if self.put_cors_error is not None:
            raise self.put_cors_error
        return {}

    def close(self) -> None:
        self.calls.append(("close", {}))
        if self.close_error is not None:
            raise self.close_error


def _client_error(code: str, operation: str = "HeadBucket") -> ClientError:
    return ClientError(
        {"Error": {"Code": code, "Message": "safe test failure"}},
        operation,
    )


def _store(
    *,
    internal: FakeS3Client | None = None,
    public: FakeS3Client | None = None,
    cors_preflight: Any | None = None,
) -> tuple[Boto3ObjectStore, FakeS3Client, FakeS3Client]:
    internal_client = internal or FakeS3Client()
    public_client = public or FakeS3Client()
    clients = iter((internal_client, public_client))

    def client_factory(_service: str, **_kwargs: Any) -> FakeS3Client:
        return next(clients)

    store = Boto3ObjectStore(
        bucket="knowledge-test",
        endpoint_url="http://minio.internal:9000",
        public_endpoint_url="https://objects.example",
        region="us-east-1",
        access_key="test-access-key",
        secret_key="test-secret-key",
        path_style=True,
        client_factory=client_factory,
        now=lambda: datetime(2026, 8, 12, 12, 0, tzinfo=UTC),
        **({"cors_preflight": cors_preflight} if cors_preflight is not None else {}),
    )
    return store, internal_client, public_client


def test_builds_distinct_internal_and_public_sigv4_path_style_clients() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def client_factory(service: str, **kwargs: Any) -> FakeS3Client:
        calls.append((service, kwargs))
        return FakeS3Client()

    store = Boto3ObjectStore(
        bucket="knowledge-test",
        endpoint_url="http://minio.internal:9000",
        public_endpoint_url="https://objects.example",
        region="cn-test-1",
        access_key="test-access-key",
        secret_key="test-secret-key",
        path_style=True,
        client_factory=client_factory,
    )

    assert [call[0] for call in calls] == ["s3", "s3"]
    assert [call[1]["endpoint_url"] for call in calls] == [
        "http://minio.internal:9000",
        "https://objects.example",
    ]
    for _, kwargs in calls:
        assert kwargs["region_name"] == "cn-test-1"
        assert kwargs["config"].signature_version == "s3v4"
        assert kwargs["config"].s3 == {"addressing_style": "path"}
    assert "test-access-key" not in repr(store)
    assert "test-secret-key" not in repr(store)


def test_presign_put_binds_checksum_content_type_and_create_only_header() -> None:
    store, _internal, public = _store()
    checksum_hex = "ab" * 32

    result = store.presign_put(
        object_key="org/project/random-key",
        content_type="text/plain",
        checksum_sha256=checksum_hex,
        expires_in=timedelta(minutes=15),
    )

    checksum_base64 = base64.b64encode(bytes.fromhex(checksum_hex)).decode("ascii")
    assert result.url == "https://objects.example/put_object"
    assert result.headers == {
        "Content-Type": "text/plain",
        "x-amz-checksum-sha256": checksum_base64,
        "If-None-Match": "*",
    }
    assert result.expires_at == datetime(2026, 8, 12, 12, 15, tzinfo=UTC)
    assert public.calls == [
        (
            "generate_presigned_url",
            {
                "operation": "put_object",
                "Params": {
                    "Bucket": "knowledge-test",
                    "Key": "org/project/random-key",
                    "ContentType": "text/plain",
                    "ChecksumSHA256": checksum_base64,
                    "IfNoneMatch": "*",
                },
                "ExpiresIn": 900,
                "HttpMethod": "PUT",
            },
        )
    ]


def test_stat_uses_provider_checksum_and_never_user_metadata() -> None:
    internal = FakeS3Client()
    checksum_hex = "cd" * 32
    internal.head_response = {
        "ContentLength": 7,
        "ContentType": "text/plain",
        "ChecksumSHA256": base64.b64encode(bytes.fromhex(checksum_hex)).decode("ascii"),
        "Metadata": {"sha256": "00" * 32},
    }
    store, _, _ = _store(internal=internal)

    result = store.stat(object_key="org/project/key")

    assert result.size_bytes == 7
    assert result.content_type == "text/plain"
    assert result.checksum_sha256 == checksum_hex
    assert internal.calls == [
        (
            "head_object",
            {"Bucket": "knowledge-test", "Key": "org/project/key", "ChecksumMode": "ENABLED"},
        )
    ]


def test_stat_streams_sha256_when_minio_omits_checksum_metadata() -> None:
    internal = FakeS3Client()
    internal.object_bytes = b"provider omitted checksum"
    store, _, _ = _store(internal=internal)

    result = store.stat(object_key="org/project/key")

    assert result.checksum_sha256 == (
        "a28a2f196d6b8cd336be57c93b52fc4d24b91a95c23a8b0611ad21c72a7b4038"
    )
    assert [call[0] for call in internal.calls] == ["head_object", "get_object"]


def test_stream_read_timeout_is_normalized_and_closes_the_provider_body() -> None:
    class FailingBody:
        closed = False

        def read(self, _size: int = -1) -> bytes:
            raise ReadTimeoutError(endpoint_url="https://secret.internal/object")

        def close(self) -> None:
            self.closed = True

    body = FailingBody()
    internal = FakeS3Client()
    internal.object_body = body
    store, _, _ = _store(internal=internal)

    with pytest.raises(ObjectStoreUnavailable) as caught:
        store.stat(object_key="org/project/key")

    assert body.closed is True
    assert "secret.internal" not in str(caught.value)


def test_stream_close_timeout_is_normalized() -> None:
    class CloseFailingBody:
        def read(self, _size: int = -1) -> bytes:
            return b"content"

        def close(self) -> None:
            raise ReadTimeoutError(endpoint_url="https://secret.internal/object")

    internal = FakeS3Client()
    internal.object_body = CloseFailingBody()
    store, _, _ = _store(internal=internal)

    with (
        pytest.raises(ObjectStoreUnavailable),
        store.open_object(object_key="org/project/key") as source,
    ):
        assert source.read() == b"content"


def test_open_put_delete_and_attachment_only_download_contract() -> None:
    store, internal, public = _store()
    checksum_hex = "ef" * 32
    source = BytesIO(b"content")

    with store.open_object(object_key="org/project/key") as opened:
        assert opened.read() == b"content"
    store.put_object(
        object_key="org/project/copied",
        source=source,
        size_bytes=7,
        content_type="text/html",
        checksum_sha256=checksum_hex,
    )
    download_url = store.presign_get(
        object_key="org/project/copied",
        download_name="../报告\r\n.html",
        expires_in=timedelta(minutes=5),
    )
    store.delete_object(object_key="org/project/copied")

    assert download_url == "https://objects.example/get_object"
    put_call = next(call for call in internal.calls if call[0] == "put_object")
    assert put_call[1] == {
        "Bucket": "knowledge-test",
        "Key": "org/project/copied",
        "Body": source,
        "ContentLength": 7,
        "ContentType": "text/html",
        "ChecksumSHA256": base64.b64encode(bytes.fromhex(checksum_hex)).decode("ascii"),
        "IfNoneMatch": "*",
    }
    get_call = public.calls[0][1]
    assert get_call["operation"] == "get_object"
    assert get_call["ExpiresIn"] == 300
    assert get_call["Params"]["ResponseContentType"] == "application/octet-stream"
    disposition = get_call["Params"]["ResponseContentDisposition"]
    assert disposition.startswith("attachment; filename*=UTF-8''")
    assert "%E6%8A%A5%E5%91%8A" in disposition
    assert "\r" not in disposition and "\n" not in disposition


def test_bootstrap_creates_only_missing_bucket_and_applies_restricted_cors() -> None:
    internal = FakeS3Client()
    internal.head_bucket_error = _client_error("404")
    store, _, _ = _store(internal=internal)

    store.bootstrap(allowed_origins=("https://web.example",))

    assert ("create_bucket", {"Bucket": "knowledge-test"}) in internal.calls
    cors_call = next(call for call in internal.calls if call[0] == "put_bucket_cors")
    assert cors_call[1] == {
        "Bucket": "knowledge-test",
        "CORSConfiguration": {
            "CORSRules": [
                {
                    "AllowedOrigins": ["https://web.example"],
                    "AllowedMethods": ["PUT", "GET", "HEAD"],
                    "AllowedHeaders": [
                        "content-type",
                        "x-amz-checksum-sha256",
                        "if-none-match",
                    ],
                    "ExposeHeaders": ["ETag", "x-amz-checksum-sha256"],
                    "MaxAgeSeconds": 300,
                }
            ]
        },
    }


def test_bootstrap_accepts_a_concurrent_create_only_after_bucket_is_accessible() -> None:
    internal = FakeS3Client()
    internal.head_bucket_errors = [_client_error("404"), None]
    internal.create_bucket_error = _client_error("BucketAlreadyOwnedByYou", "CreateBucket")
    store, _, _ = _store(internal=internal)

    store.bootstrap(allowed_origins=("https://web.example",))

    assert [call[0] for call in internal.calls[:3]] == [
        "head_bucket",
        "create_bucket",
        "head_bucket",
    ]


def test_bootstrap_accepts_only_a_verified_restricted_global_cors_fallback() -> None:
    internal = FakeS3Client()
    internal.put_cors_error = _client_error("NotImplemented", "PutBucketCors")
    calls: list[tuple[str, str, str]] = []

    def cors_preflight(endpoint: str, bucket: str, origin: str) -> bool:
        calls.append((endpoint, bucket, origin))
        return origin == "https://web.example"

    store, _, _ = _store(internal=internal, cors_preflight=cors_preflight)

    store.bootstrap(allowed_origins=("https://web.example",))

    assert calls == [
        ("https://objects.example", "knowledge-test", "https://web.example"),
        ("https://objects.example", "knowledge-test", "https://cairn-cors-probe.invalid"),
    ]

    def wildcard_cors(_endpoint: str, _bucket: str, _origin: str) -> bool:
        return True

    with pytest.raises(ObjectStoreUnavailable):
        wildcard_store, _, _ = _store(
            internal=internal,
            cors_preflight=wildcard_cors,
        )
        wildcard_store.bootstrap(allowed_origins=("https://web.example",))


def test_object_store_failures_have_secret_free_public_text() -> None:
    internal = FakeS3Client()
    internal.failure = ClientError(
        {"Error": {"Code": "InternalError", "Message": "test-secret-key leaked"}},
        "HeadObject",
    )
    store, _, _ = _store(internal=internal)

    with pytest.raises(ObjectStoreUnavailable) as caught:
        store.stat(object_key="org/project/key")

    assert str(caught.value) == "object store operation failed"
    assert "secret" not in repr(caught.value)


def test_request_dependency_returns_only_a_valid_object_store() -> None:
    store, _, _ = _store()
    app = FastAPI()
    app.state.object_store = store
    request = Request(cast(Any, {"type": "http", "app": app}))

    assert get_object_store(request) is store

    app.state.object_store = object()
    with pytest.raises(TypeError, match="object store is not configured"):
        get_object_store(request)


def test_store_close_and_bootstrap_failure_close_every_created_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    internal = FakeS3Client()
    internal.close_error = RuntimeError("internal close failed")
    store, _, public = _store(internal=internal)

    with pytest.raises(RuntimeError, match="internal close failed"):
        store.close()
    assert public.calls[-1] == ("close", {})

    failing_store = Mock()
    failing_store.bootstrap.side_effect = RuntimeError("unexpected bootstrap failure")

    def from_settings(_settings: Any) -> Any:
        return failing_store

    monkeypatch.setattr(Boto3ObjectStore, "from_settings", staticmethod(from_settings))
    with pytest.raises(RuntimeError, match="unexpected bootstrap failure"):
        bootstrap_object_store(cast(Any, object()), allowed_origins=())
    failing_store.close.assert_called_once_with()
