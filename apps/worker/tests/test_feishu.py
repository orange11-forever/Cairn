import hashlib
import json
import traceback
from collections.abc import Callable, Sequence
from http.client import BadStatusLine, HTTPMessage, HTTPResponse
from io import BytesIO
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.request import BaseHandler, Request, build_opener
from urllib.response import addinfourl

import pytest
from cairn_worker.feishu import FeishuDocumentClient, FeishuDocumentSnapshot, FeishuFailure

TOKEN = {"code": 0, "tenant_access_token": "tenant-secret", "expire": 7200}
DOCUMENT: dict[str, object] = {
    "document_id": "Doc123",
    "revision_id": 7,
    "title": "Design",
}
METADATA = {
    "code": 0,
    "data": {
        "document": DOCUMENT,
    },
}
RAW = {"code": 0, "data": {"content": "第一行\nsecond line\n"}}


class _Response(BytesIO):
    def __init__(
        self,
        body: bytes,
        *,
        status: int = 200,
        headers: HTTPMessage | None = None,
        on_read: Callable[[], None] | None = None,
        read_error: BaseException | None = None,
    ) -> None:
        super().__init__(body)
        self.status = status
        self.headers = headers or HTTPMessage()
        self.read_sizes: list[int] = []
        self._on_read = on_read
        self._read_error = read_error

    def read(self, size: int | None = -1) -> bytes:
        assert size is not None
        self.read_sizes.append(size)
        if self._on_read is not None:
            self._on_read()
        if self._read_error is not None:
            raise self._read_error
        return super().read(size)


class _SocketBytes:
    def __init__(self, value: bytes) -> None:
        self._value = value

    def makefile(self, mode: str) -> BytesIO:
        assert mode == "rb"
        return BytesIO(self._value)


class _ScriptedOpener:
    def __init__(self, items: list[_Response | BaseException]) -> None:
        self.items = items
        self.requests: list[Request] = []
        self.timeouts: list[float] = []

    def open(self, request: Request, *, timeout: float) -> _Response:
        self.requests.append(request)
        self.timeouts.append(timeout)
        item = self.items.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class _OpenerFactory:
    def __init__(self, opener: _ScriptedOpener) -> None:
        self.opener = opener
        self.handlers: list[object] = []

    def __call__(self, *handlers: object) -> _ScriptedOpener:
        self.handlers.extend(handlers)
        return self.opener


def _response(payload: object, **kwargs: Any) -> _Response:
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
    return _Response(body, **kwargs)


def _http_error(status: int, *, retry_after: str | None = None) -> HTTPError:
    headers = HTTPMessage()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return HTTPError(
        "https://open.feishu.cn/private",
        status,
        "upstream-secret-reason",
        headers,
        BytesIO(b'{"secret":"upstream-private-body"}'),
    )


def _client(
    items: Sequence[_Response | BaseException],
    *,
    clock: Callable[[], float] = lambda: 0.0,
    maximum_response_bytes: int = 2 * 1024 * 1024,
) -> tuple[FeishuDocumentClient, _ScriptedOpener, _OpenerFactory]:
    opener = _ScriptedOpener(list(items))
    factory = _OpenerFactory(opener)
    return (
        FeishuDocumentClient(
            app_id="app-identifier",
            app_secret="app-secret-canary",
            timeout_seconds=4.5,
            maximum_response_bytes=maximum_response_bytes,
            opener_factory=factory,
            clock=clock,
        ),
        opener,
        factory,
    )


def _success_responses(
    *,
    token: object = TOKEN,
    metadata_a: object = METADATA,
    raw: object = RAW,
    metadata_b: object = METADATA,
) -> list[_Response]:
    return [
        _response(token),
        _response(metadata_a),
        _response(raw),
        _response(metadata_b),
    ]


def _assert_safe_failure(failure: FeishuFailure, *canaries: str) -> None:
    rendered = f"{failure!r} {failure} {failure.args}"
    for canary in canaries:
        assert canary not in rendered


