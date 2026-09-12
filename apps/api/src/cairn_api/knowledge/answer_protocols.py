from dataclasses import dataclass
from typing import Literal, cast
from urllib.parse import quote, urlsplit

AnswerProtocol = Literal["openai-compatible", "openai-responses", "anthropic", "gemini"]


class AnswerProtocolError(Exception):
    pass


@dataclass(frozen=True)
class AnswerProtocolRequest:
    endpoint: str
    headers: dict[str, str]
    body: dict[str, object]


def build_answer_request(
    *,
    protocol: str,
    base_url: str,
    api_key: str,
    model: str,
    system_prompt: str,
    user_content: str,
    answer_schema: dict[str, object],
) -> AnswerProtocolRequest:
    if protocol not in {"openai-compatible", "openai-responses", "anthropic", "gemini"}:
        raise ValueError("unsupported answer protocol")
    parsed = urlsplit(base_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or not api_key.strip()
        or not model.strip()
    ):
        raise ValueError("answer provider configuration is invalid")
    base = base_url.rstrip("/")
    if protocol == "openai-compatible":
        return AnswerProtocolRequest(
            f"{base}/chat/completions",
            {"Authorization": f"Bearer {api_key}"},
            {
                "model": model,
                "stream": False,
                "response_format": {"type": "json_object"},
                "max_tokens": 2048,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
            },
        )
    if protocol == "openai-responses":
        return AnswerProtocolRequest(
            f"{base}/responses",
            {"Authorization": f"Bearer {api_key}"},
            {
                "model": model,
                "instructions": system_prompt,
                "input": user_content,
                "stream": False,
                "store": False,
                "max_output_tokens": 2048,
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "cairn_answer",
                        "strict": True,
                        "schema": answer_schema,
                    }
                },
            },
        )
    if protocol == "anthropic":
        return AnswerProtocolRequest(
            f"{base}/messages",
            {"x-api-key": api_key, "anthropic-version": "2023-06-01"},
            {
                "model": model,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_content}],
                "max_tokens": 2048,
                "stream": False,
                "output_config": {"format": {"type": "json_schema", "schema": answer_schema}},
            },
        )
    encoded_model = quote(model, safe="-._~")
    return AnswerProtocolRequest(
        f"{base}/models/{encoded_model}:generateContent",
        {"x-goog-api-key": api_key},
        {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_content}]}],
            "generationConfig": {
                "maxOutputTokens": 2048,
                "responseFormat": {
                    "text": {"mimeType": "application/json", "schema": answer_schema}
                },
            },
        },
    )


def _dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise AnswerProtocolError()
    return cast(dict[str, object], value)


def _list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise AnswerProtocolError()
    return cast(list[object], value)


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AnswerProtocolError()
    return value


def extract_answer_text(*, protocol: str, payload: object) -> str:
    body = _dict(payload)
    if protocol == "openai-compatible":
        choices = _list(body.get("choices"))
        if len(choices) != 1:
            raise AnswerProtocolError()
        choice = _dict(choices[0])
        message = _dict(choice.get("message"))
        if (
            choice.get("finish_reason") != "stop"
            or message.get("refusal")
            or message.get("tool_calls")
        ):
            raise AnswerProtocolError()
        return _text(message.get("content"))
    if protocol == "openai-responses":
        if body.get("status") != "completed":
            raise AnswerProtocolError()
        messages: list[dict[str, object]] = []
        for raw in _list(body.get("output")):
            item = _dict(raw)
            if item.get("type") == "reasoning":
                continue
            if (
                item.get("type") != "message"
                or item.get("status") != "completed"
                or item.get("refusal")
            ):
                raise AnswerProtocolError()
            messages.append(item)
        if len(messages) != 1:
            raise AnswerProtocolError()
        parts = _list(messages[0].get("content"))
        if len(parts) != 1 or _dict(parts[0]).get("type") != "output_text":
            raise AnswerProtocolError()
        return _text(_dict(parts[0]).get("text"))
    if protocol == "anthropic":
        if body.get("stop_reason") != "end_turn" or body.get("refusal"):
            raise AnswerProtocolError()
        texts: list[str] = []
        for raw in _list(body.get("content")):
            part = _dict(raw)
            if part.get("type") != "text" or part.get("refusal"):
                raise AnswerProtocolError()
            texts.append(_text(part.get("text")))
        return _text("".join(texts))
    if protocol == "gemini":
        prompt_feedback = body.get("promptFeedback")
        if prompt_feedback is not None and _dict(prompt_feedback).get("blockReason"):
            raise AnswerProtocolError()
        candidates = _list(body.get("candidates"))
        if len(candidates) != 1:
            raise AnswerProtocolError()
        candidate = _dict(candidates[0])
        if candidate.get("finishReason") != "STOP":
            raise AnswerProtocolError()
        safety = candidate.get("safetyRatings")
        if safety is not None and any(_dict(item).get("blocked") for item in _list(safety)):
            raise AnswerProtocolError()
        texts: list[str] = []
        for raw in _list(_dict(candidate.get("content")).get("parts")):
            part = _dict(raw)
            if "text" not in part or not set(part) <= {"text", "thought", "thoughtSignature"}:
                raise AnswerProtocolError()
            thought = part.get("thought", False)
            if not isinstance(thought, bool):
                raise AnswerProtocolError()
            if "thoughtSignature" in part and not isinstance(part["thoughtSignature"], str):
                raise AnswerProtocolError()
            text = _text(part["text"])
            if not thought:
                texts.append(text)
        return _text("".join(texts))
    raise ValueError("unsupported answer protocol")


__all__ = [
    "AnswerProtocol",
    "AnswerProtocolError",
    "AnswerProtocolRequest",
    "build_answer_request",
    "extract_answer_text",
]
