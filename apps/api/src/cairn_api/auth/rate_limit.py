"""Deterministic, stateless keying and policy helpers for authentication limits."""

from __future__ import annotations

import hashlib
import hmac
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from ipaddress import ip_address
from typing import Literal

BucketType = Literal["email", "ip"]

_DEFAULT_WINDOW = timedelta(minutes=15)
_DEFAULT_BLOCK = timedelta(minutes=15)
_DEFAULT_THRESHOLDS: dict[BucketType, int] = {"email": 5, "ip": 30}


def normalize_email_key(value: str) -> str:
    return value.strip().casefold()


def canonical_ip(value: str) -> str:
    address = ip_address(value.strip())
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        address = mapped
    return str(address)


def digest_key(bucket_type: BucketType, value: str, secret: str | bytes) -> bytes:
    if bucket_type == "email":
        canonical_value = normalize_email_key(value)
    else:
        try:
            canonical_value = canonical_ip(value)
        except ValueError:
            # Keep this low-level helper total for callers comparing domains;
            # policy clients should canonicalize IPs before invoking it.
            canonical_value = value.strip()
    secret_bytes = secret.encode("utf-8") if isinstance(secret, str) else secret
    message = f"cairn:auth-rate-limit:v1:{bucket_type}\0{canonical_value}".encode()
    return hmac.new(secret_bytes, message, hashlib.sha256).digest()


def retry_after_seconds(deadlines: list[datetime] | tuple[datetime, ...], now: datetime) -> int:
    """Return integer seconds until the latest deadline, rounded up."""
    if not deadlines:
        return 0
    latest = max(deadlines)
    remaining = (latest - now).total_seconds()
    return max(1, math.ceil(remaining)) if remaining > 0 else 1


@dataclass(frozen=True)
class RateLimitPolicy:
    bucket_type: BucketType
    threshold: int | None = None
    window: timedelta = _DEFAULT_WINDOW
    block: timedelta = _DEFAULT_BLOCK

    def __post_init__(self) -> None:
        if self.threshold is None:
            object.__setattr__(self, "threshold", _DEFAULT_THRESHOLDS[self.bucket_type])
        threshold = self.threshold
        assert threshold is not None
        if threshold <= 0:
            raise ValueError("threshold must be positive")
        if self.window <= timedelta(0) or self.block <= timedelta(0):
            raise ValueError("window and block must be positive")

    def normalize_email_key(self, value: str) -> str:
        return normalize_email_key(value)

    def canonical_ip(self, value: str) -> str:
        return canonical_ip(value)

    def digest(self, value: str, secret: str | bytes) -> bytes:
        return digest_key(self.bucket_type, value, secret)