def test_read_document_sends_exact_contract_and_returns_immutable_snapshot() -> None:
    """Break caught: request drift or content normalization corrupts a document snapshot."""
    responses = _success_responses()
    client, opener, factory = _client(responses)

    result = client.read_document("Doc123")

    expected_content = "第一行\nsecond line\n"
    assert result == FeishuDocumentSnapshot(
        document_id="Doc123",
        revision_id=7,
        title="Design",
        content=expected_content,
        content_sha256=hashlib.sha256(expected_content.encode("utf-8")).hexdigest(),
    )
    with pytest.raises((AttributeError, TypeError)):
        result.revision_id = 8  # type: ignore[misc]
    assert "Design" not in repr(result)
    assert expected_content not in repr(result)

    assert opener.timeouts == [4.5] * 4
    assert len(factory.handlers) == 4
    assert [request.get_method() for request in opener.requests] == ["POST", "GET", "GET", "GET"]
    assert [request.full_url for request in opener.requests] == [
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        "https://open.feishu.cn/open-apis/docx/v1/documents/Doc123",
        "https://open.feishu.cn/open-apis/docx/v1/documents/Doc123/raw_content",
        "https://open.feishu.cn/open-apis/docx/v1/documents/Doc123",
    ]
    token_request = opener.requests[0]
    assert token_request.get_header("Authorization") is None
    assert token_request.get_header("Cookie") is None
    assert token_request.get_header("Accept") == "application/json"
    assert token_request.get_header("Content-type") == "application/json"
    assert json.loads(cast(bytes, token_request.data)) == {
        "app_id": "app-identifier",
        "app_secret": "app-secret-canary",
    }
    for request in opener.requests[1:]:
        assert request.data is None
        assert request.get_header("Authorization") == "Bearer tenant-secret"
        assert request.get_header("Cookie") is None
        assert request.get_header("Accept") == "application/json"
    assert all(response.closed for response in responses)


def test_empty_content_is_a_valid_snapshot() -> None:
    """Break caught: the reader must not invent ingestion policy by rejecting empty remote text."""
    client, _opener, _factory = _client(_success_responses(raw={"code": 0, "data": {"content": ""}}))

    snapshot = client.read_document("Doc123")

    assert snapshot.content == ""
    assert snapshot.content_sha256 == hashlib.sha256(b"").hexdigest()


def test_instance_cache_reuses_token_until_early_expiration() -> None:
    """Break caught: valid instance-local tokens must be reused and expired before provider TTL."""
    now = [100.0]
    responses = _success_responses(token={"code": 0, "tenant_access_token": "cached", "expire": 120})
    responses.extend(_success_responses()[1:])
    responses.extend(_success_responses(token={"code": 0, "tenant_access_token": "refreshed", "expire": 120}))
    client, opener, _factory = _client(responses, clock=lambda: now[0])

    client.read_document("Doc123")
    now[0] = 159.9
    client.read_document("Doc123")
    now[0] = 160.0
    client.read_document("Doc123")

    assert [request.get_method() for request in opener.requests] == [
        "POST",
        "GET",
        "GET",
        "GET",
        "GET",
        "GET",
        "GET",
        "POST",
        "GET",
        "GET",
        "GET",
    ]
    assert opener.requests[-3].get_header("Authorization") == "Bearer refreshed"


def test_slow_token_request_does_not_extend_cached_ttl() -> None:
    """Break caught: network latency must consume token lifetime rather than moving its start time."""
    now = [0.0]
    token_response = _response(
        {"code": 0, "tenant_access_token": "slow", "expire": 120},
        on_read=lambda: now.__setitem__(0, 61.0),
    )
    items = [token_response, *_success_responses()[1:], *_success_responses()]
    client, opener, _factory = _client(items, clock=lambda: now[0])

    client.read_document("Doc123")
    client.read_document("Doc123")

    assert [request.get_method() for request in opener.requests].count("POST") == 2


