import hashlib
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from io import BytesIO
from typing import BinaryIO
from uuid import UUID, uuid4

import pytest
from cairn_api.app import create_app
from cairn_api.auth.models import User
from cairn_api.authorization.models import ResourceAclEntry
from cairn_api.authorization.types import MembershipRole
from cairn_api.db.session import Database
from cairn_api.errors import ErrorBody
from cairn_api.knowledge import repository
from cairn_api.knowledge.models import KnowledgeChunk, KnowledgeResource, KnowledgeResourceVersion
from cairn_api.knowledge.object_store import ObjectNotFound, ObjectStoreUnavailable
from cairn_api.knowledge.source_models import KnowledgeSource
from cairn_api.organizations.models import Membership
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import delete, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from .authorization_helpers import APP_ORIGIN, seed_actor
from .knowledge_helpers import MemoryObjectStore, knowledge_client, knowledge_settings, seed_project
from .test_knowledge_resource_api import _seed_ready_resource  # pyright: ignore[reportPrivateUsage]


class TextStore(MemoryObjectStore):
    def __init__(self, payload: bytes) -> None:
        super().__init__()
        self.payload = payload
        self.closed = False

    @contextmanager
    def open_object(self, *, object_key: str) -> Generator[BinaryIO, None, None]:  # pyright: ignore[reportIncompatibleMethodOverride]
        del object_key
        with BytesIO(self.payload) as stream:
            yield stream
        self.closed = True


def seed_text(
    database: Database, org_id: UUID, project_id: UUID, payload: bytes
) -> tuple[UUID, UUID, UUID]:
    resource_id, version_id, chunks = _seed_ready_resource(
        database,
        org_id=org_id,
        project_id=project_id,
        title="Preview.md",
        created_at=datetime.now(UTC),
    )
    with database.session_factory.begin() as session:
        version = session.get(KnowledgeResourceVersion, version_id)
        assert version is not None
        version.media_type = "text/markdown"
        version.size_bytes = len(payload)
        version.sha256 = hashlib.sha256(payload).hexdigest()
        for chunk_id in chunks:
            chunk = session.get(KnowledgeChunk, chunk_id)
            assert chunk is not None
            chunk.text = "中间引用"
            chunk.locator = {"type": "markdown", "headingPath": [], "lineStart": 1, "lineEnd": 5}
    return resource_id, version_id, chunks[0]


def assert_boundary(response: Response, status: int, request_id: str) -> None:
    assert response.status_code == status
    assert response.headers["x-request-id"] == request_id
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["access-control-allow-origin"] == APP_ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"
    assert {
        header.strip().lower()
        for header in response.headers["access-control-expose-headers"].split(",")
    } == {"retry-after", "x-request-id"}
    assert response.headers["content-type"].startswith("application/json")
    assert "set-cookie" not in response.headers
    if status != 200:
        body = response.json()
        assert set(body) == {"message", "code", "traceId"}
        assert body["traceId"] == request_id
        assert (
            ErrorBody.model_validate(
                {"message": body["message"], "code": body["code"], "trace_id": body["traceId"]}
            ).model_dump(by_alias=True)
            == body
        )


@pytest.mark.integration
def test_complete_normalized_text_and_authoritative_exact_citation(
    database: Database, test_database_url: str
) -> None:
    payload = "\ufeff# 标题\r\n\r\n中间\x00引用\r\n\r\nEOF完整正文\r\n".encode()
    actor = seed_actor(database, MembershipRole.MEMBER)
    project_id = seed_project(database, actor, permission="read")
    resource_id, version_id, chunk_id = seed_text(
        database, actor.organization_id, project_id, payload
    )
    store = TextStore(payload)
    with knowledge_client(knowledge_settings(test_database_url), database, actor, store) as client:
        response = client.get(
            f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}/content",
            params={"version_id": str(version_id), "chunk_id": str(chunk_id)},
            headers={"X-Request-ID": "req-content-success"},
        )
    assert_boundary(response, 200, "req-content-success")
    assert response.json() == {
        "resourceId": str(resource_id),
        "resourceVersionId": str(version_id),
        "title": "Preview.md",
        "mediaType": "text/markdown",
        "format": "markdown",
        "content": "# 标题\n\n中间引用\n\nEOF完整正文\n",
        "lineCount": 6,
        "highlight": {
            "chunkId": str(chunk_id),
            "lineStart": 3,
            "lineEnd": 3,
            "text": "中间引用",
            "matchType": "exact",
        },
    }
    assert store.closed


