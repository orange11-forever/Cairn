import json
import math
from collections.abc import Callable, Sequence
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from cairn_worker.errors import WorkerFailure

if TYPE_CHECKING:
    from cairn_api.settings import Settings

MAX_EMBEDDING_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_RETRY_AFTER_SECONDS = str(timedelta.max.days * 86_400 + timedelta.max.seconds)


class EmbeddingClient(Protocol):
    def embed(self, inputs: Sequence[str]) -> list[list[float]]: ...


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs


OpenerFactory = Callable[..., Any]


def _unavailable(*, retry_after: timedelta | None = None) -> WorkerFailure:
    return WorkerFailure.for_code("embedding_unavailable", "", retry_after=retry_after)


def _retry_after(error: HTTPError) -> timedelta | None:
    value = error.headers.get("Retry-After")
    if value is None or not value.isascii() or not value.isdecimal():
        return None
    normalized = value.lstrip("0") or "0"
    if len(normalized) > len(_MAX_RETRY_AFTER_SECONDS) or (
        len(normalized) == len(_MAX_RETRY_AFTER_SECONDS) and normalized > _MAX_RETRY_AFTER_SECONDS
    ):
        return timedelta.max
    return timedelta(seconds=int(normalized))


def _parse_vector(value: object, dimensions: int) -> list[float]:
    if not isinstance(value, list):
        raise _unavailable()
    values = cast(list[object], value)
    if len(values) != dimensions:
        raise WorkerFailure.for_code("embedding_dimension_mismatch", "")
    vector: list[float] = []
    for element in values:
        if isinstance(element, bool) or not isinstance(element, int | float):
            raise _unavailable()
        try:
            number = float(element)
        except (OverflowError, ValueError):
            raise _unavailable() from None
        if not math.isfinite(number):
            raise _unavailable()
        vector.append(number)
    return vector


def load_embedding_response(response: Any) -> object:
    try:
        payload = response.read(MAX_EMBEDDING_RESPONSE_BYTES + 1)
    except (OSError, TimeoutError):
        raise _unavailable() from None
    if not isinstance(payload, bytes) or len(payload) > MAX_EMBEDDING_RESPONSE_BYTES:
        raise _unavailable()
    try:
        return json.loads(payload)
    except (RecursionError, TypeError, UnicodeError, ValueError):
        raise _unavailable() from None


def parse_embedding_response(
    body: object,
    *,
    expected_count: int,
    dimensions: int,
) -> list[list[float]]:
    if not isinstance(body, dict):
        raise _unavailable()
    data = cast(dict[str, object], body).get("data")
    if not isinstance(data, list):
        raise _unavailable()
    records = cast(list[object], data)
    if len(records) != expected_count:
        raise _unavailable()
    vectors: list[list[float] | None] = [None] * expected_count
    for candidate in records:
        if not isinstance(candidate, dict):
            raise _unavailable()
        record = cast(dict[str, object], candidate)
        index = record.get("index")
        if (
            isinstance(index, bool)
            or not isinstance(index, int)
            or index < 0
            or index >= expected_count
            or vectors[index] is not None
        ):
            raise _unavailable()
        vectors[index] = _parse_vector(record.get("embedding"), dimensions)
    if any(vector is None for vector in vectors):
        raise _unavailable()
    return cast(list[list[float]], vectors)


class OpenAIEmbeddingClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        dimensions: int,
        timeout_seconds: float,
        maximum_batch_size: int,
        provider_key: str = "default",
        opener_factory: OpenerFactory = build_opener,
    ) -> None:
        if dimensions <= 0 or timeout_seconds <= 0 or maximum_batch_size <= 0:
            raise ValueError("embedding client limits must be positive")
        self._endpoint = f"{base_url.rstrip('/')}/embeddings"
        self._api_key = api_key
        self.provider_key = provider_key
        self._model = model
        self.model = model
        self._dimensions = dimensions
        self.dimensions = dimensions
        self._timeout_seconds = timeout_seconds
        self._maximum_batch_size = maximum_batch_size
        self.maximum_batch_size = maximum_batch_size
        self._opener_factory = opener_factory

    @classmethod
    def from_settings(cls, settings: "Settings") -> "OpenAIEmbeddingClient":
        return cls(
            base_url=str(settings.embedding_base_url),
            api_key=settings.embedding_api_key.get_secret_value(),
            provider_key=settings.embedding_provider_key,
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
            timeout_seconds=settings.embedding_timeout_seconds,
            maximum_batch_size=settings.embedding_batch_size,
        )

    def __repr__(self) -> str:
        return (
            f"OpenAIEmbeddingClient(model={self._model!r}, "
            f"dimensions={self._dimensions}, maximum_batch_size={self._maximum_batch_size})"
        )

    def embed(self, inputs: Sequence[str]) -> list[list[float]]:
        values = list(inputs)
        if not values or len(values) > self._maximum_batch_size:
            raise ValueError("embedding input batch must be nonempty and within configured limit")
        payload = json.dumps(
            {
                "input": values,
                "model": self._model,
                "dimensions": self._dimensions,
            }
        ).encode("utf-8")
        request = Request(
            self._endpoint,
            data=payload,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            opener = self._opener_factory(_RejectRedirects())
            with opener.open(request, timeout=self._timeout_seconds) as response:
                body = load_embedding_response(response)
        except HTTPError as error:
            raise _unavailable(retry_after=_retry_after(error)) from None
        except (URLError, OSError, TimeoutError, UnicodeError, ValueError, TypeError):
            raise _unavailable() from None
        return parse_embedding_response(
            body,
            expected_count=len(values),
            dimensions=self._dimensions,
        )


__all__ = [
    "MAX_EMBEDDING_RESPONSE_BYTES",
    "EmbeddingClient",
    "OpenAIEmbeddingClient",
    "load_embedding_response",
    "parse_embedding_response",
]
