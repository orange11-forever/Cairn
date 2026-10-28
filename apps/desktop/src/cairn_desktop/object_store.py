"""Immutable local objects; signed URLs retain the existing upload contract."""

import base64
import hashlib
import hmac
import json
import os
import shutil
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import BinaryIO
from urllib.parse import quote, urlencode

from cairn_api.knowledge.media import ARCHIVE_MAX_BYTES
from cairn_api.knowledge.object_store import (
    ObjectNotFound,
    ObjectStat,
    ObjectStoreError,
    ObjectStoreUnavailable,
    PresignedPut,
)
from fastapi import APIRouter, HTTPException, Request, Response
from starlette.responses import FileResponse


class ObjectExists(ObjectStoreError):
    pass


class InvalidObject(ObjectStoreError):
    pass


class LocalObjectStore:
    def __init__(
        self,
        root: Path,
        origin: str,
        signing_key: bytes,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.origin = origin.rstrip("/")
        self._key = signing_key
        self._now = now or (lambda: datetime.now(UTC))

    def _directory(self, key: str) -> Path:
        parts = key.split("/")
        if (
            not key
            or "\\" in key
            or any(not part or part.startswith(".") or ":" in part for part in parts)
            or PurePosixPath(key).is_absolute()
        ):
            raise InvalidObject("invalid local object key")
        path = self.root.joinpath(*parts).resolve()
        if not path.is_relative_to(self.root):
            raise InvalidObject("object key escapes managed storage")
        return path

    def put_object(
        self,
        *,
        object_key: str,
        source: BinaryIO,
        size_bytes: int,
        content_type: str,
        checksum_sha256: str,
    ) -> None:
        target = self._directory(object_key)
        if size_bytes < 0 or size_bytes > ARCHIVE_MAX_BYTES:
            raise InvalidObject("object size exceeds desktop storage limit")
        staging_root = self.root / ".staging"
        staging_root.mkdir(exist_ok=True)
        temporary = Path(tempfile.mkdtemp(dir=staging_root))
        try:
            digest = hashlib.sha256()
            size = 0
            with (temporary / "body").open("xb") as destination:
                while chunk := source.read(1024 * 1024):
                    size += len(chunk)
                    if size > size_bytes:
                        raise InvalidObject("object is larger than declared size")
                    digest.update(chunk)
                    destination.write(chunk)
                destination.flush()
                os.fsync(destination.fileno())
            if size != size_bytes or digest.hexdigest() != checksum_sha256:
                raise InvalidObject("object size or SHA256 does not match")
            with (temporary / "metadata.json").open("x", encoding="utf-8") as metadata:
                json.dump(
                    {"size": size, "contentType": content_type, "sha256": checksum_sha256}, metadata
                )
                metadata.flush()
                os.fsync(metadata.fileno())
            target.parent.mkdir(parents=True, exist_ok=True)
            # An existing published directory is nonempty; rename never replaces it.
            if target.exists():
                raise ObjectExists("object already exists")
            try:
                temporary.rename(target)
            except OSError as error:
                if target.exists():
                    raise ObjectExists("object already exists") from error
                raise
        except OSError as error:
            raise ObjectStoreUnavailable("cannot persist desktop object") from error
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)

    def stat(self, *, object_key: str) -> ObjectStat:
        directory = self._directory(object_key)
        try:
            metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
            size = (directory / "body").stat().st_size
            if (
                not isinstance(metadata, dict)
                or metadata.get("size") != size
                or not isinstance(metadata.get("contentType"), str)
                or not isinstance(metadata.get("sha256"), str)
                or len(metadata["sha256"]) != 64
            ):
                raise ObjectStoreUnavailable("desktop object metadata is invalid")
            return ObjectStat(size, metadata["contentType"], metadata["sha256"])
        except FileNotFoundError as error:
            raise ObjectNotFound() from error
        except (OSError, ValueError) as error:
            raise ObjectStoreUnavailable("cannot read desktop object metadata") from error

    @contextmanager
    def open_object(self, *, object_key: str) -> Iterator[BinaryIO]:
        try:
            with (self._directory(object_key) / "body").open("rb") as source:
                yield source
        except FileNotFoundError as error:
            raise ObjectNotFound() from error
        except OSError as error:
            raise ObjectStoreUnavailable("cannot read desktop object") from error

    def delete_object(self, *, object_key: str) -> None:
        path = self._directory(object_key)
        try:
            if path.exists():
                shutil.rmtree(path)
        except OSError as error:
            raise ObjectStoreUnavailable("cannot delete desktop object") from error

    def check_ready(self) -> None:
        if not self.root.is_dir():
            raise ObjectStoreUnavailable("desktop object directory is unavailable")

    def close(self) -> None:
        pass

    def _signature(self, method: str, key: str, parameters: dict[str, str]) -> str:
        payload = json.dumps(
            [method, key, parameters], sort_keys=True, separators=(",", ":")
        ).encode()
        return hmac.new(self._key, payload, hashlib.sha256).hexdigest()

    def _url(
        self, method: str, key: str, expires_in: timedelta, **parameters: str
    ) -> tuple[str, datetime]:
        self._directory(key)
        if expires_in.total_seconds() <= 0:
            raise InvalidObject("object URL expiry must be positive")
        expires = self._now() + expires_in
        parameters["expires"] = str(int(expires.timestamp()))
        parameters["signature"] = self._signature(method, key, parameters)
        return (
            f"{self.origin}/desktop/objects/{quote(key, safe='/')}?{urlencode(parameters)}",
            expires,
        )

    def presign_put(
        self, *, object_key: str, content_type: str, checksum_sha256: str, expires_in: timedelta
    ) -> PresignedPut:
        try:
            checksum = bytes.fromhex(checksum_sha256)
        except ValueError as error:
            raise InvalidObject("invalid SHA256") from error
        if len(checksum) != 32:
            raise InvalidObject("invalid SHA256")
        url, expires = self._url(
            "PUT", object_key, expires_in, contentType=content_type, checksum=checksum_sha256
        )
        return PresignedPut(
            url,
            {
                "Content-Type": content_type,
                "x-amz-checksum-sha256": base64.b64encode(checksum).decode(),
                "If-None-Match": "*",
            },
            expires,
        )

    def presign_get(self, *, object_key: str, download_name: str, expires_in: timedelta) -> str:
        return self._url("GET", object_key, expires_in, downloadName=download_name)[0]

    def _authorize(self, request: Request, key: str) -> dict[str, str]:
        parameters = dict(request.query_params)
        signature = parameters.pop("signature", "")
        try:
            expires = int(parameters["expires"])
        except (KeyError, ValueError):
            raise HTTPException(403, "invalid object signature") from None
        if expires < self._now().timestamp() or not hmac.compare_digest(
            signature, self._signature(request.method, key, parameters)
        ):
            raise HTTPException(403, "invalid or expired object signature")
        return parameters

    def router(self) -> APIRouter:
        router = APIRouter(include_in_schema=False)

        @router.put("/desktop/objects/{key:path}")
        async def upload(key: str, request: Request) -> Response:
            parameters = self._authorize(request, key)
            checksum = parameters.get("checksum", "")
            content_type = parameters.get("contentType", "")
            try:
                checksum_header = base64.b64encode(bytes.fromhex(checksum)).decode()
            except ValueError:
                raise HTTPException(422, "invalid checksum") from None
            if (
                request.headers.get("if-none-match") != "*"
                or request.headers.get("content-type") != content_type
                or request.headers.get("x-amz-checksum-sha256") != checksum_header
            ):
                raise HTTPException(422, "upload headers do not match signed intent")
            with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024) as source:
                size = 0
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > ARCHIVE_MAX_BYTES:
                        raise HTTPException(413, "upload exceeds desktop storage limit")
                    source.write(chunk)
                source.seek(0)
                try:
                    self.put_object(
                        object_key=key,
                        source=source,
                        size_bytes=size,
                        content_type=content_type,
                        checksum_sha256=checksum,
                    )
                except ObjectExists:
                    raise HTTPException(409, "object already exists") from None
                except InvalidObject:
                    raise HTTPException(422, "upload checksum or size does not match") from None
                except ObjectStoreUnavailable:
                    raise HTTPException(503, "desktop object storage is unavailable") from None
            return Response(headers={"ETag": f'"{checksum}"', "Cache-Control": "private, no-store"})

        @router.get("/desktop/objects/{key:path}")
        def download(key: str, request: Request) -> FileResponse:
            parameters = self._authorize(request, key)
            try:
                self.stat(object_key=key)
            except ObjectNotFound:
                raise HTTPException(404, "object not found") from None
            except ObjectStoreError:
                raise HTTPException(503, "desktop object storage is unavailable") from None
            name = parameters.get("downloadName", "download").replace("/", "_").replace("\\", "_")
            return FileResponse(
                self._directory(key) / "body",
                media_type="application/octet-stream",
                headers={
                    "Cache-Control": "private, no-store",
                    "Content-Disposition": f"attachment; filename*=UTF-8''{quote(name, safe='')}",
                    "X-Content-Type-Options": "nosniff",
                },
            )

        return router