@pytest.mark.integration
@pytest.mark.parametrize(
    ("kind", "status", "code"),
    [
        ("missing_version", 422, "validation_error"),
        ("stale_version", 409, "knowledge_changed"),
        ("wrong_chunk", 404, "not_found"),
        ("foreign_chunk", 404, "not_found"),
        ("binary", 415, "preview_unsupported"),
        ("binary_citation", 415, "preview_unsupported"),
        ("encoding", 415, "preview_unsupported"),
        ("large", 413, "preview_too_large"),
        ("large_actual", 413, "preview_too_large"),
        ("integrity", 503, "content_unavailable"),
        ("not_ready", 404, "not_found"),
    ],
)
def test_preview_rejects_invalid_or_unsafe_content(
    database: Database, test_database_url: str, kind: str, status: int, code: str
) -> None:
    payload = b"first\nsecond\nthird\nfourth\nlast"
    if kind == "encoding":
        payload = b"\xff"
    if kind in {"large", "large_actual"}:
        payload = b"x" * (1024 * 1024 + 1)
    actor = seed_actor(database, MembershipRole.MEMBER)
    project_id = seed_project(database, actor, permission="read")
    resource_id, version_id, chunk_id = seed_text(
        database, actor.organization_id, project_id, payload
    )
    with database.session_factory.begin() as session:
        version = session.get(KnowledgeResourceVersion, version_id)
        assert version is not None
        if kind in {"binary", "binary_citation"}:
            version.media_type = "application/pdf"
        if kind == "binary_citation":
            chunk = session.get(KnowledgeChunk, chunk_id)
            assert chunk is not None
            chunk.locator = {"type": "pdf", "page": 1}
        if kind == "not_ready":
            version.status = "processing"
            version.ready_at = None
        if kind == "integrity":
            version.sha256 = "0" * 64
        if kind == "large_actual":
            version.size_bytes = 1
    params: dict[str, str] = {}
    if kind == "missing_version":
        params = {"chunk_id": str(chunk_id)}
    if kind == "stale_version":
        params = {"version_id": str(uuid4())}
    if kind == "wrong_chunk":
        params = {"version_id": str(version_id), "chunk_id": str(uuid4())}
    if kind == "foreign_chunk":
        _, _, other_chunk_id = seed_text(database, actor.organization_id, project_id, payload)
        params = {"version_id": str(version_id), "chunk_id": str(other_chunk_id)}
    if kind == "binary_citation":
        params = {"version_id": str(version_id), "chunk_id": str(chunk_id)}
    with knowledge_client(
        knowledge_settings(test_database_url), database, actor, TextStore(payload)
    ) as client:
        response = client.get(
            f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}/content",
            params=params,
            headers={"X-Request-ID": "req-content-rejected"},
        )
    assert_boundary(response, status, "req-content-rejected")
    assert response.json()["code"] == code
    assert "object_key" not in response.text


@pytest.mark.integration
@pytest.mark.parametrize(
    ("failure", "status", "code"),
    [
        (ObjectNotFound(), 503, "content_unavailable"),
        (ObjectStoreUnavailable(), 503, "content_unavailable"),
        (OSError("private storage path"), 503, "content_unavailable"),
        (RuntimeError("private storage path"), 500, "internal_error"),
        (
            OperationalError("SELECT private", {}, Exception("private database path")),
            503,
            "database_unavailable",
        ),
    ],
)
def test_storage_and_unexpected_failures_preserve_http_contract(
    database: Database, test_database_url: str, failure: Exception, status: int, code: str
) -> None:
    actor = seed_actor(database, MembershipRole.MEMBER)
    project_id = seed_project(database, actor, permission="read")
    resource_id, _, _ = seed_text(database, actor.organization_id, project_id, b"preview")

    class FailedStore(TextStore):
        @contextmanager
        def open_object(self, *, object_key: str) -> Generator[BinaryIO, None, None]:
            del object_key
            raise failure
            yield  # pragma: no cover

    with knowledge_client(
        knowledge_settings(test_database_url), database, actor, FailedStore(b"preview")
    ) as client:
        response = client.get(
            f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}/content",
            headers={"X-Request-ID": "req-content-failure"},
        )
    assert_boundary(response, status, "req-content-failure")
    assert response.json()["code"] == code
    assert "private" not in response.text


