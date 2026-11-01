import asyncio
import json
import threading
import time
from functools import partial

import httpx
import pytest
from cairn_api.knowledge.answer_protocols import AnswerProtocol
from cairn_api.knowledge.answer_provider import AnswerProviderInvalidResponse, OpenAIAnswerProvider
from cairn_api.workspace.coding import Cancelled, sanitize


@pytest.mark.parametrize('protocol', ['openai-compatible', 'openai-responses', 'anthropic', 'gemini'])
def test_coding_step_uses_selected_model_and_parses_existing_protocols(protocol: AnswerProtocol, monkeypatch: pytest.MonkeyPatch) -> None:
    text = json.dumps({'message': 'Read the entry', 'action': {'kind': 'read_file', 'path': 'main.py'}})
    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert 'main.py' in request.content.decode()
        if protocol == 'openai-compatible':
            assert body['model'] == 'selected-model'
            response = {'choices': [{'finish_reason': 'stop', 'message': {'content': text}}]}
        elif protocol == 'openai-responses':
            assert body['store'] is False
            assert 'anyOf' in json.dumps(body['text']['format']['schema'])
            response = {'status': 'completed', 'output': [{'type': 'message', 'status': 'completed', 'content': [{'type': 'output_text', 'text': text}]}]}
        elif protocol == 'anthropic':
            response = {'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': text}]}
        else:
            response = {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': text}]}}]}
        return httpx.Response(200, json=response)
    monkeypatch.setattr(httpx, 'AsyncClient', partial(httpx.AsyncClient, transport=httpx.MockTransport(handle)))
    provider = OpenAIAnswerProvider(base_url='https://model.example/v1', api_key='secret', model='selected-model',
        timeout_seconds=5, protocol=protocol, client=httpx.Client(transport=httpx.MockTransport(handle)))
    result = provider.coding_step(context={'files': ['main.py']}, check_cancelled=lambda: None)
    assert result.action.kind == 'read_file'


def test_invalid_coding_action_is_rejected_before_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, 'AsyncClient', partial(httpx.AsyncClient, transport=httpx.MockTransport(lambda _: httpx.Response(200, json={
        'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({'message': 'run', 'action': {'kind': 'shell', 'command': 'touch bad'}})}}],
    }))))
    provider = OpenAIAnswerProvider(base_url='https://model.example/v1', api_key='secret', model='selected-model',
        timeout_seconds=5, client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={
            'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({'message': 'run', 'action': {'kind': 'shell', 'command': 'touch bad'}})}}],
        }))))
    with pytest.raises(AnswerProviderInvalidResponse):
        provider.coding_step(context={}, check_cancelled=lambda: None)


def test_silent_model_read_can_be_cancelled_without_waiting_for_http_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    arrived = threading.Event()
    stop = threading.Event()
    closed = threading.Event()
    class SilentResponse(httpx.AsyncByteStream):
        async def __aiter__(self):
            arrived.set()
            try:
                await asyncio.sleep(60)
                yield b'never'
            finally:
                closed.set()
    async def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=SilentResponse())
    original_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', partial(original_client, transport=httpx.MockTransport(handle)))
    # Also supply a silent sync stream for the old implementation, so the test
    # fails on cancellation latency rather than attempting an external request.
    class SyncSilent(httpx.SyncByteStream):
        def __iter__(self):
            arrived.set()
            time.sleep(2)
            yield b'{}'
    provider = OpenAIAnswerProvider(base_url='https://model.example/v1', api_key='secret', model='selected-model', timeout_seconds=5,
        client=httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=SyncSilent()))))
    result: list[str] = []
    def check() -> None:
        if stop.is_set():
            raise Cancelled()
    def run() -> None:
        try:
            provider.coding_step(context={}, check_cancelled=check)
        except Cancelled:
            result.append('cancelled')
    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    assert arrived.wait(2)
    stop.set()
    worker.join(timeout=0.8)
    assert not worker.is_alive(), 'Cancellation remained blocked in the model read'
    assert result == ['cancelled'] and closed.is_set()


def test_model_output_redaction_covers_token_only_repository_urls() -> None:
    assert sanitize('origin https://mytoken@github.example/repo') == 'origin https://[REDACTED]@github.example/repo'
