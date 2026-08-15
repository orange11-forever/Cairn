import json
from datetime import timedelta
from http.client import HTTPMessage
from io import BytesIO
from typing import cast
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request

import pytest
from cairn_api.settings import Settings
from cairn_worker.embedding import OpenAIEmbeddingClient, load_embedding_response
from cairn_worker.errors import WorkerFailure
from pydantic import AnyHttpUrl, SecretStr

MAX_EMBEDDING_RESPONSE_BYTES = 2 * 1024 * 1024


class _RecordingResponse(BytesIO):
    def __init__(self, value: bytes, reads: list[int]) -> None:
        super().__init__(value)
        self._reads = reads

    def read(self, size: int | None = -1) -> bytes:
        assert size is not None
        self._reads.append(size)
        return super().read(size)


class _Opener:
    def __init__(self, response: bytes | Exception) -> None:
        self.response = response
        self.requests: list[Request] = []
        self.timeouts: list[float] = []
        self.read_sizes: list[int] = []

    def open(self, request: Request, *, timeout: float) -> BytesIO:
        self.requests.append(request)
        self.timeouts.append(timeout)
        if isinstance(self.response, Exception):
            raise self.response
        return _RecordingResponse(self.response, self.read_sizes)


def _client(
    response: object,
    *,
    dimensions: int = 3,
    maximum_batch_size: int = 2,
) -> tuple[OpenAIEmbeddingClient, _Opener, list[HTTPRedirectHandler]]:
    payload = response if isinstance(response, bytes | Exception) else json.dumps(response).encode()
    opener = _Opener(payload)
    handlers: list[HTTPRedirectHandler] = []

    def build(*values: HTTPRedirectHandler) -> _Opener:
        handlers.extend(values)
        return opener

    return (
        OpenAIEmbeddingClient(
            base_url="https://embedding.example/v1/",
            api_key="provider-secret-token",
            model="embedding-model",
            dimensions=dimensions,
            timeout_seconds=4.5,
            maximum_batch_size=maximum_batch_size,
            opener_factory=build,
        ),
        opener,
        handlers,
    )


def test_embed_sends_exact_contract_and_restores_provider_order() -> None:
    """Break caught: request drift or trusting Provider response order corrupts chunk vectors."""
    client, opener, handlers = _client(
        {
            "data": [
                {"index": 1, "embedding": [4, 5.5, 6]},
                {"index": 0, "embedding": [1, 2, 3]},
            ]
        }
    )

    result = client.embed(["first source text", "second source text"])

    assert result == [[1.0, 2.0, 3.0], [4.0, 5.5, 6.0]]
    assert len(handlers) == 1
    assert opener.timeouts == [4.5]
    request = opener.requests[0]
    assert request.full_url == "https://embedding.example/v1/embeddings"
    assert request.get_method() == "POST"
    assert request.get_header("Authorization") == "Bearer provider-secret-token"
    assert request.get_header("Content-type") == "application/json"
    assert json.loads(cast(bytes, request.data)) == {
        "input": ["first source text", "second source text"],
        "model": "embedding-model",
        "dimensions": 3,
    }


@pytest.mark.parametrize("inputs", [[], ["one", "two", "three"]])
def test_embed_enforces_one_nonempty_configured_batch(inputs: list[str]) -> None:
    """Break caught: callers must not bypass the configured Provider batch boundary."""
    client, opener, _handlers = _client({"data": []})

    with pytest.raises(ValueError, match="batch"):
        client.embed(inputs)

    assert opener.requests == []


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"data": "not-a-list"},
        {"data": [{"index": 0, "embedding": [1, 2, 3]}]},
        {"data": [{"index": 0, "embedding": [1, 2, 3]}, {"index": 0, "embedding": [4, 5, 6]}]},
        {"data": [{"index": 0, "embedding": [1, 2, 3]}, {"index": 2, "embedding": [4, 5, 6]}]},
        {"data": [{"index": True, "embedding": [1, 2, 3]}, {"index": 1, "embedding": [4, 5, 6]}]},
        {"data": [{"index": 0, "embedding": [1, 2, True]}, {"index": 1, "embedding": [4, 5, 6]}]},
        {
            "data": [
                {"index": 0, "embedding": [1, 2, float("nan")]},
                {"index": 1, "embedding": [4, 5, 6]},
            ]
        },
    ],
    ids=[
        "missing-data",
        "data-schema",
        "count",
        "duplicate-index",
        "range",
        "boolean-index",
        "boolean-vector",
        "nonfinite",
    ],
)
def test_embed_translates_malformed_provider_responses(body: object) -> None:
    """Break caught: malformed or ambiguous Provider records must never become stored vectors."""
    client, _opener, _handlers = _client(body)

    with pytest.raises(WorkerFailure) as raised:
        client.embed(["one", "two"])

    assert (raised.value.code, raised.value.retryable) == ("embedding_unavailable", True)