@pytest.mark.integration
@pytest.mark.parametrize("mutation", ["acl", "membership", "role", "delete", "version", "user"])
def test_fresh_post_read_authorization_discards_body(
    database: Database, test_database_url: str, mutation: str
) -> None:
    actor = seed_actor(
        database, MembershipRole.OWNER if mutation == "role" else MembershipRole.MEMBER
    )
    project_id = seed_project(database, actor, permission=None if mutation == "role" else "read")
    resource_id, _version_id, _ = seed_text(
        database, actor.organization_id, project_id, b"secret preview"
    )

    class ChangedStore(TextStore):
        @contextmanager
        def open_object(self, *, object_key: str) -> Generator[BinaryIO, None, None]:
            with super().open_object(object_key=object_key) as stream:
                yield stream
            with database.session_factory.begin() as session:
                if mutation == "acl":
                    session.execute(
                        delete(ResourceAclEntry).where(ResourceAclEntry.resource_id == project_id)
                    )
                elif mutation == "membership":
                    session.execute(delete(Membership).where(Membership.id == actor.membership_id))
                elif mutation == "role":
                    session.execute(
                        update(Membership)
                        .where(Membership.id == actor.membership_id)
                        .values(role="member")
                    )
                elif mutation == "delete":
                    session.execute(
                        update(KnowledgeResource)
                        .where(KnowledgeResource.id == resource_id)
                        .values(deleted_at=datetime.now(UTC), deleted_by=actor.user_id)
                    )
                elif mutation == "user":
                    session.execute(
                        update(User).where(User.id == actor.user_id).values(is_active=False)
                    )
                else:
                    session.execute(
                        update(KnowledgeResource)
                        .where(KnowledgeResource.id == resource_id)
                        .values(current_version_id=None)
                    )

    store = ChangedStore(b"secret preview")
    with knowledge_client(knowledge_settings(test_database_url), database, actor, store) as client:
        if mutation == "user":
            assert client.get("/api/v1/session").status_code == 200
            with database.session_factory() as session:
                assert (
                    session.scalar(select(User.is_active).where(User.id == actor.user_id)) is True
                )
        response = client.get(
            f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}/content",
            headers={"X-Request-ID": "req-content-recheck"},
        )
        if mutation == "user":
            assert client.get("/api/v1/session").status_code == 401
    assert_boundary(response, 401 if mutation == "user" else 404, "req-content-recheck")
    if mutation == "user":
        assert response.json() == {
            "code": "session_invalid",
            "message": "会话无效或已过期",
            "traceId": "req-content-recheck",
        }
    assert store.closed
    assert "secret preview" not in response.text


@pytest.mark.integration
def test_auth_validation_methods_and_openapi_contract(
    database: Database, test_database_url: str
) -> None:
    actor = seed_actor(database, MembershipRole.MEMBER)
    project_id = seed_project(database, actor, permission="read")
    path = f"/api/v1/projects/{project_id}/knowledge/resources/{uuid4()}/content"
    with TestClient(
        create_app(knowledge_settings(test_database_url), database, TextStore(b"")),
        raise_server_exceptions=False,
    ) as client:
        response = client.get(
            path, headers={"Origin": APP_ORIGIN, "X-Request-ID": "req-content-auth"}
        )
    assert_boundary(response, 401, "req-content-auth")
    with knowledge_client(
        knowledge_settings(test_database_url), database, actor, TextStore(b"")
    ) as client:
        invalid = client.get(
            path, params={"version_id": "invalid"}, headers={"X-Request-ID": "req-content-invalid"}
        )
        method = client.post(path, headers={"X-Request-ID": "req-content-method"})
        options = client.options(
            path,
            headers={"Access-Control-Request-Method": "GET", "X-Request-ID": "req-content-options"},
        )
        schema = client.get("/openapi.json").json()
    assert_boundary(invalid, 422, "req-content-invalid")
    assert_boundary(method, 405, "req-content-method")
    assert method.headers["allow"] == "GET"
    assert options.status_code == 200
    assert options.headers["cache-control"] == "private, no-store"
    assert options.headers["x-content-type-options"] == "nosniff"
    assert options.headers["access-control-allow-origin"] == APP_ORIGIN
    operation = schema["paths"][
        "/api/v1/projects/{project_id}/knowledge/resources/{resource_id}/content"
    ]["get"]
    assert set(operation["responses"]) == {
        "200",
        "401",
        "404",
        "409",
        "413",
        "415",
        "422",
        "500",
        "503",
    }
    assert {p["name"] for p in operation["parameters"]} == {
        "project_id",
        "resource_id",
        "version_id",
        "chunk_id",
    }


