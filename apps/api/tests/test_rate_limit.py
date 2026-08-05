from datetime import UTC, datetime, timedelta

from cairn_api.auth.rate_limit import (
    RateLimitPolicy,
    digest_key,
    retry_after_seconds,
)


def test_email_digest_is_domain_separated_and_stable() -> None:
    assert digest_key("email", " Alice@Example.com ", b"s" * 32) == digest_key(
        "email", "alice@example.com", b"s" * 32
    )
    assert digest_key("email", "a@example.com", b"s" * 32) != digest_key(
        "ip", "a@example.com", b"s" * 32
    )


def test_retry_after_rounds_up_and_uses_latest_deadline() -> None:
    now = datetime(2026, 8, 5, 0, 0, 0, 100_000, tzinfo=UTC)
    assert retry_after_seconds(
        [now + timedelta(seconds=1), now + timedelta(seconds=2.1)], now
    ) == 3


def test_rate_limit_policy_defaults_and_helpers() -> None:
    policy = RateLimitPolicy("email")
    assert policy.threshold == 5
    assert policy.window == timedelta(minutes=15)
    assert policy.block == timedelta(minutes=15)
    assert policy.normalize_email_key(" Alice@Example.com ") == "alice@example.com"
    assert policy.digest("a@example.com", b"s" * 32) == digest_key(
        "email", "a@example.com", b"s" * 32
    )