def test_different_clients_never_share_tokens() -> None:
    """Break caught: credentials from one application instance must not authenticate another."""
    first, first_opener, _factory = _client(_success_responses())
    second, second_opener, _factory = _client(_success_responses())

    first.read_document("Doc123")
    second.read_document("Doc123")

    assert first_opener.requests[0].get_method() == "POST"
    assert second_opener.requests[0].get_method() == "POST"


@pytest.mark.parametrize(
    ("metadata_b", "field"),
    [
        ({"code": 0, "data": {"document": {**DOCUMENT, "revision_id": 8}}}, "revision"),
        ({"code": 0, "data": {"document": {**DOCUMENT, "title": "Changed"}}}, "title"),
    ],
)
def test_metadata_change_rejects_partial_snapshot(metadata_b: object, field: str) -> None:
    """Break caught: concurrent metadata changes must never pair stale text with new metadata."""
    del field
    client, _opener, _factory = _client(_success_responses(metadata_b=metadata_b))

    with pytest.raises(FeishuFailure) as raised:
        client.read_document("Doc123")

    assert (raised.value.code, raised.value.retryable) == ("feishu_document_changed", True)


@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_redirects_are_classified_without_retry(status: int) -> None:
    """Break caught: credentials must never be replayed after any provider redirect."""
    error = _http_error(status)
    client, opener, _factory = _client([error])

    with pytest.raises(FeishuFailure) as raised:
        client.read_document("Doc123")

    assert (raised.value.code, raised.value.retryable, len(opener.requests)) == (
        "feishu_redirect_rejected",
        False,
        1,
    )


@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [
        (400, "feishu_request_rejected", False),
        (401, "feishu_auth_failed", False),
        (403, "feishu_auth_failed", False),
        (404, "feishu_auth_failed", False),
        (429, "feishu_rate_limited", True),
        (500, "feishu_unavailable", True),
        (503, "feishu_unavailable", True),
    ],
)
def test_http_status_is_classified_before_error_body(
    status: int, code: str, retryable: bool
) -> None:
    """Break caught: status semantics must win over a malformed or sensitive error body."""
    error = _http_error(status)
    client, opener, _factory = _client([error])

    with pytest.raises(FeishuFailure) as raised:
        client.read_document("Doc123")

    assert (raised.value.code, raised.value.retryable, len(opener.requests)) == (code, retryable, 1)
    _assert_safe_failure(raised.value, "upstream-secret-reason", "upstream-private-body", "app-secret-canary")
    assert error.closed


@pytest.mark.parametrize("stage", ["metadata", "raw"])
@pytest.mark.parametrize(
    ("status", "business_code", "expected"),
    [
        (403, 1770032, "feishu_access_denied"),
        (404, 1770002, "feishu_not_found"),
        (400, 1770003, "feishu_not_found"),
        (500, 1771001, "feishu_unavailable"),
        (503, 1771005, "feishu_unavailable"),
        (400, 9999999, "feishu_request_rejected"),
    ],
)
@pytest.mark.parametrize("transport", ["response", "http_error", "envelope"])
def test_document_error_classification_keeps_token_errors_separate(
    stage: str, status: int, business_code: int, expected: str, transport: str,
) -> None:
    """A documented document error changes access; an unknown code stays generic."""
    body = json.dumps({"code": business_code, "msg": "private-upstream-secret"}).encode()
    if transport == "http_error":
        failed: _Response | BaseException = HTTPError(
            "https://open.feishu.cn/private", status, "private-upstream-secret",
            HTTPMessage(), BytesIO(body),
        )
    else:
        failed = _response({"code": business_code, "msg": "private-upstream-secret"}, status=200 if transport == "envelope" else status)
    items: list[_Response | BaseException] = [_response(TOKEN)]
    if stage == "raw":
        items.append(_response(METADATA))
    items.append(failed)
    client, opener, _factory = _client(items)

    with pytest.raises(FeishuFailure) as raised:
        client.read_document("Doc123")

    assert raised.value.code == expected
    assert len(opener.requests) == (3 if stage == "raw" else 2)
    _assert_safe_failure(raised.value, "private-upstream-secret")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("17", 17),
        ("0", 0),
        ("3600", 3600),
        ("3601", 3600),
        ("9" * 5000, 3600),
        ("-1", None),
        ("tomorrow", None),
        ("Wed, 21 Oct 2015 07:28:00 GMT", None),
        ("１２", None),
    ],
)
@pytest.mark.parametrize("status", [429, 503])
def test_retry_after_accepts_only_bounded_ascii_delta_seconds(
    value: str, expected: int | None, status: int
) -> None:
    """Break caught: scheduling hints must not trust dates, signs, Unicode digits, or huge integers."""
    client, _opener, _factory = _client([_http_error(status, retry_after=value)])

    with pytest.raises(FeishuFailure) as raised:
        client.read_document("Doc123")

    assert raised.value.retry_after_seconds == expected


