import base64
import hashlib
from collections.abc import Callable, Generator, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, BinaryIO, NoReturn, Protocol, cast, runtime_checkable
from urllib.parse import quote

import boto3
import httpx
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from mypy_boto3_s3.client import S3Client

if TYPE_CHECKING:
    from cairn_api.settings import Settings


@dataclass(frozen=True)
class PresignedPut:
    url: str
    headers: dict[str, str]
    expires_at: datetime


@dataclass(frozen=True)
class ObjectStat:
    size_bytes: int
    content_type: str | None
    checksum_sha256: str | None


class ObjectStoreError(RuntimeError):
    default_message = "object store operation failed"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.default_message)

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


class ObjectStoreUnavailable(ObjectStoreError):
    pass


class ObjectNotFound(ObjectStoreError):
    default_message = "object not found"


@runtime_checkable
class ObjectStore(Protocol):
    def presign_put(
        self,
        *,
        object_key: str,
        content_type: str,
        checksum_sha256: str,
        expires_in: timedelta,
    ) -> PresignedPut: ...

    def stat(self, *, object_key: str) -> ObjectStat: ...

    def open_object(self, *, object_key: str) -> AbstractContextManager[BinaryIO]: ...

    def put_object(
        self,
        *,
        object_key: str,
        source: BinaryIO,
        size_bytes: int,
        content_type: str,
        checksum_sha256: str,
    ) -> None: ...

    def presign_get(
        self,
        *,
        object_key: str,
        download_name: str,
        expires_in: timedelta,
    ) -> str: ...

    def delete_object(self, *, object_key: str) -> None: ...

    def check_ready(self) -> None: ...

    def close(self) -> None: ...


ClientFactory = Callable[..., Any]
CorsPreflight = Callable[[str, str, str], bool]
_NOT_FOUND_CODES = frozenset({"404", "NoSuchBucket", "NoSuchKey", "NotFound"})
_BUCKET_CREATE_CONFLICT_CODES = frozenset(
    {"409", "BucketAlreadyExists", "BucketAlreadyOwnedByYou"}
)
_CORS_HEADERS = frozenset({"content-type", "x-amz-checksum-sha256", "if-none-match"})
_CORS_PROBE_ORIGIN = "https://cairn-cors-probe.invalid"


def _create_s3_client(
    _service_name: str,
    *,
    endpoint_url: str,
    aws_access_key_id: str,
    aws_secret_access_key: str,
    region_name: str,
    config: Config,
) -> S3Client:
    # boto3-stubs leaves unrelated service overloads partially unknown in strict mode.
    return boto3.client(  # pyright: ignore[reportUnknownMemberType]
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
        region_name=region_name,
        config=config,
    )


def _cors_preflight(endpoint_url: str, bucket: str, origin: str) -> bool:
    try:
        with httpx.Client(trust_env=False) as client:
            response = client.options(
                f"{endpoint_url.rstrip('/')}/{quote(bucket, safe='')}/cairn-cors-probe",
                headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": "PUT",
                    "Access-Control-Request-Headers": ",".join(sorted(_CORS_HEADERS)),
                },
                timeout=10,
            )
    except httpx.HTTPError:
        return False
    allowed_origin = response.headers.get("access-control-allow-origin")
    allowed_methods = {
        value.strip().upper()
        for value in response.headers.get("access-control-allow-methods", "").split(",")
    }
    allowed_headers = {
        value.strip().lower()
        for value in response.headers.get("access-control-allow-headers", "").split(",")
    }
    return (
        response.is_success
        and allowed_origin in {origin, "*"}
        and "PUT" in allowed_methods
        and _CORS_HEADERS.issubset(allowed_headers)
    )


def _client_error_code(error: ClientError) -> str:
    value = error.response.get("Error", {}).get("Code", "")
    return str(value)


_CLIENT_FAILURES = (BotoCoreError, ClientError, KeyError, TypeError, ValueError)
_STREAM_FAILURES = (BotoCoreError, ClientError, OSError)


def _raise_store_error(error: Exception, *, missing_is_not_found: bool = False) -> NoReturn:
    if (
        missing_is_not_found
        and isinstance(error, ClientError)
        and _client_error_code(error) in _NOT_FOUND_CODES
    ):
        raise ObjectNotFound() from None
    raise ObjectStoreUnavailable() from None


def _checksum_base64(checksum_sha256: str) -> str:
    if len(checksum_sha256) != 64:
        raise ValueError("checksum_sha256 must be 64 lowercase hexadecimal characters")
    try:
        raw = bytes.fromhex(checksum_sha256)
    except ValueError as error:
        raise ValueError("checksum_sha256 must be 64 lowercase hexadecimal characters") from error
    if checksum_sha256 != checksum_sha256.lower():
        raise ValueError("checksum_sha256 must be 64 lowercase hexadecimal characters")
    return base64.b64encode(raw).decode("ascii")


