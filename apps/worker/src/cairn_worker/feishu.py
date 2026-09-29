import hashlib
import json
import math
import re
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from http.client import HTTPException
from time import monotonic
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

_ORIGIN = "https://open.feishu.cn"
_TOKEN_URL = f"{_ORIGIN}/open-apis/auth/v3/tenant_access_token/internal"
_TOKEN_RESPONSE_LIMIT = 64 * 1024
_MINIMUM_RESPONSE_LIMIT = 1024 * 1024
_MAXIMUM_RESPONSE_LIMIT = 8 * 1024 * 1024
_MAXIMUM_CREDENTIAL_LENGTH = 4096
_MAXIMUM_TOKEN_LENGTH = 4096
_MAXIMUM_TITLE_LENGTH = 4096
_DOCUMENT_ID = re.compile(r"[A-Za-z0-9]{1,128}\Z", re.ASCII)

_SAFE_DETAILS = {
    "feishu_access_denied": "Feishu denied access to the document",
    "feishu_auth_failed": "Feishu authentication failed",
    "feishu_document_changed": "Feishu document changed during the read",
    "feishu_invalid_response": "Feishu returned an invalid response",
    "feishu_not_found": "Feishu document was not found",
    "feishu_rate_limited": "Feishu rate limited the request",
    "feishu_redirect_rejected": "Feishu redirect was rejected",
    "feishu_request_rejected": "Feishu rejected the request",
    "feishu_response_too_large": "Feishu response exceeded the size limit",
    "feishu_unavailable": "Feishu is unavailable",
    "feishu_unexpected": "Feishu reader failed unexpectedly",
}
_RETRYABLE_CODES = frozenset(
    {
        "feishu_document_changed",
        "feishu_rate_limited",
        "feishu_unavailable",
    }
)


@dataclass(frozen=True)
class FeishuDocumentSnapshot:
    document_id: str
    revision_id: int
    title: str = field(repr=False)
    content: str = field(repr=False)
    content_sha256: str


@dataclass
class FeishuFailure(Exception):
    code: str
    safe_detail: str
    retryable: bool
    retry_after_seconds: int | None = None

    def __post_init__(self) -> None:
        Exception.__init__(self, self.code, self.safe_detail)


def _failure(code: str, *, retry_after_seconds: int | None = None) -> FeishuFailure:
    return FeishuFailure(
        code=code,
        safe_detail=_SAFE_DETAILS[code],
        retryable=code in _RETRYABLE_CODES,
        retry_after_seconds=retry_after_seconds,
    )


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs


OpenerFactory = Callable[..., Any]
Clock = Callable[[], float]


def _validate_credential(name: str, value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > _MAXIMUM_CREDENTIAL_LENGTH
        or any(unicodedata.category(character) == "Cc" for character in value)
    ):
        raise ValueError(f"{name} must be nonempty, bounded text without control characters")
    return value


def _validate_timeout(value: object) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(value)
        or value <= 0
        or value > 60
    ):
        raise ValueError("timeout_seconds must be a finite number in (0, 60]")
    return float(value)


def _validate_response_limit(value: object) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < _MINIMUM_RESPONSE_LIMIT
        or value > _MAXIMUM_RESPONSE_LIMIT
    ):
        raise ValueError("maximum_response_bytes must be an integer from 1 MiB through 8 MiB")
    return value


def _retry_after(headers: object) -> int | None:
    try:
        value = cast(Any, headers).get("Retry-After")
    except (AttributeError, TypeError):
        return None
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
        return None
    normalized = value.lstrip("0") or "0"
    if len(normalized) > 4 or (len(normalized) == 4 and normalized > "3600"):
        return 3600
    return int(normalized)


def _status_failure(
    status: object, headers: object, *, token_endpoint: bool = False,
    document_endpoint: bool = False, business_code: object = None,
) -> FeishuFailure:
    if document_endpoint and status == 400 and business_code == 1770003:
        return _failure("feishu_not_found")
    if status == 401:
        return _failure("feishu_auth_failed")
    if status == 403:
        return _failure("feishu_auth_failed" if token_endpoint else "feishu_access_denied")
    if status == 404:
        return _failure("feishu_auth_failed" if token_endpoint else "feishu_not_found")
    if status == 429:
        return _failure("feishu_rate_limited", retry_after_seconds=_retry_after(headers))
    if isinstance(status, int) and not isinstance(status, bool) and 500 <= status <= 599:
        return _failure("feishu_unavailable", retry_after_seconds=_retry_after(headers))
    if isinstance(status, int) and not isinstance(status, bool) and 300 <= status <= 399:
        return _failure("feishu_redirect_rejected")
    return _failure("feishu_request_rejected")