@pytest.mark.parametrize(
    ("payload", "stage"),
    [
        ({"code": True, "tenant_access_token": "token", "expire": 10}, "token"),
        ({"code": 7, "tenant_access_token": "token", "expire": 10}, "token-business"),
        ({"code": 0, "tenant_access_token": "", "expire": 10}, "empty-token"),
        ({"code": 0, "tenant_access_token": "contains space", "expire": 10}, "space-token"),
        ({"code": 0, "tenant_access_token": "é", "expire": 10}, "unicode-token"),
        ({"code": 0, "tenant_access_token": "x" * 4097, "expire": 10}, "long-token"),
        ({"code": 0, "tenant_access_token": "token", "expire": True}, "bool-expire"),
        ({"code": 0, "tenant_access_token": "token", "expire": 0}, "zero-expire"),
        ({"code": 0, "tenant_access_token": "token", "expire": 86401}, "long-expire"),
    ],
)
def test_invalid_token_payloads_are_rejected(payload: object, stage: str) -> None:
    """Break caught: invalid business status, token bytes, or TTL must never enter the cache."""
    del stage
    client, opener, _factory = _client([_response(payload)])

    with pytest.raises(FeishuFailure) as raised:
        client.read_document("Doc123")

    expected = "feishu_request_rejected" if cast(dict[str, object], payload).get("code") == 7 else "feishu_invalid_response"
    assert (raised.value.code, raised.value.retryable, len(opener.requests)) == (expected, False, 1)


@pytest.mark.parametrize(
    ("payload", "stage"),
    [
        ({"code": 3, "data": {}}, "metadata-business"),
        ({"code": True, "data": {}}, "metadata-code-bool"),
        ({"code": 0, "data": {}}, "metadata-missing-document"),
        ({"code": 0, "data": {"document": {**DOCUMENT, "document_id": "Other"}}}, "wrong-id"),
        ({"code": 0, "data": {"document": {**DOCUMENT, "revision_id": True}}}, "bool-revision"),
        ({"code": 0, "data": {"document": {**DOCUMENT, "revision_id": -1}}}, "negative-revision"),
        ({"code": 0, "data": {"document": {**DOCUMENT, "title": "x" * 4097}}}, "long-title"),
        ({"code": 0, "data": {"document": {**DOCUMENT, "title": "\ud800"}}}, "surrogate-title"),
    ],
)
def test_invalid_metadata_is_rejected(payload: object, stage: str) -> None:
    """Break caught: ambiguous metadata must never become an apparently valid snapshot."""
    del stage
    client, opener, _factory = _client([_response(TOKEN), _response(payload)])

    with pytest.raises(FeishuFailure) as raised:
        client.read_document("Doc123")

    expected = "feishu_request_rejected" if cast(dict[str, object], payload).get("code") == 3 else "feishu_invalid_response"
    assert (raised.value.code, raised.value.retryable, len(opener.requests)) == (expected, False, 2)


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"code": 9, "data": {}}, "feishu_request_rejected"),
        ({"code": 0, "data": {}}, "feishu_invalid_response"),
        ({"code": 0, "data": {"content": 7}}, "feishu_invalid_response"),
        ({"code": 0, "data": {"content": "\ud800"}}, "feishu_invalid_response"),
    ],
)
def test_invalid_raw_content_is_rejected(payload: object, expected: str) -> None:
    """Break caught: missing, non-text, or invalid UTF-8 content must not be hashed or returned."""
    client, opener, _factory = _client([_response(TOKEN), _response(METADATA), _response(payload)])

    with pytest.raises(FeishuFailure) as raised:
        client.read_document("Doc123")

    assert (raised.value.code, raised.value.retryable, len(opener.requests)) == (expected, False, 3)


