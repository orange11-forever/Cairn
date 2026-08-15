from datetime import timedelta
from importlib.resources import files

import pytest
from cairn_api.knowledge.models import INGESTION_ERROR_CODES
from cairn_worker.errors import (
    PERMANENT_ERROR_CODES,
    SAFE_DETAIL_MAX_LENGTH,
    WorkerFailure,
    retry_delay,
    safe_detail_for,
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


def test_retry_delay_preserves_a_multi_day_provider_contract_exactly() -> None:
    """Break caught: overflow protection must not shorten valid Provider backpressure."""
    failure = WorkerFailure(
        "embedding_unavailable",
        "provider unavailable",
        retryable=True,
        retry_after=timedelta(days=2),
    )

    assert retry_delay(1, failure) == timedelta(days=2)


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


def test_safe_detail_is_code_derived_and_never_copies_untrusted_text() -> None:
    """Break caught: attempt history must not persist credentials or raw provider bodies."""
    secret = 'Bearer sk-secret\n{"error":{"message":"private document text"}}' + "x" * (
        SAFE_DETAIL_MAX_LENGTH + 100
    )
    failure = WorkerFailure(
        "parser_failed",
        secret,
        retryable=True,
    )

    assert failure.safe_detail == "worker handler or parser failed"
    assert len(failure.safe_detail) <= SAFE_DETAIL_MAX_LENGTH
    assert "\n" not in failure.safe_detail
    assert "sk-secret" not in failure.safe_detail
    assert "private document text" not in failure.safe_detail


def test_every_ingestion_error_code_has_a_bounded_safe_template() -> None:
    """Break caught: newly persisted failure codes must not fall back to caller text."""
    details = [safe_detail_for(code) for code in INGESTION_ERROR_CODES]

    assert all(detail and len(detail) <= SAFE_DETAIL_MAX_LENGTH for detail in details)


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
