from datetime import timedelta
from importlib.resources import files

import pytest
from cairn_worker.errors import (
    PERMANENT_ERROR_CODES,
    SAFE_DETAIL_MAX_LENGTH,
    WorkerFailure,
    retry_delay,
)


def test_worker_package_declares_inline_typing_support() -> None:
    """Break caught: consumers must not treat the annotated worker package as untyped."""
    assert files("cairn_worker").joinpath("py.typed").is_file()


def test_retry_delay_uses_the_four_exact_automatic_backoffs() -> None:
    """Break caught: retry scheduling must not drift from the durable backoff contract."""
    failure = WorkerFailure("embedding_unavailable", "provider unavailable", retryable=True)

    assert [retry_delay(attempt, failure) for attempt in range(1, 5)] == [
        timedelta(seconds=5),
        timedelta(seconds=30),
        timedelta(minutes=2),
        timedelta(minutes=10),
    ]


def test_retry_after_only_extends_the_automatic_backoff() -> None:
    """Break caught: a shorter provider Retry-After must never weaken local backoff."""
    short = WorkerFailure(
        "embedding_unavailable",
        "provider unavailable",
        retryable=True,
        retry_after=timedelta(seconds=2),
    )
    long = WorkerFailure(
        "embedding_unavailable",
        "provider unavailable",
        retryable=True,
        retry_after=timedelta(seconds=45),
    )

    assert retry_delay(1, short) == timedelta(seconds=5)
    assert retry_delay(1, long) == timedelta(seconds=45)


@pytest.mark.parametrize(
    "code",
    [
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
    ],
)
def test_permanent_ingestion_codes_never_retry(code: str) -> None:
    """Break caught: unsafe or structurally invalid content must not enter a retry loop."""
    assert code in PERMANENT_ERROR_CODES
    assert WorkerFailure.for_code(code, "safe").retryable is False


def test_safe_detail_is_single_line_and_bounded() -> None:
    """Break caught: attempt history must not persist unbounded multi-line provider output."""
    failure = WorkerFailure(
        "parser_failed",
        "first line\n" + "x" * (SAFE_DETAIL_MAX_LENGTH + 100),
        retryable=True,
    )

    assert len(failure.safe_detail) == SAFE_DETAIL_MAX_LENGTH
    assert "\n" not in failure.safe_detail
    assert failure.safe_detail.startswith("first line ")


def test_worker_failure_rejects_unknown_codes_and_negative_retry_after() -> None:
    """Break caught: invalid failure facts must be rejected before reaching DB constraints."""
    with pytest.raises(ValueError, match="unknown worker failure code"):
        WorkerFailure("not_a_real_code", "safe", retryable=True)
    with pytest.raises(ValueError, match="retry_after"):
        WorkerFailure(
            "embedding_unavailable",
            "safe",
            retryable=True,
            retry_after=timedelta(seconds=-1),
        )