@pytest.mark.integration
@pytest.mark.parametrize(
    ("text", "start", "end", "expected"),
    [
        ("hit", 1, 5, {"lineStart": 2, "lineEnd": 2, "matchType": "exact"}),
        ("repeat", 1, 5, {"lineStart": 1, "lineEnd": 5, "matchType": "range"}),
        ("missing indexed excerpt", 1, 5, {"lineStart": 1, "lineEnd": 5, "matchType": "range"}),
        ("hit", 6, 8, None),
        ("hit", 4, 2, None),
    ],
)
def test_exact_unique_and_honest_range_mapping(
    database: Database,
    test_database_url: str,
    text: str,
    start: int,
    end: int,
    expected: dict[str, object] | None,
) -> None:
    payload = b"start\nhit\nrepeat\nrepeat\nEOF"
    actor = seed_actor(database, MembershipRole.MEMBER)
    project_id = seed_project(database, actor, permission="read")
    resource_id, version_id, chunk_id = seed_text(
        database, actor.organization_id, project_id, payload
    )
    with database.session_factory.begin() as session:
        chunk = session.get(KnowledgeChunk, chunk_id)
        assert chunk is not None
        chunk.text = text
        chunk.locator = {"type": "text", "headingPath": [], "lineStart": start, "lineEnd": end}
    with knowledge_client(
        knowledge_settings(test_database_url), database, actor, TextStore(payload)
    ) as client:
        response = client.get(
            f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}/content",
            params={"version_id": str(version_id), "chunk_id": str(chunk_id)},
            headers={"X-Request-ID": "req-content-map"},
        )
    assert_boundary(response, 404 if expected is None else 200, "req-content-map")
    if expected is not None:
        assert response.json()["highlight"] == {"chunkId": str(chunk_id), "text": text, **expected}


@pytest.mark.integration
@pytest.mark.parametrize("mutation", [None, "disabled", "access_denied", "unverified", "not_found"])
def test_feishu_snapshot_rechecks_current_source_after_read(
    database: Database, test_database_url: str, mutation: str | None
) -> None:
    actor = seed_actor(database, MembershipRole.MEMBER)
    project_id = seed_project(database, actor, permission="read")
    payload = b"snapshot\nfull text\nEOF"
    resource_id, version_id, _ = seed_text(database, actor.organization_id, project_id, payload)
    source_id = uuid4()
    with database.session_factory.begin() as session:
        source = KnowledgeSource(
            id=source_id,
            org_id=actor.organization_id,
            project_id=project_id,
            name="Synthetic snapshot",
            external_id="SyntheticDocument",
            credential_ref="synthetic_fixture",
            access_policy="project_members",
            access_state="available",
        )
        session.add(source)
        for model, model_id in [
            (KnowledgeResource, resource_id),
            (KnowledgeResourceVersion, version_id),
        ]:
            row = session.get(model, model_id)
            assert row is not None
            row.source_type = "feishu"
            row.source_id = str(source_id)
            row.external_id = "SyntheticDocument"
        version = session.get(KnowledgeResourceVersion, version_id)
        assert version is not None
        version.media_type = "text/plain"

    class SourceStore(TextStore):
        @contextmanager
        def open_object(self, *, object_key: str) -> Generator[BinaryIO, None, None]:
            with super().open_object(object_key=object_key) as stream:
                yield stream
            if mutation is not None:
                with database.session_factory.begin() as session:
                    source = session.get(KnowledgeSource, source_id)
                    assert source is not None
                    if mutation == "disabled":
                        source.status = "disabled"
                        source.disabled_at = datetime.now(UTC)
                    else:
                        source.access_state = mutation

    with knowledge_client(
        knowledge_settings(test_database_url), database, actor, SourceStore(payload)
    ) as client:
        response = client.get(
            f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}/content",
            headers={"X-Request-ID": "req-content-source"},
        )
    assert_boundary(response, 200 if mutation is None else 404, "req-content-source")
    if mutation is None:
        assert response.json()["content"] == "snapshot\nfull text\nEOF"
        assert response.json()["resourceVersionId"] == str(version_id)
    else:
        assert "snapshot" not in response.text


