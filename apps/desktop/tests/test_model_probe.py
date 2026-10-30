import json

import httpx
import pytest
from cairn_desktop.models import EmbeddingConnection, ModelConnection


def test_probe_distinguishes_connection_from_actual_call_without_disclosing_remote_errors():
    from cairn_desktop.model_probe import probe_connection

    connection = ModelConnection(
        protocol="openai-compatible",
        baseUrl="https://controlled.example/v1",
        model="synthetic",
        apiKey="private-test-key",
    )
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(401, text="echo private-test-key")

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = probe_connection(connection, client=client)
    assert result["connected"] is True and result["callSucceeded"] is False
    assert "401" in result["message"] and "private-test-key" not in json.dumps(result)
    assert requests[0]["model"] == "synthetic"


@pytest.mark.parametrize(
    "body, expected",
    [
        ({"choices": [{"finish_reason": "stop", "message": {"content": '{"ok":true}'}}]}, True),
        ({"choices": [{"finish_reason": "stop", "message": {"content": "bad-output"}}]}, False),
        ({"error": "wrong protocol"}, False),
        ({"choices": [{"finish_reason": "stop", "message": {"content": '{"ok":1}'}}]}, False),
    ],
)
def test_probe_validates_answer_response(body, expected):
    from cairn_desktop.model_probe import probe_connection

    connection = ModelConnection(
        protocol="openai-compatible",
        baseUrl="https://controlled.example/v1",
        model="synthetic",
        apiKey="test-key",
    )
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body))
    ) as client:
        result = probe_connection(connection, client=client)
    assert result["connected"] is True and result["callSucceeded"] is expected


def test_probe_requires_real_1024_dimensional_finite_embedding():
    from cairn_desktop.model_probe import probe_connection

    connection = EmbeddingConnection(
        baseUrl="https://controlled.example/v1", model="synthetic", apiKey="test-key"
    )
    for vector, expected in [([0.1] * 1024, True), ([0.1] * 768, False), (["x"] * 1024, False)]:

        def respond(request, vector=vector):
            assert request.url.path == "/v1/embeddings"
            assert json.loads(request.content)["dimensions"] == 1024
            return httpx.Response(200, json={"data": [{"index": 0, "embedding": vector}]})

        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            result = probe_connection(connection, client=client)
        assert result["callSucceeded"] is expected


def test_probe_timeout_is_reported_as_unconfirmed_connection():
    from cairn_desktop.model_probe import probe_connection

    def fail(request):
        raise httpx.ConnectTimeout("private-test-key")

    connection = ModelConnection(
        protocol="openai-compatible",
        baseUrl="https://controlled.example/v1",
        model="synthetic",
        apiKey="test-key",
    )
    with httpx.Client(transport=httpx.MockTransport(fail)) as client:
        result = probe_connection(connection, client=client)
    assert result["connected"] is False and result["callSucceeded"] is False
    assert "超时" in result["message"] and "private-test-key" not in json.dumps(result)


def test_live_http_probe_uses_each_selected_model_and_never_saves_configuration(
    tmp_path, monkeypatch
):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    from cairn_desktop.model_probe import probe_model_settings

    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append((body["model"], self.headers["Authorization"]))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {"choices": [{"finish_reason": "stop", "message": {"content": '{"ok":true}'}}]}
                ).encode()
            )

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        address = f"http://127.0.0.1:{server.server_port}/v1"
        models = [
            {
                "id": name,
                "name": name,
                "protocol": "openai-compatible",
                "baseUrl": address,
                "model": name,
                "apiKey": f"test-{name}-key",
            }
            for name in ("first", "second")
        ]
        config = {"answerModels": models, "defaultModelId": "first", "embedding": None}
        for name in ("first", "second"):
            result = probe_model_settings(
                tmp_path, {"configuration": config, "kind": "answer", "modelId": name}
            )
            assert result["connected"] is True and result["callSucceeded"] is True
        assert not (tmp_path / "model-settings.dpapi").exists()
        assert calls == [("first", "Bearer test-first-key"), ("second", "Bearer test-second-key")]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
