from dataclasses import dataclass
from datetime import timedelta

from cairn_api.knowledge.models import INGESTION_ERROR_CODES

SAFE_DETAIL_MAX_LENGTH = 1024

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


def _sanitize_detail(value: str) -> str:
    return " ".join(value.splitlines())[:SAFE_DETAIL_MAX_LENGTH]


@dataclass
class WorkerFailure(Exception):
    code: str
    safe_detail: str
    retryable: bool
    retry_after: timedelta | None = None

    def __post_init__(self) -> None:
        if self.code not in INGESTION_ERROR_CODES:
            raise ValueError(f"unknown worker failure code: {self.code}")
        if self.retry_after is not None and self.retry_after < timedelta(0):
            raise ValueError("retry_after cannot be negative")
        self.safe_detail = _sanitize_detail(self.safe_detail)
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
    return delay


__all__ = [
    "PERMANENT_ERROR_CODES",
    "RETRY_DELAYS",
    "SAFE_DETAIL_MAX_LENGTH",
    "WorkerFailure",
    "retry_delay",
]
