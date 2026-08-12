from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import BinaryIO
from uuid import UUID, uuid4

from cairn_api.app import create_app
from cairn_api.authorization.models import ResourceAclEntry
from cairn_api.db.session import Database
from cairn_api.knowledge.object_store import (
    ObjectNotFound,
    ObjectStat,
    ObjectStore,
    PresignedPut,
)
from cairn_api.projects.models import Project
from cairn_api.settings import Settings
from fastapi.testclient import TestClient

from .authorization_helpers import APP_ORIGIN, SeededActor


class MemoryObjectStore:
    def __init__(self, *, now: datetime | None = None) -> None:
        self.now = now or datetime.now(UTC)
        self.objects: dict[str, ObjectStat] = {}
        self.presigned_keys: list[str] = []
        self.stat_calls: list[str] = []

    def presign_put(
        self,
        *,
        object_key: str,
        content_type: str,
        checksum_sha256: str,
        expires_in: timedelta,
    ) -> PresignedPut:
        self.presigned_keys.append(object_key)
        return PresignedPut(
            url=f"https://objects.example/{object_key}",
            headers={
                "Content-Type": content_type,
                "x-amz-checksum-sha256": checksum_sha256,
                "If-None-Match": "*",
            },
            expires_at=self.now + expires_in,
        )

    def stat(self, *, object_key: str) -> ObjectStat:
        self.stat_calls.append(object_key)
        try:
            return self.objects[object_key]
        except KeyError:
            raise ObjectNotFound() from None

    def open_object(self, *, object_key: str) -> BinaryIO:
        if object_key not in self.objects:
            raise ObjectNotFound()
        return BytesIO()

    def put_object(
        self,
        *,
        object_key: str,
        source: BinaryIO,
        size_bytes: int,
        content_type: str,
        checksum_sha256: str,
    ) -> None:
        del source
        self.objects[object_key] = ObjectStat(
            size_bytes=size_bytes,
            content_type=content_type,
            checksum_sha256=checksum_sha256,
        )

    def presign_get(
        self,
        *,
        object_key: str,
        download_name: str,
        expires_in: timedelta,
    ) -> str:
        del download_name, expires_in
        return f"https://objects.example/{object_key}"

    def delete_object(self, *, object_key: str) -> None:
        self.objects.pop(object_key, None)

    def check_ready(self) -> None:
        return None

    def close(self) -> None:
        return None


def knowledge_settings(test_database_url: str, **overrides: object) -> Settings:
    return Settings(
        environment="test",
        database_url=test_database_url,
        app_url=APP_ORIGIN,
        cors_origins=[APP_ORIGIN],
        csrf_secret="test-only-csrf-secret-with-at-least-32-bytes",
        auth_rate_limit_secret="test-only-auth-rate-limit-secret-with-at-least-32-bytes",
        _env_file=None,  # pyright: ignore[reportCallIssue]
        **overrides,
    )


def seed_project(
    database: Database,
    actor: SeededActor,
    *,
    permission: str | None,
    org_id: UUID | None = None,
) -> UUID:
    project_id = uuid4()
    project_org_id = org_id or actor.organization_id
    with database.session_factory.begin() as session:
        session.add(
            Project(
                id=project_id,
                org_id=project_org_id,
                name="Knowledge upload project",
            )
        )
        if permission is not None:
            session.add(
                ResourceAclEntry(
                    org_id=project_org_id,
                    resource_type="project",
                    resource_id=project_id,
                    principal_type="user",
                    principal_id=str(actor.user_id),
                    permission=permission,
                    granted_by_type="system",
                )
            )
    return project_id


@contextmanager
def knowledge_client(
    settings: Settings,
    database: Database,
    actor: SeededActor,
    object_store: ObjectStore,
) -> Generator[TestClient, None, None]:
    with TestClient(
        create_app(settings, database, object_store),
        raise_server_exceptions=False,
    ) as client:
        response = client.post(
            "/api/v1/login",
            headers={"Origin": APP_ORIGIN},
            json={"email": actor.email, "password": actor.password},
        )
        assert response.status_code == 200
        client.headers.update(
            {
                "Origin": APP_ORIGIN,
                "X-CSRF-Token": response.json()["csrfToken"],
            }
        )
        yield client


__all__ = [
    "MemoryObjectStore",
    "knowledge_client",
    "knowledge_settings",
    "seed_project",
]
