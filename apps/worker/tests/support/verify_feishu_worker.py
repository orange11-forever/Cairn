"""Verification-only Worker entrypoint with one synthetic Feishu document.

Never loaded by the normal Worker CLI. Refuses production, non-test databases,
real tenant credentials and every document/alias outside this fixture.
"""

from __future__ import annotations

import json
import os
import re
import socket
from collections.abc import Mapping
from email.message import Message
from io import BytesIO
from typing import cast
from urllib.request import Request
from uuid import UUID

from cairn_api.db.session import Database
from cairn_api.knowledge.models import JobKind
from cairn_api.knowledge.object_store import Boto3ObjectStore
from cairn_api.settings import Settings
from cairn_worker.feishu import FeishuDocumentClient
from cairn_worker.feishu_credentials import FeishuCredentialResolver
from cairn_worker.feishu_sync import build_feishu_sync_handler
from cairn_worker.runner import WorkerRuntime, build_runtime_handlers, main

FIXTURE_ORG = UUID("00000000-0000-4000-8000-000000002001")
FIXTURE_ALIAS = "verify_feishu"
FIXTURE_DOCUMENT_ID = "VerifyDoc2026"
FIXTURE_TITLE = "飞书验收资料"
FIXTURE_PHRASE = "青松协定确认飞书跨区域恢复完成"
FIXTURE_CONTENT = f"{FIXTURE_TITLE}\n{FIXTURE_PHRASE}\n这是一份仅供本地自动化验收的合成文档。\n"
_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
_DOC_URL = f"https://open.feishu.cn/open-apis/docx/v1/documents/{FIXTURE_DOCUMENT_ID}"


def validate_environment(environment: Mapping[str, str]) -> None:
    database_url = environment.get("DATABASE_URL", "")
    if (
        environment.get("CAIRN_ENVIRONMENT") != "test"
        or environment.get("CAIRN_VERIFY_FAKE_FEISHU") != "1"
        or re.fullmatch(r"postgresql\+psycopg://[^/@]+:[^/@]+@127\.0\.0\.1:[0-9]{1,5}/cairn_test", database_url) is None
        or environment.get("CAIRN_FEISHU_CREDENTIALS_JSON") != "{}"
        or any(key.startswith("FEISHU_TEST_") for key in environment)
    ):
        raise RuntimeError("fake Feishu Worker requires isolated verification settings")


class FixtureResponse(BytesIO):
    status = 200

    def __init__(self, payload: dict[str, object]) -> None:
        super().__init__(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        self.headers = Message()


class FixtureOpener:
    def open(self, request: Request, *, timeout: float) -> FixtureResponse:
        if not 0 < timeout <= 60:
            raise OSError("invalid verification timeout")
        if request.full_url == _TOKEN_URL and request.get_method() == "POST":
            body = request.data
            if not isinstance(body, bytes):
                raise OSError("unexpected fixture credential request")
            credentials = json.loads(body)
            if credentials != {"app_id": "fixture-app", "app_secret": "fixture-secret"}:
                raise OSError("unexpected fixture credentials")
            return FixtureResponse({"code": 0, "tenant_access_token": "fixture-token", "expire": 3600})
        if request.full_url == _DOC_URL and request.get_method() == "GET":
            return FixtureResponse({"code": 0, "data": {"document": {
                "document_id": FIXTURE_DOCUMENT_ID, "revision_id": 1, "title": FIXTURE_TITLE,
            }}})
        if request.full_url == f"{_DOC_URL}/raw_content" and request.get_method() == "GET":
            return FixtureResponse({"code": 0, "data": {"content": FIXTURE_CONTENT}})
        raise OSError("document outside fake Feishu verification allowlist")


class FixtureResolver:
    def create_client(self, *, org_id: UUID, credential_ref: str) -> FeishuDocumentClient:
        if org_id != FIXTURE_ORG or credential_ref != FIXTURE_ALIAS:
            raise OSError("source outside fake Feishu verification allowlist")
        opener = FixtureOpener()
        return FeishuDocumentClient(
            app_id="fixture-app", app_secret="fixture-secret",
            opener_factory=lambda *_handlers: opener,
        )


def run() -> int:
    validate_environment(os.environ)
    settings = Settings()
    database = Database(settings.database_url)
    try:
        object_store = Boto3ObjectStore.from_settings(settings)
    except Exception:
        database.dispose()
        raise
    handlers = build_runtime_handlers(
        settings=settings, object_store=object_store,
        session_factory=database.session_factory,
    )
    handlers[JobKind.SYNC_FEISHU_SOURCE] = build_feishu_sync_handler(
        object_store=object_store, resolver=cast(FeishuCredentialResolver, FixtureResolver()),
    )
    runtime = WorkerRuntime(
        settings=settings, database=database, object_store=object_store,
        handlers=handlers, worker_id=f"verify-feishu:{socket.gethostname()}:{os.getpid()}",
    )
    try:
        return main(["serve"], runtime=runtime)
    finally:
        runtime.close()


if __name__ == "__main__":
    raise SystemExit(run())
