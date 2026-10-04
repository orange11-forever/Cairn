import hashlib
import re
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from cairn_api.auth.models import User
from cairn_api.auth.schemas import IdentityContextResponse
from cairn_api.authorization.policy import AuthorizationPolicy
from cairn_api.authorization.repository import get_current_membership_role
from cairn_api.authorization.types import ProjectPermission
from cairn_api.errors import ApiProblem
from cairn_api.knowledge import repository
from cairn_api.knowledge.content_schemas import KnowledgeContent, KnowledgeContentHighlight
from cairn_api.knowledge.models import KnowledgeResource, ResourceVersionStatus
from cairn_api.knowledge.object_store import ObjectNotFound, ObjectStore, ObjectStoreUnavailable

MAX_PREVIEW_BYTES = 1024 * 1024
MAX_PREVIEW_LINES = 20_000
_CONTROLS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def _problem(status: int, code: str, message: str) -> ApiProblem:
    return ApiProblem(status_code=status, code=code, message=message)


def _missing() -> ApiProblem:
    return _problem(404, "not_found", "资源不存在")


def _changed() -> ApiProblem:
    return _problem(409, "knowledge_changed", "资料版本已变化，请重新打开资料")


@dataclass(frozen=True)
class ContentObservation:
    resource_id: UUID
    version_id: UUID
    title: str
    media_type: str
    size_bytes: int
    sha256: str
    object_key: str
    chunk_id: UUID | None
    chunk_text: str | None
    line_start: int | None
    line_end: int | None


def _highlight(observation: ContentObservation, content: str) -> KnowledgeContentHighlight | None:
    if observation.chunk_id is None:
        return None
    start, end, text = observation.line_start, observation.line_end, observation.chunk_text
    lines = content.split("\n")
    if (
        start is None
        or end is None
        or not 1 <= start <= end <= len(lines)
        or not text
        or not text.strip()
    ):
        raise _missing()
    window = "\n".join(lines[start - 1 : end])
    first = window.find(text)
    exact = first >= 0 and window.find(text, first + 1) < 0
    if exact:
        refined_start = start + window[:first].count("\n")
        refined_end = refined_start + text.count("\n")
    else:
        refined_start, refined_end = start, end
    return KnowledgeContentHighlight(
        chunk_id=observation.chunk_id,
        line_start=refined_start,
        line_end=refined_end,
        text=text,
        match_type="exact" if exact else "range",
    )