@pytest.mark.parametrize(
    "body",
    [
        b"not-json",
        b'\xff',
        b"[" * 2000 + b"0" + b"]" * 2000,
        json.dumps(["object-required"]).encode(),
    ],
    ids=["malformed-json", "invalid-utf8", "deep-json", "non-object"],
)
def test_invalid_json_transport_payload_is_rejected(body: bytes) -> None:
    """Break caught: malformed, deeply nested, or wrong-shaped JSON must fail closed."""
    client, _opener, _factory = _client([_response(body)])

    with pytest.raises(FeishuFailure) as raised:
        client.read_document("Doc123")

    assert (raised.value.code, raised.value.retryable) == ("feishu_invalid_response", False)


def test_token_and_document_responses_use_distinct_bounded_reads() -> None:
    """Break caught: neither token nor document responses may be accumulated without a hard cap."""
    responses = _success_responses()
    client, _opener, _factory = _client(list(responses), maximum_response_bytes=1024 * 1024)

    client.read_document("Doc123")

    assert responses[0].read_sizes == [64 * 1024 + 1]
    assert [response.read_sizes for response in responses[1:]] == [[1024 * 1024 + 1]] * 3


@pytest.mark.parametrize("token_stage", [True, False])
def test_response_overflow_is_permanent_and_closed(token_stage: bool) -> None:
    """Break caught: a provider cannot force excess buffering at either response boundary."""
    maximum = 1024 * 1024
    if token_stage:
        oversized = _response(b"x" * (64 * 1024 + 1))
        items = [oversized]
    else:
        oversized = _response(b"x" * (maximum + 1))
        items = [_response(TOKEN), oversized]
    client, _opener, _factory = _client(items, maximum_response_bytes=maximum)

    with pytest.raises(FeishuFailure) as raised:
        client.read_document("Doc123")

    assert (raised.value.code, raised.value.retryable, oversized.closed) == (
        "feishu_response_too_large",
        False,
        True,
    )


@pytest.mark.parametrize(
    "error",
    [
        URLError("transport-secret"),
        TimeoutError("transport-secret"),
        OSError("transport-secret"),
        BadStatusLine("transport-secret"),
    ],
)
def test_open_transport_failures_are_retryable_and_redacted(error: Exception) -> None:
    """Break caught: provider transport diagnostics must not escape into logs or failures."""
    client, opener, _factory = _client([error])

    with pytest.raises(FeishuFailure) as raised:
        client.read_document("Doc123")

    assert (raised.value.code, raised.value.retryable, len(opener.requests)) == (
        "feishu_unavailable",
        True,
        1,
    )
    _assert_safe_failure(raised.value, "transport-secret", "app-secret-canary")


