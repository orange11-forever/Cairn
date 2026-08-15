import hashlib
import os
import time
from contextlib import closing
from datetime import timedelta
from uuid import uuid4

import boto3
import httpx
import pytest
from botocore.config import Config
from botocore.exceptions import ClientError
from cairn_api.knowledge.object_store import (
    Boto3ObjectStore,
    ObjectNotFound,
    ObjectStoreError,
)
from mypy_boto3_s3.client import S3Client


def _endpoint() -> str:
    endpoint = os.environ.get("CAIRN_TEST_S3_ENDPOINT_URL")
    if endpoint is None:
        pytest.skip("CAIRN_TEST_S3_ENDPOINT_URL is required for MinIO integration tests")
    return endpoint


def _cors_origin() -> str:
    return os.environ.get("CAIRN_TEST_CORS_ORIGIN", "http://localhost:5500")


@pytest.mark.integration
def test_minio_checksum_bound_create_only_upload_and_safe_download() -> None:
    endpoint = _endpoint()
    bucket = f"cairn-test-{uuid4().hex}"
    access_key = os.environ.get("CAIRN_OBJECT_STORE_ACCESS_KEY", "cairn-local")
    secret_key = os.environ.get(
        "CAIRN_OBJECT_STORE_SECRET_KEY",
        "cairn-local-only-change-before-deploying",
    )
    raw_client: S3Client = boto3.client(  # pyright: ignore[reportUnknownMemberType]
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="us-east-1",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    store = Boto3ObjectStore(
        bucket=bucket,
        endpoint_url=endpoint,
        public_endpoint_url=endpoint,
        region="us-east-1",
        access_key=access_key,
        secret_key=secret_key,
        path_style=True,
    )
    object_key = f"integration/{uuid4().hex}/document.html"
    expired_object_key = f"integration/{uuid4().hex}/expired.html"
    payload = b"<h1>safe download only</h1>"
    checksum = hashlib.sha256(payload).hexdigest()
    cors_origin = _cors_origin()
    http_client = httpx.Client(trust_env=False)

    try:
        store.bootstrap(allowed_origins=(cors_origin,))
        cors = http_client.options(
            f"{endpoint}/{bucket}/{object_key}",
            headers={
                "Origin": cors_origin,
                "Access-Control-Request-Method": "PUT",
                "Access-Control-Request-Headers": (
                    "content-type,x-amz-checksum-sha256,if-none-match"
                ),
            },
            timeout=10,
        )
        assert cors.status_code == 204
        assert cors.headers["access-control-allow-origin"] == cors_origin
        assert "PUT" in cors.headers["access-control-allow-methods"]
        assert {
            "content-type",
            "x-amz-checksum-sha256",
            "if-none-match",
        }.issubset(
            {header.strip().lower() for header in cors.headers["access-control-allow-headers"].split(",")}
        )

        incorrect = store.presign_put(
            object_key=object_key,
            content_type="text/html",
            checksum_sha256="00" * 32,
            expires_in=timedelta(minutes=5),
        )
        bad_response = http_client.put(
            incorrect.url,
            content=payload,
            headers=incorrect.headers,
            timeout=10,
        )
        assert bad_response.status_code >= 400

        instruction = store.presign_put(
            object_key=object_key,
            content_type="text/html",
            checksum_sha256=checksum,
            expires_in=timedelta(minutes=5),
        )
        upload = http_client.put(
            instruction.url,
            content=payload,
            headers=instruction.headers,
            timeout=10,
        )
        assert upload.status_code in {200, 204}

        overwrite = http_client.put(
            instruction.url,
            content=payload,
            headers=instruction.headers,
            timeout=10,
        )
        assert overwrite.status_code == 412

        stat = store.stat(object_key=object_key)
        assert stat.size_bytes == len(payload)
        assert stat.content_type == "text/html"
        assert stat.checksum_sha256 == checksum

        with store.open_object(object_key=object_key) as source:
            assert source.read() == payload

        download_url = store.presign_get(
            object_key=object_key,
            download_name="报告.html",
            expires_in=timedelta(minutes=5),
        )
        download = http_client.get(download_url, timeout=10)
        assert download.status_code == 200
        assert download.content == payload
        assert download.headers["content-type"].startswith("application/octet-stream")
        assert download.headers["content-disposition"].startswith("attachment;")

        expired_put = store.presign_put(
            object_key=expired_object_key,
            content_type="text/html",
            checksum_sha256=checksum,
            expires_in=timedelta(seconds=1),
        )
        expired_get = store.presign_get(
            object_key=object_key,
            download_name="expired.html",
            expires_in=timedelta(seconds=1),
        )
        time.sleep(2)
        expired_upload = http_client.put(
            expired_put.url,
            content=payload,
            headers=expired_put.headers,
            timeout=10,
        )
        expired_download = http_client.get(expired_get, timeout=10)
        assert expired_upload.status_code == 403
        assert expired_download.status_code == 403

        store.delete_object(object_key=object_key)
        with pytest.raises(ObjectNotFound):
            store.stat(object_key=object_key)
    finally:
        for cleanup_key in (object_key, expired_object_key):
            try:
                store.delete_object(object_key=cleanup_key)
            except ObjectStoreError:
                # Best-effort cleanup after a partial object-store failure.
                pass
        http_client.close()
        store.close()
        with closing(raw_client):
            try:
                raw_client.delete_bucket(Bucket=bucket)
            except ClientError:
                # The bucket may not exist or may still contain a failed upload.
                pass