def _document_request(request: Request) -> bool:
    return request.full_url.startswith(f"{_ORIGIN}/open-apis/docx/v1/documents/")


def _bounded_business_code(response: object) -> object:
    try:
        body = cast(Any, response).read(_TOKEN_RESPONSE_LIMIT + 1)
        if not isinstance(body, bytes) or len(body) > _TOKEN_RESPONSE_LIMIT:
            return None
        payload = json.loads(body)
        return cast(dict[str, object], payload).get("code") if isinstance(payload, dict) else None
    except (AttributeError, HTTPException, OSError, TimeoutError, UnicodeError, ValueError, RecursionError):
        return None


def _close_quietly(value: object) -> None:
    try:
        cast(Any, value).close()
    except Exception:  # noqa: BLE001, S110 -- cleanup must not replace the safe failure
        pass


def _valid_utf8_text(value: object, *, maximum_length: int | None = None) -> str | None:
    if not isinstance(value, str) or (maximum_length is not None and len(value) > maximum_length):
        return None
    try:
        value.encode("utf-8")
    except UnicodeError:
        return None
    return value


class FeishuDocumentClient:
    def __init__(
        self,
        *,
        app_id: str,
        app_secret: str,
        timeout_seconds: float = 10.0,
        maximum_response_bytes: int = 2 * 1024 * 1024,
        opener_factory: OpenerFactory = build_opener,
        clock: Clock = monotonic,
    ) -> None:
        self._app_id = _validate_credential("app_id", app_id)
        self._app_secret = _validate_credential("app_secret", app_secret)
        self._timeout_seconds = _validate_timeout(timeout_seconds)
        self._maximum_response_bytes = _validate_response_limit(maximum_response_bytes)
        if not callable(opener_factory) or not callable(clock):
            raise TypeError("opener_factory and clock must be callable")
        self._opener_factory = opener_factory
        self._clock = clock
        self._cached_token: str | None = None
        self._token_expires_at = 0.0

    def __repr__(self) -> str:
        return (
            "FeishuDocumentClient("
            f"timeout_seconds={self._timeout_seconds!r}, "
            f"maximum_response_bytes={self._maximum_response_bytes!r})"
        )

    def read_document(self, document_id: str) -> FeishuDocumentSnapshot:
        try:
            if type(document_id) is not str or _DOCUMENT_ID.fullmatch(document_id) is None:
                raise _failure("feishu_invalid_response")
            token = self._tenant_token()
            metadata_a = self._metadata(document_id, token)
            content = self._raw_content(document_id, token)
            metadata_b = self._metadata(document_id, token)
            if metadata_a != metadata_b:
                raise _failure("feishu_document_changed")
            revision_id, title = metadata_a
            return FeishuDocumentSnapshot(
                document_id=document_id,
                revision_id=revision_id,
                title=title,
                content=content,
                content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            )
        except FeishuFailure:
            raise
        except Exception:  # noqa: BLE001 -- the public boundary redacts every ordinary exception
            raise _failure("feishu_unexpected") from None

    def _tenant_token(self) -> str:
        request_started_at = self._clock()
        if self._cached_token is not None and request_started_at < self._token_expires_at:
            return self._cached_token
        body = json.dumps(
            {"app_id": self._app_id, "app_secret": self._app_secret},
            separators=(",", ":"),
        ).encode("utf-8")
        request = Request(
            _TOKEN_URL,
            data=body,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            method="POST",
        )
        payload = self._request_json(request, limit=_TOKEN_RESPONSE_LIMIT)
        self._check_business_code(payload)
        token = _valid_utf8_text(payload.get("tenant_access_token"), maximum_length=_MAXIMUM_TOKEN_LENGTH)
        expire = payload.get("expire")
        if (
            token is None
            or not token
            or not token.isascii()
            or any(character.isspace() or not 0x21 <= ord(character) <= 0x7E for character in token)
            or isinstance(expire, bool)
            or not isinstance(expire, int)
            or expire < 1
            or expire > 86_400
        ):
            raise _failure("feishu_invalid_response")
        self._cached_token = token
        self._token_expires_at = request_started_at + expire - min(60.0, expire / 2)
        return token

    def _metadata(self, document_id: str, token: str) -> tuple[int, str]:
        payload = self._authorized_get(
            f"{_ORIGIN}/open-apis/docx/v1/documents/{document_id}", token
        )
        self._check_business_code(payload, document_endpoint=True)
        data = payload.get("data")
        if not isinstance(data, dict):
            raise _failure("feishu_invalid_response")
        document = cast(dict[str, object], data).get("document")
        if not isinstance(document, dict):
            raise _failure("feishu_invalid_response")
        record = cast(dict[str, object], document)
        response_document_id = record.get("document_id")
        revision_id = record.get("revision_id")
        title = _valid_utf8_text(record.get("title"), maximum_length=_MAXIMUM_TITLE_LENGTH)
        if (
            response_document_id != document_id
            or isinstance(revision_id, bool)
            or not isinstance(revision_id, int)
            or revision_id < 0
            or title is None
        ):
            raise _failure("feishu_invalid_response")
        return revision_id, title

    def _raw_content(self, document_id: str, token: str) -> str:
        payload = self._authorized_get(
            f"{_ORIGIN}/open-apis/docx/v1/documents/{document_id}/raw_content", token
        )
        self._check_business_code(payload, document_endpoint=True)
        data = payload.get("data")
        if not isinstance(data, dict):
            raise _failure("feishu_invalid_response")
        content = _valid_utf8_text(cast(dict[str, object], data).get("content"))
        if content is None:
            raise _failure("feishu_invalid_response")
        return content

    def _authorized_get(self, url: str, token: str) -> dict[str, object]:
        request = Request(
            url,
            headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
            method="GET",
        )
        return self._request_json(request, limit=self._maximum_response_bytes)

    def _check_business_code(self, payload: Mapping[str, object], *, document_endpoint: bool = False) -> None:
        code = payload.get("code")
        if isinstance(code, bool) or not isinstance(code, int):
            raise _failure("feishu_invalid_response")
        if code != 0:
            self._cached_token = None
            self._token_expires_at = 0.0
            if document_endpoint:
                if code in {1770002, 1770003}:
                    raise _failure("feishu_not_found")
                if code == 1770032:
                    raise _failure("feishu_access_denied")
                if code in {1771001, 1771002, 1771003, 1771004, 1771005, 1771006}:
                    raise _failure("feishu_unavailable")
            raise _failure("feishu_request_rejected")

    def _request_json(self, request: Request, *, limit: int) -> dict[str, object]:
        try:
            opener = self._opener_factory(_RejectRedirects())
            with opener.open(request, timeout=self._timeout_seconds) as response:
                status = getattr(response, "status", getattr(response, "code", None))
                if status != 200:
                    if status == 401:
                        self._cached_token = None
                        self._token_expires_at = 0.0
                    code = _bounded_business_code(response) if _document_request(request) else None
                    raise _status_failure(status, getattr(response, "headers", None), token_endpoint=request.full_url == _TOKEN_URL, document_endpoint=_document_request(request), business_code=code)
                try:
                    body = response.read(limit + 1)
                except (HTTPException, OSError, TimeoutError):
                    raise _failure("feishu_unavailable") from None
                if not isinstance(body, bytes):
                    raise _failure("feishu_invalid_response")
                if len(body) > limit:
                    raise _failure("feishu_response_too_large")
        except HTTPError as error:
            try:
                if error.code == 401:
                    self._cached_token = None
                    self._token_expires_at = 0.0
                code = _bounded_business_code(error) if _document_request(request) else None
                failure = _status_failure(error.code, error.headers, token_endpoint=request.full_url == _TOKEN_URL, document_endpoint=_document_request(request), business_code=code)
            finally:
                _close_quietly(error)
            raise failure from None
        except (HTTPException, URLError, OSError, TimeoutError):
            raise _failure("feishu_unavailable") from None
        try:
            decoded = json.loads(body)
        except (RecursionError, TypeError, UnicodeError, ValueError):
            raise _failure("feishu_invalid_response") from None
        if not isinstance(decoded, dict):
            raise _failure("feishu_invalid_response")
        return cast(dict[str, object], decoded)


__all__ = ["FeishuDocumentClient", "FeishuDocumentSnapshot", "FeishuFailure"]
