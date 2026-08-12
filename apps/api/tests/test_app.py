import logging
import sys
from collections.abc import Iterator
from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from cairn_api.app import create_app
from cairn_api.db.session import Database
from cairn_api.knowledge.object_store import ObjectStore, ObjectStoreUnavailable
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


def test_object_store_bootstrap_cli_uses_settings_origins_and_closes_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cairn_api import __main__

    store = Mock()
    bootstrap = Mock(return_value=store)
    settings = SimpleNamespace(cors_origins=["https://web.example"])
    monkeypatch.setattr(__main__, "Settings", lambda: settings)
    monkeypatch.setattr(__main__, "bootstrap_object_store", bootstrap)
    monkeypatch.setattr(sys, "argv", ["cairn-api", "object-store-bootstrap"])

    assert __main__.main() == 0
    bootstrap.assert_called_once_with(settings, allowed_origins=settings.cors_origins)
    store.close.assert_called_once_with()


def test_upload_cleanup_cli_dispatches_maintenance_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cairn_api import __main__

    cleanup = Mock(return_value=0)
    monkeypatch.setattr(__main__, "run_upload_cleanup_command", cleanup)
    monkeypatch.setattr(sys, "argv", ["cairn-api", "upload-cleanup"])

    assert __main__.main() == 0
    cleanup.assert_called_once_with()


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
        "/api/v1/organizations/{organization_id}/memberships",
        "/api/v1/organizations/{organization_id}/memberships/{membership_id}",
        "/api/v1/projects",
        "/api/v1/projects/{project_id}",
        "/api/v1/projects/{project_id}/acl",
        "/api/v1/projects/{project_id}/acl/{principal_type}/{principal_id}",
        "/api/v1/projects/{project_id}/events",
        "/api/v1/projects/{project_id}/knowledge/uploads",
        "/api/v1/projects/{project_id}/knowledge/uploads/{upload_id}/complete",
        "/api/v1/projects/{project_id}/knowledge/batches/{batch_id}",
        "/api/v1/projects/{project_id}/knowledge/resources",
        "/api/v1/projects/{project_id}/knowledge/resources/{resource_id}",
        "/api/v1/projects/{project_id}/knowledge/resources/{resource_id}/versions/{version_id}/retry",
        "/api/v1/projects/{project_id}/knowledge/resources/{resource_id}/download",
        "/api/v1/projects/{project_id}/knowledge/resources/{resource_id}/chunks/{chunk_id}",
        "/api/v1/projects/{project_id}/tasks",
        "/api/v1/tasks/{task_id}/status",
        "/api/v1/tasks/{task_id}/dependencies",
    }


