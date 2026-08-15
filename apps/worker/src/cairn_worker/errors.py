from dataclasses import dataclass
from datetime import timedelta

from cairn_api.knowledge.models import INGESTION_ERROR_CODES

SAFE_DETAIL_MAX_LENGTH = 1024
MAX_RETRY_DELAY = timedelta(days=1)

SAFE_DETAIL_TEMPLATES = {
    "archive_duplicate_path": "archive contains a duplicate entry path",
    "archive_encrypted": "encrypted archives are not supported",
    "archive_limit_exceeded": "archive exceeds an ingestion safety limit",
    "archive_nested": "nested archives are not supported",
    "archive_path_unsafe": "archive entry path is unsafe",
    "database_unavailable": "worker database operation failed",
    "embedding_dimension_mismatch": "embedding dimensions do not match the active profile",
    "embedding_unavailable": "embedding provider is unavailable",
    "encrypted_pdf_unsupported": "encrypted PDF files are not supported",
    "file_too_large": "file exceeds the ingestion size limit",
    "ingestion_retry_exhausted": "automatic ingestion retries are exhausted",
    "lease_lost": "worker no longer owns the job lease",
    "no_extractable_text": "document contains no supported extractable text",
    "object_store_unavailable": "object storage is unavailable",
    "parser_failed": "worker handler or parser failed",
    "unsupported_media_type": "file media type is not supported",
    "upload_checksum_mismatch": "uploaded object checksum does not match",
    "upload_expired": "upload session expired before completion",
    "upload_media_type_mismatch": "uploaded object media type does not match",
    "upload_object_missing": "uploaded object is missing",
    "upload_size_mismatch": "uploaded object size does not match",
}

RETRY_DELAYS = (
    timedelta(seconds=5),
    timedelta(seconds=30),
    timedelta(minutes=2),
    timedelta(minutes=10),
)

PERMANENT_ERROR_CODES = frozenset(
    {
        "archive_duplicate_path",
        "archive_encrypted",
        "archive_limit_exceeded",
        "archive_nested",
        "archive_path_unsafe",
        "embedding_dimension_mismatch",
        "encrypted_pdf_unsupported",
        "file_too_large",
        "no_extractable_text",
        "unsupported_media_type",
        "upload_checksum_mismatch",
        "upload_media_type_mismatch",
    }
)


def safe_detail_for(code: str) -> str:
    if code not in INGESTION_ERROR_CODES:
        raise ValueError(f"unknown worker failure code: {code}")
    detail = SAFE_DETAIL_TEMPLATES[code]
    if len(detail) > SAFE_DETAIL_MAX_LENGTH:
        raise RuntimeError("worker safe-detail template exceeds its storage boundary")
    return detail


@dataclass
class WorkerFailure(Exception):
    code: str
    safe_detail: str
    retryable: bool
    retry_after: timedelta | None = None

    def __post_init__(self) -> None:
        self.safe_detail = safe_detail_for(self.code)
        if self.retry_after is not None and self.retry_after < timedelta(0):
            raise ValueError("retry_after cannot be negative")
        Exception.__init__(self, self.code, self.safe_detail)

    @classmethod
    def for_code(
        cls,
        code: str,
        safe_detail: str,
        *,
        retry_after: timedelta | None = None,
    ) -> "WorkerFailure":
        return cls(
            code=code,
            safe_detail=safe_detail,
            retryable=code not in PERMANENT_ERROR_CODES,
            retry_after=retry_after,
        )


def retry_delay(attempt: int, failure: WorkerFailure) -> timedelta:
    if attempt < 1 or attempt > len(RETRY_DELAYS):
        raise ValueError("attempt must identify one of the four automatic retry delays")
    delay = RETRY_DELAYS[attempt - 1]
    if failure.retry_after is not None:
        delay = max(delay, failure.retry_after)
    return min(delay, MAX_RETRY_DELAY)


__all__ = [
    "MAX_RETRY_DELAY",
    "PERMANENT_ERROR_CODES",
    "RETRY_DELAYS",
    "SAFE_DETAIL_MAX_LENGTH",
    "WorkerFailure",
    "retry_delay",
    "safe_detail_for",
]