@pytest.mark.integration
@pytest.mark.parametrize("stream_failure", [False, True])
def test_bounded_read_closes_stream_and_holds_no_database_transaction(
    database: Database,
    test_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    stream_failure: bool,
) -> None:
    actor = seed_actor(database, MembershipRole.MEMBER)
    project_id = seed_project(database, actor, permission="read")
    payload = b"x" * (1024 * 1024)
    resource_id, _, _ = seed_text(database, actor.organization_id, project_id, payload)
    observed: list[Session] = []
    original = repository.get_active_resource

    def observe(session: Session, **kwargs: object):  # pyright: ignore[reportUnknownParameterType]
        observed.append(session)
        return original(session, **kwargs)  # pyright: ignore[reportArgumentType]

    monkeypatch.setattr(repository, "get_active_resource", observe)
    sizes: list[int] = []
    streams: list[BytesIO] = []

    class BoundedStream(BytesIO):
        def read(self, size: int | None = -1) -> bytes:
            assert size is not None
            assert size > 0 and size <= 64 * 1024
            assert not observed[-1].in_transaction()
            sizes.append(size)
            if stream_failure and len(sizes) == 2:
                raise OSError("synthetic stream failure")
            return super().read(size)

    class BoundedStore(TextStore):
        @contextmanager
        def open_object(self, *, object_key: str) -> Generator[BinaryIO, None, None]:
            del object_key
            with BoundedStream(self.payload) as stream:
                streams.append(stream)
                yield stream

    with knowledge_client(
        knowledge_settings(test_database_url), database, actor, BoundedStore(payload)
    ) as client:
        response = client.get(
            f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}/content",
            headers={"X-Request-ID": "req-content-bound"},
        )
    assert_boundary(response, 503 if stream_failure else 200, "req-content-bound")
    if stream_failure:
        assert response.json()["code"] == "content_unavailable"
    else:
        assert len(response.json()["content"]) == 1024 * 1024
        assert len(sizes) >= 17
    assert all(stream.closed for stream in streams)


@pytest.mark.integration
@pytest.mark.parametrize(("lines", "status"), [(20000, 200), (20001, 413)])
def test_full_preview_line_limit_is_inclusive_and_never_truncates(
    database: Database, test_database_url: str, lines: int, status: int
) -> None:
    payload = ("\n" * (lines - 1) + "EOF").encode()
    actor = seed_actor(database, MembershipRole.MEMBER)
    project_id = seed_project(database, actor, permission="read")
    resource_id, _, _ = seed_text(database, actor.organization_id, project_id, payload)
    store = TextStore(payload)
    with knowledge_client(knowledge_settings(test_database_url), database, actor, store) as client:
        response = client.get(
            f"/api/v1/projects/{project_id}/knowledge/resources/{resource_id}/content",
            headers={"X-Request-ID": "req-content-line-limit"},
        )
    assert_boundary(response, status, "req-content-line-limit")
    assert store.closed
    if status == 200:
        assert response.json()["lineCount"] == 20000
        assert response.json()["content"] == "\n" * 19999 + "EOF"
    else:
        assert response.json()["code"] == "preview_too_large"
        assert "content" not in response.json()
