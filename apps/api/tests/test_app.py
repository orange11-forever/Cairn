import logging
import sys
from collections.abc import Iterator
from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from cairn_api.app import create_app
from cairn_api.db.session import Database
from cairn_api.logging import configure_app_logging
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError


def test_uvicorn_leaves_proxy_headers_for_the_application_to_validate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cairn_api import __main__

    run = Mock()
    monkeypatch.setattr("cairn_api.__main__.uvicorn.run", run)
    monkeypatch.setattr(
        __main__,
        "Settings",
        lambda: SimpleNamespace(bind_host="127.0.0.1", http_port=8080, log_level="INFO"),
    )
    monkeypatch.setattr(sys, "argv", ["cairn-api"])

    assert __main__.main() == 0
    run.assert_called_once_with(
        "cairn_api.app:app",
        host="127.0.0.1",
        port=8080,
        log_level="info",
        proxy_headers=False,
    )


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client


def test_health_and_api_version(client: TestClient) -> None:
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {
        "service": "cairn-api",
        "version": "0.1.0",
        "status": "ok",
    }
    assert health.headers["x-request-id"]

    api_root = client.get("/api/v1")
    assert api_root.status_code == 200
    assert api_root.json() == {"version": "v1", "service": "cairn-api"}


def test_openapi_contains_only_approved_paths(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert set(response.json()["paths"]) == {
        "/health",
        "/ready",
        "/api/v1",
        "/api/v1/login",
        "/api/v1/session",
        "/api/v1/logout",
        "/api/v1/organizations/{organization_id}",
    }


def test_openapi_declares_logout_csrf_header() -> None:
    operation = create_app().openapi()["paths"]["/api/v1/logout"]["post"]

    assert operation["parameters"] == [
        {
            "name": "X-CSRF-Token",
            "in": "header",
            "required": False,
            "schema": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "title": "X-Csrf-Token",
            },
        }
    ]


def test_health_does_not_touch_database() -> None:
    database = Mock(spec=Database)

    with TestClient(create_app(database=database)) as client:
        response = client.get("/health")

    assert response.status_code == 200
    database.check_ready.assert_not_called()


def test_ready_reports_database_success() -> None:
    database = Mock(spec=Database)

    with TestClient(create_app(database=database)) as client:
        response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    database.check_ready.assert_called_once_with()


def test_ready_reports_database_failure_with_trace_id() -> None:
    database = Mock(spec=Database)
    database.check_ready.side_effect = OperationalError("SELECT 1", {}, Exception("down"))

    with TestClient(create_app(database=database), raise_server_exceptions=False) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.json()["code"] == "database_unavailable"
    assert response.json()["message"] == "数据库暂时不可用"
    assert response.json()["traceId"] == response.headers["x-request-id"]
    assert "SELECT 1" not in response.text
    assert "down" not in response.text


def test_ready_does_not_normalize_programming_errors() -> None:
    database = Mock(spec=Database)
    database.check_ready.side_effect = RuntimeError("programming mistake")

    with TestClient(create_app(database=database), raise_server_exceptions=False) as client:
        response = client.get("/ready")

    assert response.status_code == 500
    assert response.json()["code"] == "internal_error"


def test_app_lifespan_disposes_database() -> None:
    database = Mock(spec=Database)

    with TestClient(create_app(database=database)):
        database.dispose.assert_not_called()

    database.dispose.assert_called_once_with()


def test_unknown_route_has_normalized_error_and_generated_request_id(
    client: TestClient,
) -> None:
    response = client.get("/missing")
    body = response.json()

    assert response.status_code == 404
    assert body == {
        "message": "请求的资源不存在",
        "code": "not_found",
        "traceId": response.headers["x-request-id"],
    }


def test_valid_request_id_is_transmitted(client: TestClient) -> None:
    response = client.get("/missing", headers={"X-Request-ID": "req-test-123"})

    assert response.headers["x-request-id"] == "req-test-123"
    assert response.json()["traceId"] == "req-test-123"


def test_invalid_request_id_is_replaced(client: TestClient) -> None:
    response = client.get("/missing", headers={"X-Request-ID": "invalid request id"})

    assert response.headers["x-request-id"] != "invalid request id"
    assert response.json()["traceId"] == response.headers["x-request-id"]


def test_method_not_allowed_is_normalized(client: TestClient) -> None:
    response = client.post("/health")

    assert response.status_code == 405
    assert response.json()["code"] == "method_not_allowed"
    assert response.json()["message"] == "请求方法不被允许"
    assert response.json()["traceId"] == response.headers["x-request-id"]


def test_login_openapi_declares_rate_limit_error() -> None:
    schema = create_app().openapi()
    responses = schema["paths"]["/api/v1/login"]["post"]["responses"]
    assert "429" in responses
    assert responses["429"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/ErrorBody"
    )


