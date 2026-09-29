"""Persist bounded Feishu outcomes in the effective job transaction."""

from datetime import datetime, timedelta
from uuid import UUID

from cairn_api.knowledge.source_models import KnowledgeSource, KnowledgeSourceSync
from cairn_api.projects.models import Project
from sqlalchemy import select
from sqlalchemy.orm import Session

from cairn_worker.errors import WorkerFailure
from cairn_worker.leases import ClaimedJob

SAFE_FEISHU_CODES = frozenset({
    "feishu_access_denied", "feishu_auth_failed", "feishu_document_changed",
    "feishu_invalid_response", "feishu_not_found", "feishu_rate_limited",
    "feishu_redirect_rejected", "feishu_request_rejected", "feishu_response_too_large",
    "feishu_unavailable", "feishu_unexpected", "feishu_credentials_invalid",
    "feishu_credentials_not_found", "feishu_credentials_unexpected",
    "feishu_resource_deleted",
})


class FeishuSyncFailure(WorkerFailure):
    def __init__(
        self, *, code: str, source_id: UUID, generation: int,
        retryable: bool, checked: bool, retry_after: timedelta | None = None,
    ) -> None:
        if code not in SAFE_FEISHU_CODES:
            raise ValueError("unsafe Feishu failure code")
        super().__init__("parser_failed", "", retryable=retryable, retry_after=retry_after)
        self.failure_code = code
        self.source_id = source_id
        self.generation = generation
        self.checked = checked


def persist_feishu_failure(
    session: Session, *, claim: ClaimedJob, failure: FeishuSyncFailure, now: datetime,
) -> None:
    # Caller already proved and consumed this lease through fail_job in this transaction.
    project = session.scalar(select(Project).where(
        Project.id == claim.project_id, Project.org_id == claim.org_id,
    ).with_for_update())
    if project is None:
        return
    source = session.scalar(select(KnowledgeSource).where(
        KnowledgeSource.id == failure.source_id,
        KnowledgeSource.org_id == claim.org_id,
        KnowledgeSource.project_id == claim.project_id,
    ).with_for_update())
    sync = session.scalar(select(KnowledgeSourceSync).where(
        KnowledgeSourceSync.id == claim.target_id,
        KnowledgeSourceSync.source_id == failure.source_id,
        KnowledgeSourceSync.org_id == claim.org_id,
        KnowledgeSourceSync.project_id == claim.project_id,
    ).with_for_update())
    if sync is None or sync.source_generation != failure.generation:
        return
    sync.failure_code = failure.failure_code
    if source is None or source.generation != failure.generation or source.status != "configured":
        return
    if failure.checked:
        source.last_checked_at = now
    source.last_error_code = failure.failure_code
    if failure.failure_code == "feishu_access_denied":
        source.access_state = "access_denied"
    elif failure.failure_code == "feishu_not_found":
        source.access_state = "not_found"
    elif failure.failure_code.startswith("feishu_credentials_") or failure.failure_code == "feishu_auth_failed":
        source.access_state = "unverified"
    source.updated_at = now
