from collections.abc import Iterator

import pytest
from cairn_api.app import create_app
from fastapi import FastAPI
from fastapi.testclient import TestClient


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
    assert set(response.json()["paths"]) == {"/health", "/api/v1"}


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