def test_error_response_only_forwards_server_retry_after_header() -> None:
    from cairn_api.errors import ApiProblem

    app = create_app()

    @app.get("/_test/rate-limit", include_in_schema=False)
    def _rate_limit_probe() -> None:  # pyright: ignore[reportUnusedFunction]
        raise ApiProblem(
            status_code=429,
            code="login_rate_limited",
            message="too many",
            headers={"Retry-After": "12", "X-User-Header": "ignored"},
        )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/_test/rate-limit")

    assert response.status_code == 429
    assert response.headers["retry-after"] == "12"
    assert "x-user-header" not in response.headers


def test_request_validation_error_is_normalized() -> None:
    app = create_app()

    @app.get("/_test/validation", include_in_schema=False)
    def _validation_probe(  # pyright: ignore[reportUnusedFunction]
        limit: int,
    ) -> dict[str, int]:
        return {"limit": limit}

    with TestClient(app) as client:
        response = client.get("/_test/validation", params={"limit": "invalid"})

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert response.json()["message"] == "请求参数无效"
    assert response.json()["traceId"] == response.headers["x-request-id"]


def test_internal_error_does_not_leak_details() -> None:
    app: FastAPI = create_app()

    @app.get("/_test/error", include_in_schema=False)
    def _fail() -> None:  # pyright: ignore[reportUnusedFunction]
        raise RuntimeError("secret stack detail")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/_test/error")

    assert response.status_code == 500
    assert response.json()["code"] == "internal_error"
    assert response.json()["message"] == "服务器内部错误"
    assert response.json()["traceId"] == response.headers["x-request-id"]
    assert "secret stack detail" not in response.text


def test_configured_cors_origin_handles_credentialed_preflight(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from cairn_api.settings import Settings

    settings = Settings(
        cors_origins="http://localhost:5500",
        _env_file=None,  # pyright: ignore[reportCallIssue]
    )
    with TestClient(create_app(settings)) as client:
        response = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:5500",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "X-CSRF-Token",
            },
        )

    assert response.status_code == 200
    request_id = response.headers["x-request-id"]
    captured = capsys.readouterr()
    assert request_id
    assert f"request_id={request_id}" in captured.err
    assert "OPTIONS /health status=200" in captured.err
    assert response.headers["access-control-allow-origin"] == "http://localhost:5500"
    assert response.headers["access-control-allow-credentials"] == "true"
    assert "X-CSRF-Token" in response.headers["access-control-allow-headers"]


def test_unconfigured_origin_receives_no_cors_permission() -> None:
    from cairn_api.settings import Settings

    settings = Settings(cors_origins="http://localhost:5500", _env_file=None)  # pyright: ignore[reportCallIssue]
    with TestClient(create_app(settings)) as client:
        response = client.get("/health", headers={"Origin": "https://attacker.example"})

    assert "access-control-allow-origin" not in response.headers


def test_cairn_logger_formats_request_id() -> None:
    stream = StringIO()
    logger = configure_app_logging("INFO", stream=stream)
    logger.error("probe", extra={"request_id": "req-log-123"})

    assert "request_id=req-log-123" in stream.getvalue()
    logger.handlers.clear()


def test_configure_app_logging_reenables_disabled_logger() -> None:
    logger = logging.getLogger("cairn_api")
    logger.disabled = True
    stream = StringIO()
    try:
        configured = configure_app_logging("INFO", stream=stream)
        configured.error("probe", extra={"request_id": "req-reenabled-123"})
        assert "request_id=req-reenabled-123" in stream.getvalue()
    finally:
        logger.handlers.clear()
        logger.disabled = False


def test_request_completion_log_contains_response_request_id(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health", headers={"X-Request-ID": "req-access-456"})

    captured = capsys.readouterr()
    assert response.status_code == 200
    assert "request_id=req-access-456" in captured.err
    assert "GET /health status=200" in captured.err


def test_unhandled_error_correlates_response_body_header_and_formatted_log(
    capsys: pytest.CaptureFixture[str],
) -> None:
    app = create_app()

    @app.get("/_test/log-error", include_in_schema=False)
    def _log_error() -> None:  # pyright: ignore[reportUnusedFunction]
        raise RuntimeError("private detail")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/_test/log-error", headers={"X-Request-ID": "req-correlated-789"})

    captured = capsys.readouterr()
    assert response.status_code == 500
    assert response.headers["x-request-id"] == "req-correlated-789"
    assert response.json()["traceId"] == "req-correlated-789"
    assert "request_id=req-correlated-789" in captured.err
    assert "Unhandled API exception" in captured.err