class KnowledgeContentService:
    def __init__(self, session: Session, object_store: ObjectStore) -> None:
        self._session = session
        self._object_store = object_store

    def _observe(
        self,
        identity: IdentityContextResponse,
        project_id: UUID,
        resource_id: UUID,
        version_id: UUID | None,
        chunk_id: UUID | None,
    ) -> ContentObservation:
        # Authentication restored the user before this service, but deactivation
        # can commit while object I/O is in progress. Select the current scalar
        # in each observation rather than reusing the request's live ORM row.
        if (
            self._session.scalar(select(User.is_active).where(User.id == identity.user.id))
            is not True
        ):
            raise _problem(401, "session_invalid", "会话无效或已过期")
        # Read scalar role from the database; request-time identity and ORM objects
        # may be stale after commit (the session deliberately keeps them alive).
        role = get_current_membership_role(
            self._session,
            org_id=identity.organization.id,
            membership_id=identity.membership.id,
            user_id=identity.user.id,
        )
        if role is None:
            raise _missing()
        current_identity = identity.model_copy(
            update={
                "membership": identity.membership.model_copy(update={"role": role}),
            }
        )
        policy = AuthorizationPolicy(self._session)
        if policy.find_project(current_identity, project_id, ProjectPermission.READ) is None:
            raise _missing()
        access_filter = policy.project_filter(
            current_identity,
            ProjectPermission.READ,
            cast(ColumnElement[UUID], KnowledgeResource.project_id),
        )
        result = repository.get_active_resource(
            self._session,
            org_id=identity.organization.id,
            project_id=project_id,
            resource_id=resource_id,
            access_filter=access_filter,
        )
        if result is None:
            raise _missing()
        resource, version = result
        if version is None or version.status != ResourceVersionStatus.READY:
            raise _missing()
        if version_id is not None and version.id != version_id:
            raise _changed()
        text, start, end = None, None, None
        if chunk_id is not None:
            context = repository.get_chunk_context(
                self._session,
                org_id=identity.organization.id,
                project_id=project_id,
                resource_id=resource_id,
                chunk_id=chunk_id,
                access_filter=access_filter,
            )
            if context is None or context[0].id != version.id:
                raise _missing()
            chunk = context[1]
            locator = chunk.locator
            text = chunk.text
            if version.media_type in {"text/plain", "text/markdown"}:
                if locator.get("type") not in {"text", "markdown"}:
                    raise _missing()
                raw_start, raw_end = locator.get("lineStart"), locator.get("lineEnd")
                if type(raw_start) is not int or type(raw_end) is not int:
                    raise _missing()
                start, end = raw_start, raw_end
        return ContentObservation(
            resource.id,
            version.id,
            resource.title,
            version.media_type,
            version.size_bytes,
            version.sha256,
            version.object_key,
            chunk_id,
            text,
            start,
            end,
        )

    def get_content(
        self,
        *,
        identity: IdentityContextResponse,
        project_id: UUID,
        resource_id: UUID,
        version_id: UUID | None = None,
        chunk_id: UUID | None = None,
    ) -> KnowledgeContent:
        if chunk_id is not None and version_id is None:
            raise _problem(422, "validation_error", "请求参数无效")
        with self._session.begin():
            before = self._observe(identity, project_id, resource_id, version_id, chunk_id)
        if before.media_type not in {"text/markdown", "text/plain"}:
            raise _problem(415, "preview_unsupported", "该格式暂不支持全文预览，请下载原文件")
        if before.size_bytes > MAX_PREVIEW_BYTES:
            raise _problem(413, "preview_too_large", "资料超过全文预览限制，请下载原文件")
        try:
            payload = bytearray()
            with self._object_store.open_object(object_key=before.object_key) as source:
                while True:
                    chunk = cast(
                        object, source.read(min(64 * 1024, MAX_PREVIEW_BYTES - len(payload) + 1))
                    )
                    if not isinstance(chunk, bytes):
                        raise TypeError("object stream returned non-bytes")
                    if not chunk:
                        break
                    payload.extend(chunk)
                    if len(payload) > MAX_PREVIEW_BYTES:
                        raise _problem(
                            413, "preview_too_large", "资料超过全文预览限制，请下载原文件"
                        )
            if (
                len(payload) != before.size_bytes
                or hashlib.sha256(payload).hexdigest() != before.sha256
            ):
                raise _problem(503, "content_unavailable", "资料内容暂时不可用，请稍后重试")
            content = payload.decode("utf-8-sig", errors="strict")
            content = _CONTROLS.sub("", content.replace("\r\n", "\n").replace("\r", "\n"))
        except (ObjectNotFound, ObjectStoreUnavailable, OSError):
            raise _problem(503, "content_unavailable", "资料内容暂时不可用，请稍后重试") from None
        except UnicodeDecodeError:
            raise _problem(
                415, "preview_unsupported", "资料编码不支持全文预览，请下载原文件"
            ) from None
        line_count = content.count("\n") + 1
        if line_count > MAX_PREVIEW_LINES:
            raise _problem(413, "preview_too_large", "资料超过全文预览限制，请下载原文件")
        # Force fresh ORM values as well as a fresh transaction and scalar role.
        self._session.expire_all()
        with self._session.begin():
            after = self._observe(identity, project_id, resource_id, version_id, chunk_id)
            if before != after:
                raise _changed()
        return KnowledgeContent(
            resource_id=before.resource_id,
            resource_version_id=before.version_id,
            title=before.title,
            media_type=before.media_type,
            format="markdown" if before.media_type == "text/markdown" else "text",
            content=content,
            line_count=line_count,
            highlight=_highlight(before, content),
        )