def test_truncated_chunked_http_response_is_retryable_closed_and_redacted() -> None:
    """Break caught: truncated HTTP framing must remain a retryable transport failure."""
    partial_canary = "private-partial-body-canary"
    wire_response = (
        b"HTTP/1.1 200 OK\r\n"
        b"Transfer-Encoding: chunked\r\n"
        b"\r\n"
        b"40\r\n"
        + partial_canary.encode("ascii")
    )
    response = HTTPResponse(cast(Any, _SocketBytes(wire_response)))
    response.begin()
    opener = _ScriptedOpener([])

    def open_response(request: Request, *, timeout: float) -> HTTPResponse:
        opener.requests.append(request)
        opener.timeouts.append(timeout)
        return response

    opener.open = open_response  # type: ignore[method-assign]
    client = FeishuDocumentClient(
        app_id="app-identifier",
        app_secret="app-secret-canary",
        opener_factory=lambda *handlers: opener,
    )

    with pytest.raises(FeishuFailure) as raised:
        try:
            client.read_document("Doc123")
        except FeishuFailure:
            formatted = traceback.format_exc()
            assert partial_canary not in formatted
            assert "app-secret-canary" not in formatted
            raise

    assert (raised.value.code, raised.value.retryable, response.isclosed()) == (
        "feishu_unavailable",
        True,
        True,
    )
    _assert_safe_failure(raised.value, partial_canary, "app-secret-canary")


@pytest.mark.parametrize(
    ("error", "expected"),
    [(OSError("read-secret"), "feishu_unavailable"), (TimeoutError("read-secret"), "feishu_unavailable"), (RuntimeError("read-secret"), "feishu_unexpected")],
)
def test_read_failures_are_closed_classified_and_traceback_redacted(
    error: Exception, expected: str
) -> None:
    """Break caught: response read and unexpected failures must close resources without leaking text."""
    response = _response(b"", read_error=error)
    client, _opener, _factory = _client([response])

    with pytest.raises(FeishuFailure) as raised:
        try:
            client.read_document("Doc123")
        except FeishuFailure:
            formatted = traceback.format_exc()
            assert "read-secret" not in formatted
            raise

    assert (raised.value.code, response.closed) == (expected, True)
    _assert_safe_failure(raised.value, "read-secret", "app-secret-canary")


@pytest.mark.parametrize("error", [KeyboardInterrupt("stop"), SystemExit("stop")])
def test_base_exceptions_propagate(error: BaseException) -> None:
    """Break caught: process-control exceptions must never be converted into provider failures."""
    client, _opener, _factory = _client([error])

    with pytest.raises(type(error), match="stop"):
        client.read_document("Doc123")


@pytest.mark.parametrize("document_id", ["", "with-dash", "with/slash", "飞书", "a" * 129, 123])
def test_invalid_document_id_fails_before_network(document_id: object) -> None:
    """Break caught: user-controlled IDs must not alter paths or trigger provider requests."""
    client, opener, _factory = _client([])

    with pytest.raises(FeishuFailure) as raised:
        client.read_document(cast(str, document_id))

    assert (raised.value.code, raised.value.retryable, opener.requests) == (
        "feishu_invalid_response",
        False,
        [],
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"app_id": ""},
        {"app_id": "x" * 4097},
        {"app_id": "bad\nvalue"},
        {"app_secret": ""},
        {"app_secret": "bad\x00value"},
        {"timeout_seconds": True},
        {"timeout_seconds": 0},
        {"timeout_seconds": float("inf")},
        {"timeout_seconds": 60.1},
        {"maximum_response_bytes": True},
        {"maximum_response_bytes": 1024 * 1024 - 1},
        {"maximum_response_bytes": 8 * 1024 * 1024 + 1},
    ],
)
def test_invalid_client_configuration_fails_before_opener_creation(overrides: dict[str, object]) -> None:
    """Break caught: unsafe credentials and resource limits must fail before any transport exists."""
    called = False

    def factory(*handlers: object) -> object:
        del handlers
        nonlocal called
        called = True
        raise AssertionError("must not construct transport")

    values: dict[str, object] = {
        "app_id": "app",
        "app_secret": "secret",
        "timeout_seconds": 10.0,
        "maximum_response_bytes": 2 * 1024 * 1024,
        "opener_factory": factory,
    }
    values.update(overrides)

    with pytest.raises((TypeError, ValueError)):
        FeishuDocumentClient(**values)  # type: ignore[arg-type]

    assert called is False