def _expires_seconds(expires_in: timedelta) -> int:
    seconds = int(expires_in.total_seconds())
    if seconds <= 0:
        raise ValueError("expires_in must be positive")
    return seconds


def _safe_download_name(download_name: str) -> str:
    normalized = download_name.replace("/", "_").replace("\\", "_")
    normalized = "".join(character for character in normalized if ord(character) >= 32)
    normalized = normalized.strip().strip(".")
    return normalized or "download"


class _TranslatedObjectBody:
    def __init__(self, source: Any) -> None:
        self._source = source

    def read(self, size: int = -1) -> bytes:
        try:
            chunk = self._source.read(size)
        except _STREAM_FAILURES as error:
            _raise_store_error(error)
        if not isinstance(chunk, bytes):
            raise ObjectStoreUnavailable()
        return chunk

    def close(self) -> None:
        try:
            self._source.close()
        except _STREAM_FAILURES as error:
            _raise_store_error(error)


class Boto3ObjectStore:
    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str,
        public_endpoint_url: str,
        region: str,
        access_key: str,
        secret_key: str,
        path_style: bool,
        client_factory: ClientFactory = _create_s3_client,
        cors_preflight: CorsPreflight = _cors_preflight,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._bucket = bucket
        self._public_endpoint_url = public_endpoint_url.rstrip("/")
        self._region = region
        self._now = now or (lambda: datetime.now(UTC))
        self._cors_preflight = cors_preflight
        addressing_style = "path" if path_style else "virtual"
        client_options = {
            "aws_access_key_id": access_key,
            "aws_secret_access_key": secret_key,
            "region_name": region,
            "config": Config(
                signature_version="s3v4",
                s3={"addressing_style": addressing_style},
            ),
        }
        self._client = client_factory("s3", endpoint_url=endpoint_url, **client_options)
        self._public_client = client_factory(
            "s3",
            endpoint_url=public_endpoint_url,
            **client_options,
        )

    def __repr__(self) -> str:
        return f"Boto3ObjectStore(bucket={self._bucket!r}, region={self._region!r})"

    @classmethod
    def from_settings(cls, settings: "Settings") -> "Boto3ObjectStore":
        return cls(
            bucket=settings.object_store_bucket,
            endpoint_url=str(settings.object_store_endpoint_url).rstrip("/"),
            public_endpoint_url=str(settings.object_store_public_endpoint_url).rstrip("/"),
            region=settings.object_store_region,
            access_key=settings.object_store_access_key.get_secret_value(),
            secret_key=settings.object_store_secret_key.get_secret_value(),
            path_style=settings.object_store_path_style,
        )

    def presign_put(
        self,
        *,
        object_key: str,
        content_type: str,
        checksum_sha256: str,
        expires_in: timedelta,
    ) -> PresignedPut:
        checksum = _checksum_base64(checksum_sha256)
        expires_seconds = _expires_seconds(expires_in)
        parameters = {
            "Bucket": self._bucket,
            "Key": object_key,
            "ContentType": content_type,
            "ChecksumSHA256": checksum,
            "IfNoneMatch": "*",
        }
        try:
            url = self._public_client.generate_presigned_url(
                "put_object",
                Params=parameters,
                ExpiresIn=expires_seconds,
                HttpMethod="PUT",
            )
        except _CLIENT_FAILURES as error:
            _raise_store_error(error)
        return PresignedPut(
            url=str(url),
            headers={
                "Content-Type": content_type,
                "x-amz-checksum-sha256": checksum,
                "If-None-Match": "*",
            },
            expires_at=self._now() + timedelta(seconds=expires_seconds),
        )

    def stat(self, *, object_key: str) -> ObjectStat:
        try:
            response = self._client.head_object(
                Bucket=self._bucket,
                Key=object_key,
                ChecksumMode="ENABLED",
            )
        except _CLIENT_FAILURES as error:
            _raise_store_error(error, missing_is_not_found=True)

        checksum_sha256: str | None = None
        provider_checksum = response.get("ChecksumSHA256")
        if isinstance(provider_checksum, str):
            try:
                checksum_bytes = base64.b64decode(provider_checksum, validate=True)
            except ValueError:
                checksum_bytes = b""
            if len(checksum_bytes) == 32:
                checksum_sha256 = checksum_bytes.hex()
        if checksum_sha256 is None:
            checksum_sha256 = self._stream_checksum(object_key=object_key)
        content_type = response.get("ContentType")
        return ObjectStat(
            size_bytes=int(response["ContentLength"]),
            content_type=content_type if isinstance(content_type, str) else None,
            checksum_sha256=checksum_sha256,
        )

    def _stream_checksum(self, *, object_key: str) -> str:
        digest = hashlib.sha256()
        with self.open_object(object_key=object_key) as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()

    @contextmanager
    def open_object(self, *, object_key: str) -> Generator[BinaryIO]:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=object_key)
            body = _TranslatedObjectBody(response["Body"])
        except _CLIENT_FAILURES as error:
            _raise_store_error(error, missing_is_not_found=True)
        try:
            yield cast(BinaryIO, body)
        finally:
            body.close()

    def put_object(
        self,
        *,
        object_key: str,
        source: BinaryIO,
        size_bytes: int,
        content_type: str,
        checksum_sha256: str,
    ) -> None:
        checksum = _checksum_base64(checksum_sha256)
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=object_key,
                Body=source,
                ContentLength=size_bytes,
                ContentType=content_type,
                ChecksumSHA256=checksum,
                IfNoneMatch="*",
            )
        except _CLIENT_FAILURES as error:
            _raise_store_error(error)

    def _verify_global_cors(self, *, allowed_origins: Sequence[str]) -> None:
        if not all(
            self._cors_preflight(self._public_endpoint_url, self._bucket, origin)
            for origin in allowed_origins
        ):
            raise ObjectStoreUnavailable()
        disallowed_origin = _CORS_PROBE_ORIGIN
        if disallowed_origin in allowed_origins:
            disallowed_origin = "https://cairn-cors-probe-2.invalid"
        if self._cors_preflight(self._public_endpoint_url, self._bucket, disallowed_origin):
            raise ObjectStoreUnavailable()

    def presign_get(
        self,
        *,
        object_key: str,
        download_name: str,
        expires_in: timedelta,
    ) -> str:
        expires_seconds = _expires_seconds(expires_in)
        disposition = (
            f"attachment; filename*=UTF-8''{quote(_safe_download_name(download_name), safe='')}"
        )
        try:
            url = self._public_client.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": self._bucket,
                    "Key": object_key,
                    "ResponseContentDisposition": disposition,
                    "ResponseContentType": "application/octet-stream",
                },
                ExpiresIn=expires_seconds,
            )
        except _CLIENT_FAILURES as error:
            _raise_store_error(error)
        return str(url)

    def delete_object(self, *, object_key: str) -> None:
        try:
            self._client.delete_object(Bucket=self._bucket, Key=object_key)
        except _CLIENT_FAILURES as error:
            _raise_store_error(error)

    def check_ready(self) -> None:
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except _CLIENT_FAILURES as error:
            _raise_store_error(error)

    def bootstrap(self, *, allowed_origins: Sequence[str]) -> None:
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except ClientError as error:
            if _client_error_code(error) not in _NOT_FOUND_CODES:
                _raise_store_error(error)
            create_parameters: dict[str, Any] = {"Bucket": self._bucket}
            if self._region != "us-east-1":
                create_parameters["CreateBucketConfiguration"] = {
                    "LocationConstraint": self._region
                }
            try:
                self._client.create_bucket(**create_parameters)
            except ClientError as create_error:
                if _client_error_code(create_error) not in _BUCKET_CREATE_CONFLICT_CODES:
                    _raise_store_error(create_error)
                try:
                    self._client.head_bucket(Bucket=self._bucket)
                except _CLIENT_FAILURES as confirm_error:
                    _raise_store_error(confirm_error)
            except (BotoCoreError, KeyError, TypeError, ValueError) as create_error:
                _raise_store_error(create_error)
        except BotoCoreError as error:
            _raise_store_error(error)

        if not allowed_origins:
            return
        try:
            self._client.put_bucket_cors(
                Bucket=self._bucket,
                CORSConfiguration={
                    "CORSRules": [
                        {
                            "AllowedOrigins": list(allowed_origins),
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
            )
        except ClientError as error:
            if _client_error_code(error) != "NotImplemented":
                _raise_store_error(error)
            self._verify_global_cors(allowed_origins=allowed_origins)
        except (BotoCoreError, KeyError, TypeError, ValueError) as error:
            _raise_store_error(error)

    def close(self) -> None:
        try:
            self._client.close()
        finally:
            self._public_client.close()


def bootstrap_object_store(
    settings: "Settings",
    *,
    allowed_origins: Sequence[str],
) -> Boto3ObjectStore:
    store = Boto3ObjectStore.from_settings(settings)
    bootstrap_succeeded = False
    try:
        store.bootstrap(allowed_origins=allowed_origins)
        bootstrap_succeeded = True
    finally:
        if not bootstrap_succeeded:
            store.close()
    return store


__all__ = [
    "Boto3ObjectStore",
    "ObjectNotFound",
    "ObjectStat",
    "ObjectStore",
    "ObjectStoreError",
    "ObjectStoreUnavailable",
    "PresignedPut",
    "bootstrap_object_store",
]