def test_embed_dimension_mismatch_is_permanent() -> None:
    """Break caught: a valid-looking wrong-width vector must terminalize rather than retry."""
    client, _opener, _handlers = _client({"data": [{"index": 0, "embedding": [1, 2]}]})

    with pytest.raises(WorkerFailure) as raised:
        client.embed(["one"])

    assert (raised.value.code, raised.value.retryable) == (
        "embedding_dimension_mismatch",
        False,
    )


def test_embed_reads_at_most_one_bounded_response_body() -> None:
    """Break caught: a Provider response must never be accumulated with an unbounded read."""
    oversized = b"{" + b" " * MAX_EMBEDDING_RESPONSE_BYTES
    client, opener, _handlers = _client(oversized)

    with pytest.raises(WorkerFailure) as raised:
        client.embed(["one"])

    assert raised.value.code == "embedding_unavailable"
    assert opener.read_sizes == [MAX_EMBEDDING_RESPONSE_BYTES + 1]
    assert -1 not in opener.read_sizes


@pytest.mark.parametrize("payload", [b"{", "not-bytes"])
def test_bounded_loader_rejects_invalid_json_and_nonbyte_reads(payload: object) -> None:
    """Break caught: bounded reads must still reject malformed transport results safely."""

    class Response:
        def read(self, size: int) -> object:
            assert size == MAX_EMBEDDING_RESPONSE_BYTES + 1
            return payload

    with pytest.raises(WorkerFailure) as raised:
        load_embedding_response(Response())

    assert raised.value.code == "embedding_unavailable"


@pytest.mark.parametrize(
    "error",
    [
        URLError("provider-secret-token"),
        TimeoutError("provider-secret-token"),
        OSError("provider-secret-token"),
    ],
)
def test_embed_translates_transport_failures_without_secrets(error: Exception) -> None:
    """Break caught: transport exception details must not escape the worker boundary."""
    client, _opener, _handlers = _client(error)

    with pytest.raises(WorkerFailure) as raised:
        client.embed(["private source text"])

    rendered = f"{raised.value!r} {raised.value}"
    assert (raised.value.code, raised.value.retryable) == ("embedding_unavailable", True)
    assert "provider-secret-token" not in rendered
    assert "private source text" not in rendered


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("17", timedelta(seconds=17)),
        ("0", timedelta(0)),
        ("-1", None),
        ("tomorrow", None),
        ("9" * 100, None),
    ],
)
def test_embed_honors_only_nonnegative_delta_retry_after(
    header: str, expected: timedelta | None
) -> None:
    """Break caught: retry scheduling must preserve a valid Provider delta without trusting dates."""
    headers = HTTPMessage()
    headers["Retry-After"] = header
    error = HTTPError(
        "https://embedding.example/v1/embeddings",
        429,
        "provider-secret-token",
        headers,
        BytesIO(b'{"private":"provider body"}'),
    )
    client, _opener, _handlers = _client(error)

    with pytest.raises(WorkerFailure) as raised:
        client.embed(["private source text"])

    assert raised.value.retry_after == expected
    assert "provider-secret-token" not in repr(raised.value)
    assert "private source text" not in repr(raised.value)


def test_redirect_handler_refuses_redirects() -> None:
    """Break caught: bearer authorization must never be forwarded to any redirect target."""
    client, _opener, handlers = _client({"data": [{"index": 0, "embedding": [1, 2, 3]}]})
    client.embed(["one"])

    assert (
        handlers[0].redirect_request(
            Request("https://embedding.example/v1/embeddings"),
            BytesIO(),
            302,
            "redirect",
            HTTPMessage(),
            "https://attacker.example/collect",
        )
        is None
    )


def test_from_settings_binds_configuration_and_repr_redacts_secret() -> None:
    """Break caught: deployment settings and secrets must not drift at construction/log boundaries."""
    settings = Settings(
        embedding_base_url=AnyHttpUrl("https://embedding.example/v2"),
        embedding_api_key=SecretStr("settings-secret-token"),
        embedding_batch_size=7,
        embedding_timeout_seconds=9.5,
    )

    client = OpenAIEmbeddingClient.from_settings(settings)

    rendered = repr(client)
    assert "settings-secret-token" not in rendered
    assert "embedding.example" not in rendered
    assert "text-embedding-v4" in rendered
    assert "1024" in rendered