@pytest.mark.parametrize("failure_kind", ["auth", "business"])
def test_auth_and_business_failures_clear_cache_without_replaying_request(failure_kind: str) -> None:
    """Break caught: rejected cached credentials must be discarded without hidden retry in the same call."""
    rejection: _Response | BaseException
    if failure_kind == "auth":
        rejection = _http_error(401)
    else:
        rejection = _response({"code": 123, "data": {}})
    items: list[_Response | BaseException] = [
        *_success_responses(),
        rejection,
        *_success_responses(token={"code": 0, "tenant_access_token": "new-token", "expire": 7200}),
    ]
    client, opener, _factory = _client(items)
    client.read_document("Doc123")

    with pytest.raises(FeishuFailure):
        client.read_document("Doc123")
    request_count_after_failure = len(opener.requests)
    client.read_document("Doc123")

    assert request_count_after_failure == 5
    assert opener.requests[5].get_method() == "POST"
    assert opener.requests[6].get_header("Authorization") == "Bearer new-token"


@pytest.mark.parametrize(
    ("status", "expected"),
    [(403, "feishu_access_denied"), (404, "feishu_not_found")],
)
def test_final_metadata_failure_returns_no_partial_snapshot(status: int, expected: str) -> None:
    """Break caught: successfully read private content must not escape when final verification fails."""
    client, opener, _factory = _client([
        _response(TOKEN),
        _response(METADATA),
        _response({"code": 0, "data": {"content": "private-partial-content"}}),
        _http_error(status),
    ])

    with pytest.raises(FeishuFailure) as raised:
        client.read_document("Doc123")

    assert raised.value.code == expected
    assert len(opener.requests) == 4
    _assert_safe_failure(raised.value, "private-partial-content")


class _RedirectTransport(BaseHandler):
    handler_order = 100

    def __init__(self) -> None:
        self.requests: list[Request] = []

    def https_open(self, request: Request) -> addinfourl:
        self.requests.append(request)
        headers = HTTPMessage()
        headers["Location"] = "https://redirect-target.invalid/collect"
        response = addinfourl(BytesIO(b"redirect-body-secret"), headers, request.full_url, 302)
        cast(Any, response).msg = "Found"
        return response


def test_real_urllib_handler_chain_does_not_follow_redirect() -> None:
    """Break caught: injected redirect policy must actually stop urllib before a second request."""
    transport = _RedirectTransport()

    def factory(*handlers: BaseHandler) -> Any:
        return build_opener(*handlers, transport)

    client = FeishuDocumentClient(
        app_id="real-chain-app",
        app_secret="real-chain-secret",
        opener_factory=factory,
    )

    with pytest.raises(FeishuFailure) as raised:
        client.read_document("Doc123")

    assert (raised.value.code, raised.value.retryable) == ("feishu_redirect_rejected", False)
    assert [request.full_url for request in transport.requests] == [
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    ]
    assert transport.requests[0].get_header("Authorization") is None


def test_client_and_failure_repr_do_not_expose_credentials_or_upstream_text() -> None:
    """Break caught: routine diagnostics must remain safe even for unexpected provider failures."""
    client, _opener, _factory = _client([RuntimeError("arbitrary-upstream-secret")])

    assert "app-secret-canary" not in repr(client)
    with pytest.raises(FeishuFailure) as raised:
        client.read_document("Doc123")

    assert (raised.value.code, raised.value.retryable) == ("feishu_unexpected", False)
    _assert_safe_failure(raised.value, "arbitrary-upstream-secret", "app-secret-canary")
