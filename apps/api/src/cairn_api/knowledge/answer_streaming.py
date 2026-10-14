"""Bounded Responses SSE and completed structured paragraph decoding."""

import codecs
import json
import re
from collections.abc import Callable, Iterable, Iterator
from typing import cast

from cairn_api.knowledge.answer_protocols import AnswerProtocolError, extract_answer_text
from cairn_api.knowledge.answer_provider import (
    MAX_ANSWER_PARAGRAPHS,
    MAX_ANSWER_RESPONSE_BYTES,
    MAX_ANSWER_TEXT_CODEPOINTS,
    AnswerProviderInvalidResponse,
    ProviderAnswer,
    ProviderParagraph,
)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise AnswerProviderInvalidResponse()
        result[key] = value
    return result


def sse_data(chunks: Iterable[bytes], check: Callable[[], None]) -> Iterator[str]:
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    pending = ""
    data: list[str] = []
    size = 0
    for chunk in chunks:
        check()
        size += len(chunk)
        if size > MAX_ANSWER_RESPONSE_BYTES:
            raise AnswerProviderInvalidResponse()
        pending += decoder.decode(chunk)
        while "\n" in pending:
            line, pending = pending.split("\n", 1)
            line = line.removesuffix("\r")
            if not line:
                if data:
                    yield "\n".join(data)
                    data = []
            elif line.startswith("data:"):
                data.append(line[5:].removeprefix(" "))
    pending += decoder.decode(b"", final=True)
    if pending or data:
        raise AnswerProviderInvalidResponse()


class ParagraphDecoder:
    def __init__(self, known: set[str], receive: Callable[[ProviderParagraph], None]) -> None:
        self.text = ""
        self.emitted: list[ProviderParagraph] = []
        self._known = known
        self._receive = receive
        self._cursor: int | None = None
        self._after_item = False
        self._ended = False
        self._json = json.JSONDecoder(object_pairs_hook=_unique_object)

    def feed(self, delta: str) -> None:
        self.text += delta
        if len(self.text.encode("utf-8")) > MAX_ANSWER_RESPONSE_BYTES:
            raise AnswerProviderInvalidResponse()
        if self._cursor is None:
            # Schema order is requested explicitly. Other valid key orders remain
            # accepted at completion, without risking a preview of unknown status.
            prefix = re.match(
                r'^\s*\{\s*"status"\s*:\s*"answered"\s*,\s*"paragraphs"\s*:\s*\[', self.text
            )
            if prefix is None:
                return
            self._cursor = prefix.end()
        while not self._ended:
            cursor = self._cursor
            while cursor < len(self.text) and self.text[cursor].isspace():
                cursor += 1
            if cursor == len(self.text):
                return
            if self.text[cursor] == "]":
                self._ended = True
                return
            if self._after_item:
                if self.text[cursor] != ",":
                    raise AnswerProviderInvalidResponse()
                cursor += 1
                while cursor < len(self.text) and self.text[cursor].isspace():
                    cursor += 1
            try:
                value, end = self._json.raw_decode(self.text, cursor)
            except json.JSONDecodeError:
                return  # A complete object is required before validation/emission.
            paragraph = ProviderParagraph.model_validate(value)
            if not set(paragraph.citation_ids) <= self._known:
                raise AnswerProviderInvalidResponse()
            if (
                len(self.emitted) >= MAX_ANSWER_PARAGRAPHS
                or sum(len(p.text) for p in self.emitted) + len(paragraph.text)
                > MAX_ANSWER_TEXT_CODEPOINTS
            ):
                raise AnswerProviderInvalidResponse()
            self._cursor = end
            self._after_item = True
            self.emitted.append(paragraph)
            self._receive(paragraph)

    def finish(self, response: object) -> ProviderAnswer:
        final_text = extract_answer_text(protocol="openai-responses", payload=response)
        if final_text != self.text:
            raise AnswerProviderInvalidResponse()
        answer = ProviderAnswer.model_validate(
            json.loads(final_text, object_pairs_hook=_unique_object)
        )
        if any(not set(p.citation_ids) <= self._known for p in answer.paragraphs):
            raise AnswerProviderInvalidResponse()
        if answer.paragraphs[: len(self.emitted)] != self.emitted:
            raise AnswerProviderInvalidResponse()
        return answer


def decode_responses(
    chunks: Iterable[bytes],
    *,
    known: set[str],
    receive: Callable[[ProviderParagraph], None],
    check: Callable[[], None],
) -> ProviderAnswer:
    paragraphs = ParagraphDecoder(known, receive)
    target: tuple[object, object, object] | None = None
    try:
        for data in sse_data(chunks, check):
            payload = json.loads(data, object_pairs_hook=_unique_object)
            if not isinstance(payload, dict):
                raise AnswerProviderInvalidResponse()
            payload = cast(dict[str, object], payload)
            kind = payload.get("type")
            if kind == "response.output_text.delta":
                delta = payload.get("delta")
                if not isinstance(delta, str):
                    raise AnswerProviderInvalidResponse()
                current = (
                    payload.get("item_id"),
                    payload.get("output_index"),
                    payload.get("content_index"),
                )
                if target is not None and current != target:
                    raise AnswerProviderInvalidResponse()
                target = current
                paragraphs.feed(delta)
            elif kind == "response.completed":
                check()
                return paragraphs.finish(payload.get("response"))
            elif kind in {
                "error",
                "response.failed",
                "response.incomplete",
                "response.refusal.delta",
                "response.refusal.done",
            }:
                raise AnswerProviderInvalidResponse()
        raise AnswerProviderInvalidResponse()
    except (AnswerProtocolError, ValueError, TypeError, RecursionError, UnicodeError):
        raise AnswerProviderInvalidResponse() from None