def test_openapi_ready_declares_success_and_dependency_failure_contracts() -> None:
    operation = create_app().openapi()["paths"]["/ready"]["get"]

    assert set(operation["responses"]) == {"200", "503"}
    assert operation["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/ReadyResponse")
    assert operation["responses"]["503"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/ErrorBody")
    for status_code in ("200", "503"):
        request_id = operation["responses"][status_code]["headers"]["X-Request-ID"]
        assert request_id["schema"] == {"type": "string"}


def test_openapi_project_requests_forbid_identity_fields_and_bound_values() -> None:
    schema = create_app().openapi()
    components = schema["components"]["schemas"]
    request_names = {
        "ProjectCreateRequest",
        "TaskCreateRequest",
        "TaskStatusUpdateRequest",
        "TaskDependencyCreateRequest",
    }
    forbidden = {"org_id", "orgId", "created_by", "createdBy", "actor", "actorId"}

    for name in request_names:
        request_schema = components[name]
        assert request_schema["additionalProperties"] is False
        assert forbidden.isdisjoint(request_schema.get("properties", {}))

    assert components["ProjectCreateRequest"]["properties"]["name"]["maxLength"] == 160
    assert components["TaskCreateRequest"]["properties"]["title"]["maxLength"] == 240
    assert components["TaskCreateRequest"]["properties"]["priority"]["$ref"].endswith(
        "/TaskPriority"
    )
    assert components["TaskStatusUpdateRequest"]["properties"]["status"]["$ref"].endswith(
        "/TaskStatus"
    )
    dependency_property = components["TaskDependencyCreateRequest"]["properties"][
        "predecessorTaskId"
    ]
    assert "predecessor" in dependency_property["description"]
    assert "successor" in dependency_property["description"]

    mutation_operations = [
        schema["paths"]["/api/v1/projects"]["post"],
        schema["paths"]["/api/v1/projects/{project_id}/tasks"]["post"],
        schema["paths"]["/api/v1/tasks/{task_id}/status"]["patch"],
        schema["paths"]["/api/v1/tasks/{task_id}/dependencies"]["post"],
    ]
    for operation in mutation_operations:
        csrf_parameter = next(
            parameter
            for parameter in operation["parameters"]
            if parameter["name"] == "X-CSRF-Token"
        )
        assert csrf_parameter["required"] is True
        assert operation["responses"]["403"]["content"]["application/json"]["schema"][
            "$ref"
        ].endswith("/ErrorBody")


def test_openapi_knowledge_uploads_are_json_only_bounded_and_traced() -> None:
    schema = create_app().openapi()
    components = schema["components"]["schemas"]
    request_schema = components["UploadBatchCreateRequest"]
    intent_schema = components["UploadFileIntent"]
    paths = schema["paths"]
    create = paths["/api/v1/projects/{project_id}/knowledge/uploads"]["post"]
    complete_path = paths["/api/v1/projects/{project_id}/knowledge/uploads/{upload_id}/complete"]

    assert request_schema["additionalProperties"] is False
    assert request_schema["properties"]["files"]["minItems"] == 1
    assert request_schema["properties"]["files"]["maxItems"] == 20
    assert intent_schema["additionalProperties"] is False
    assert set(intent_schema["properties"]) == {
        "fileName",
        "mediaType",
        "sizeBytes",
        "sha256",
    }
    assert intent_schema["properties"]["fileName"]["maxLength"] == 255
    assert intent_schema["properties"]["mediaType"]["maxLength"] == 127
    assert intent_schema["properties"]["sizeBytes"]["exclusiveMinimum"] == 0
    assert intent_schema["properties"]["sha256"]["pattern"] == "^[0-9a-f]{64}$"
    assert set(create["requestBody"]["content"]) == {"application/json"}
    assert set(complete_path) == {"post"}

    for operation, success_status in ((create, "201"), (complete_path["post"], "200")):
        csrf = next(
            parameter
            for parameter in operation["parameters"]
            if parameter["name"] == "X-CSRF-Token"
        )
        assert csrf["required"] is True
        assert "X-Request-ID" in operation["responses"][success_status]["headers"]
        for error_status in ("401", "403", "404", "409", "410", "422", "500", "503"):
            response = operation["responses"][error_status]
            assert response["content"]["application/json"]["schema"]["$ref"].endswith("/ErrorBody")
            assert "X-Request-ID" in response["headers"]


def test_openapi_knowledge_resource_lifecycle_is_bounded_secured_and_traced() -> None:
    schema = create_app().openapi()
    paths = schema["paths"]
    resources = paths["/api/v1/projects/{project_id}/knowledge/resources"]["get"]
    detail_path = paths["/api/v1/projects/{project_id}/knowledge/resources/{resource_id}"]
    retry = paths[
        "/api/v1/projects/{project_id}/knowledge/resources/{resource_id}/versions/"
        "{version_id}/retry"
    ]["post"]
    download = paths["/api/v1/projects/{project_id}/knowledge/resources/{resource_id}/download"][
        "get"
    ]

    parameters = {parameter["name"]: parameter for parameter in resources["parameters"]}
    assert parameters["cursor"]["schema"]["anyOf"][0] == {
        "type": "string",
        "maxLength": 2048,
    }
    assert parameters["limit"]["schema"] == {
        "type": "integer",
        "maximum": 100,
        "minimum": 1,
        "default": 50,
        "title": "Limit",
    }

    operations = [
        paths["/api/v1/projects/{project_id}/knowledge/batches/{batch_id}"]["get"],
        resources,
        detail_path["get"],
        retry,
        detail_path["delete"],
        download,
        paths["/api/v1/projects/{project_id}/knowledge/resources/{resource_id}/chunks/{chunk_id}"][
            "get"
        ],
    ]
    for operation in operations:
        success_status = next(
            code for code in ("200", "204", "307") if code in operation["responses"]
        )
        assert "X-Request-ID" in operation["responses"][success_status]["headers"]
        for error_status in ("401", "404", "422", "500", "503"):
            response = operation["responses"][error_status]
            assert response["content"]["application/json"]["schema"]["$ref"].endswith("/ErrorBody")
            assert "X-Request-ID" in response["headers"]

    for operation in (retry, detail_path["delete"]):
        csrf = next(
            parameter
            for parameter in operation["parameters"]
            if parameter["name"] == "X-CSRF-Token"
        )
        assert csrf["required"] is True
        assert "403" in operation["responses"]
    assert "409" in retry["responses"]
    assert "409" not in detail_path["delete"]["responses"]
    for operation in (resources, detail_path["get"], download):
        assert all(parameter["name"] != "X-CSRF-Token" for parameter in operation["parameters"])

    assert download["responses"]["307"]["headers"]["Location"]["schema"] == {
        "type": "string",
        "format": "uri",
    }
    assert (
        "objectKey" not in schema["components"]["schemas"]["KnowledgeVersionResponse"]["properties"]
    )
    resource_properties = schema["components"]["schemas"]["KnowledgeResourceResponse"][
        "properties"
    ]
    assert "latestVersion" in resource_properties
    assert "currentVersion" not in resource_properties


def test_openapi_project_events_declares_bounded_sse_read_contract() -> None:
    # Break caught: generated clients lose the event route, opaque resume parameter,
    # SSE media type, or pre-stream database error envelope.
    operation = create_app().openapi()["paths"][
        "/api/v1/projects/{project_id}/events"
    ]["get"]
    parameters = {parameter["name"]: parameter for parameter in operation["parameters"]}

    assert set(parameters) == {"project_id", "after"}
    assert parameters["after"]["required"] is False
    assert parameters["after"]["schema"]["anyOf"][0] == {
        "type": "string",
        "maxLength": 2048,
    }
    assert operation["responses"]["200"] == {
        "description": "有界项目事件批次",
        "content": {"text/event-stream": {}},
    }
    assert operation["responses"]["503"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/ErrorBody")


def test_openapi_declares_project_acl_write_contracts() -> None:
    schema = create_app().openapi()
    path = schema["paths"][
        "/api/v1/projects/{project_id}/acl/{principal_type}/{principal_id}"
    ]

    for operation in (path["put"], path["delete"]):
        csrf_parameter = next(
            parameter
            for parameter in operation["parameters"]
            if parameter["name"] == "X-CSRF-Token"
        )
        assert csrf_parameter["required"] is True
        for status_code in ("404", "422", "503"):
            assert operation["responses"][status_code]["content"]["application/json"][
                "schema"
            ]["$ref"].endswith("/ErrorBody")

    request_schema = schema["components"]["schemas"]["AclGrantRequest"]
    assert request_schema["additionalProperties"] is False
    assert set(request_schema["properties"]) == {"permission"}
    permission_ref = request_schema["properties"]["permission"]["$ref"]
    permission_schema = schema["components"]["schemas"][permission_ref.rsplit("/", 1)[-1]]
    assert permission_schema["enum"] == ["read", "write", "manage"]

    for operation in (path["put"], path["delete"]):
        parameters = {parameter["name"]: parameter for parameter in operation["parameters"]}
        assert parameters["project_id"]["schema"]["format"] == "uuid"
        assert parameters["principal_type"]["schema"] == {
            "type": "string",
            "minLength": 1,
            "maxLength": 16,
            "title": "Principal Type",
        }
        assert parameters["principal_id"]["schema"] == {
            "type": "string",
            "minLength": 1,
            "maxLength": 64,
            "title": "Principal Id",
        }


def test_openapi_declares_membership_list_and_role_patch_contracts() -> None:
    schema = create_app().openapi()
    collection = schema["paths"][
        "/api/v1/organizations/{organization_id}/memberships"
    ]
    item = schema["paths"][
        "/api/v1/organizations/{organization_id}/memberships/{membership_id}"
    ]

    assert set(collection) == {"get"}
    assert set(item) == {"patch"}
    csrf_parameter = next(
        parameter
        for parameter in item["patch"]["parameters"]
        if parameter["name"] == "X-CSRF-Token"
    )
    assert csrf_parameter["required"] is True
    request_schema = schema["components"]["schemas"]["MembershipRoleUpdateRequest"]
    assert request_schema["additionalProperties"] is False
    assert set(request_schema["properties"]) == {"role"}
    role_ref = request_schema["properties"]["role"]["$ref"]
    role_schema = schema["components"]["schemas"][role_ref.rsplit("/", 1)[-1]]
    assert role_schema["enum"] == ["owner", "admin", "member", "viewer"]

    parameters = {
        parameter["name"]: parameter for parameter in item["patch"]["parameters"]
    }
    assert parameters["organization_id"]["schema"]["format"] == "uuid"
    assert parameters["membership_id"]["schema"]["format"] == "uuid"


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
    object_store = Mock(spec=ObjectStore)

    with TestClient(create_app(database=database, object_store=object_store)) as client:
        response = client.get("/health")

    assert response.status_code == 200
    database.check_ready.assert_not_called()
    object_store.check_ready.assert_not_called()


def test_ready_reports_database_success() -> None:
    database = Mock(spec=Database)
    object_store = Mock(spec=ObjectStore)

    with TestClient(create_app(database=database, object_store=object_store)) as client:
        response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    database.check_ready.assert_called_once_with()
    object_store.check_ready.assert_called_once_with()


def test_ready_reports_database_failure_with_trace_id() -> None:
    database = Mock(spec=Database)
    object_store = Mock(spec=ObjectStore)
    database.check_ready.side_effect = OperationalError("SELECT 1", {}, Exception("down"))

    with TestClient(
        create_app(database=database, object_store=object_store),
        raise_server_exceptions=False,
    ) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.json()["code"] == "database_unavailable"
    assert response.json()["message"] == "数据库暂时不可用"
    assert response.json()["traceId"] == response.headers["x-request-id"]
    assert "SELECT 1" not in response.text
    assert "down" not in response.text
    object_store.check_ready.assert_not_called()


def test_ready_reports_object_store_failure_with_trace_id() -> None:
    database = Mock(spec=Database)
    object_store = Mock(spec=ObjectStore)
    object_store.check_ready.side_effect = ObjectStoreUnavailable()

    with TestClient(
        create_app(database=database, object_store=object_store),
        raise_server_exceptions=False,
    ) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "code": "object_store_unavailable",
        "message": "对象存储暂时不可用",
        "traceId": response.headers["x-request-id"],
    }
    database.check_ready.assert_called_once_with()


def test_ready_does_not_normalize_programming_errors() -> None:
    database = Mock(spec=Database)
    object_store = Mock(spec=ObjectStore)
    database.check_ready.side_effect = RuntimeError("programming mistake")

    with TestClient(
        create_app(database=database, object_store=object_store),
        raise_server_exceptions=False,
    ) as client:
        response = client.get("/ready")

    assert response.status_code == 500
    assert response.json()["code"] == "internal_error"


def test_app_lifespan_disposes_database() -> None:
    database = Mock(spec=Database)
    object_store = Mock(spec=ObjectStore)

    with TestClient(create_app(database=database, object_store=object_store)):
        database.dispose.assert_not_called()
        object_store.close.assert_not_called()

    database.dispose.assert_called_once_with()
    object_store.close.assert_called_once_with()


def test_app_lifespan_closes_object_store_when_database_disposal_fails() -> None:
    database = Mock(spec=Database)
    database.dispose.side_effect = RuntimeError("database dispose failed")
    object_store = Mock(spec=ObjectStore)

    with (
        pytest.raises(RuntimeError, match="database dispose failed"),
        TestClient(create_app(database=database, object_store=object_store)),
    ):
        pass

    object_store.close.assert_called_once_with()


def test_app_exposes_the_injected_object_store() -> None:
    object_store = Mock(spec=ObjectStore)

    application = create_app(object_store=object_store)

    assert application.state.object_store is object_store


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
    assert response.headers["allow"] == "GET"
    assert response.json()["code"] == "method_not_allowed"
    assert response.json()["message"] == "请求方法不被允许"
    assert response.json()["traceId"] == response.headers["x-request-id"]


@pytest.mark.parametrize(
    ("path", "method", "success_status", "error_statuses"),
    [
        pytest.param(
            "/api/v1/login",
            "post",
            "200",
            {"401", "403", "409", "422", "429", "500", "503"},
            id="login",
        ),
        pytest.param(
            "/api/v1/session",
            "get",
            "200",
            {"401", "500", "503"},
            id="session",
        ),
        pytest.param(
            "/api/v1/logout",
            "post",
            "204",
            {"403", "500", "503"},
            id="logout",
        ),
        pytest.param(
            "/api/v1/organizations/{organization_id}",
            "get",
            "200",
            {"401", "404", "422", "500", "503"},
            id="organization",
        ),
        pytest.param(
            "/api/v1/organizations/{organization_id}/memberships",
            "get",
            "200",
            {"401", "403", "404", "422", "500", "503"},
            id="membership-list",
        ),
        pytest.param(
            "/api/v1/organizations/{organization_id}/memberships/{membership_id}",
            "patch",
            "200",
            {"401", "403", "404", "409", "422", "500", "503"},
            id="membership-update",
        ),
    ],
)
def test_openapi_auth_and_organization_errors_match_runtime_contracts(
    path: str,
    method: str,
    success_status: str,
    error_statuses: set[str],
) -> None:
    schema = create_app().openapi()
    responses = schema["paths"][path][method]["responses"]
    assert set(responses) == {success_status} | error_statuses
    for status_code in error_statuses:
        assert responses[status_code]["content"]["application/json"]["schema"][
            "$ref"
        ].endswith("/ErrorBody")


def test_error_response_forwards_retry_after_but_rejects_unapproved_headers() -> None:
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


def test_internal_error_applies_configured_cors_and_preserves_request_id() -> None:
    from cairn_api.settings import Settings

    origin = "http://localhost:5500"
    app: FastAPI = create_app(
        Settings(cors_origins=origin, _env_file=None)  # pyright: ignore[reportCallIssue]
    )

    @app.get("/_test/cors-error", include_in_schema=False)
    def _fail_with_origin() -> None:  # pyright: ignore[reportUnusedFunction]
        raise RuntimeError("private cross-origin detail")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(
            "/_test/cors-error",
            headers={"Origin": origin, "X-Request-ID": "req-cors-error-500"},
        )

    assert response.status_code == 500
    assert response.json() == {
        "message": "服务器内部错误",
        "code": "internal_error",
        "traceId": "req-cors-error-500",
    }
    assert response.headers["x-request-id"] == "req-cors-error-500"
    assert response.headers["access-control-allow-origin"] == origin
    assert response.headers["access-control-allow-credentials"] == "true"


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
