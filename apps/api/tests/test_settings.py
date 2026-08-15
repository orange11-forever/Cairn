import pytest
from cairn_api.settings import Settings
from pydantic import SecretStr, ValidationError

PRODUCTION_SETTINGS: dict[str, object] = {
    "environment": "production",
    "app_url": "https://cairn.example",
    "session_cookie_secure": True,
    "csrf_secret": "production-only-csrf-secret-with-at-least-32-bytes",
    "auth_rate_limit_secret": "production-only-rate-limit-secret-with-at-least-32-bytes",
    "object_store_access_key": "production-object-store-access-key",
    "object_store_secret_key": "production-object-store-secret-key",
    "object_store_public_endpoint_url": "https://objects.cairn.example",
    "embedding_api_key": "production-embedding-api-key",
    "search_audit_secret": "production-search-audit-secret-at-least-32-bytes",
}


@pytest.mark.parametrize(
    "url",
    [
        "http://objects.example.com",
        "http://127.0.0.1:9000",
        "http://[::1]:9000",
        "http://localhost:9000",
    ],
)
def test_production_requires_https_public_object_store_url(url: str) -> None:
    with pytest.raises(ValidationError, match="HTTPS.*public object-store"):
        production_settings(object_store_public_endpoint_url=url)


@pytest.mark.parametrize(
    "url",
    [
        "https://objects.example.com",
        "https://127.0.0.1:9000",
    ],
)
def test_production_accepts_https_public_object_store_url(url: str) -> None:
    settings = production_settings(object_store_public_endpoint_url=url)

    assert str(settings.object_store_public_endpoint_url).startswith("https://")


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:58081/v1",
        "http://127.0.0.2:58081/v1",
        "http://[::1]:58081/v1",
        "http://localhost:58081/v1",
        "https://embedding.example.com/v1",
    ],
)
def test_production_accepts_https_or_strict_loopback_embedding_url(url: str) -> None:
    settings = production_settings(embedding_base_url=url)

    assert str(settings.embedding_base_url).startswith(("http://", "https://"))


@pytest.mark.parametrize(
    "url",
    [
        "http://embedding.example.com/v1",
        "http://10.0.0.5:58081/v1",
        "http://192.168.1.5:58081/v1",
        "http://embedding.localhost.example/v1",
    ],
)
def test_production_rejects_non_loopback_http_embedding_url(url: str) -> None:
    with pytest.raises(ValidationError, match="HTTPS.*loopback"):
        production_settings(embedding_base_url=url)


def production_settings(**overrides: object) -> Settings:
    values = PRODUCTION_SETTINGS | overrides
    return Settings(**values, _env_file=None)  # pyright: ignore[reportCallIssue]


def test_settings_defaults() -> None:
    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert settings.environment == "development"
    assert settings.database_url == (
        "postgresql+psycopg://cairn:cairn-local-only@127.0.0.1:5432/cairn"
    )
    assert settings.bind_host == "127.0.0.1"
    assert settings.http_port == 8080
    assert settings.app_url is None
    assert settings.cors_origins == []
    assert settings.log_level == "INFO"
    assert settings.session_cookie_name == "cairn_session"
    assert settings.session_cookie_secure is False
    assert settings.session_ttl_seconds == 604800
    assert settings.auth_rate_limit_secret == (
        "local-development-auth-rate-limit-secret-change-before-deploying-32-bytes"
    )
    assert settings.trusted_proxy_cidrs == ()


def test_knowledge_services_default_to_local_runtime() -> None:
    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert str(settings.object_store_endpoint_url) == "http://127.0.0.1:9000/"
    assert str(settings.object_store_public_endpoint_url) == "http://127.0.0.1:9000/"
    assert str(settings.embedding_base_url) == "http://127.0.0.1:58081/v1"


def test_knowledge_settings_have_bounded_local_defaults() -> None:
    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert settings.object_store_region == "us-east-1"
    assert settings.object_store_bucket == "cairn"
    assert settings.object_store_path_style is True
    assert settings.upload_session_ttl_seconds == 900
    assert settings.download_url_ttl_seconds == 300
    assert settings.embedding_provider_key == "local-fake"
    assert settings.embedding_model == "text-embedding-v4"
    assert settings.embedding_dimensions == 1024
    assert settings.embedding_batch_size == 10
    assert settings.embedding_timeout_seconds == 30.0
    assert settings.search_user_limit_per_minute == 30
    assert settings.search_org_limit_per_minute == 300


@pytest.mark.parametrize(
    ("field_name", "url"),
    [
        ("object_store_endpoint_url", "http://access:secret@127.0.0.1:9000"),
        ("object_store_public_endpoint_url", "https://access:secret@objects.example"),
        ("embedding_base_url", "https://api-key:secret@embedding.example/v1"),
    ],
)
def test_knowledge_urls_reject_embedded_credentials(field_name: str, url: str) -> None:
    with pytest.raises(ValidationError, match="credentials"):
        Settings(**{field_name: url}, _env_file=None)  # pyright: ignore[reportCallIssue]


@pytest.mark.parametrize("dimensions", [0, 768, 1536])
def test_embedding_dimensions_are_fixed_for_stage_3a(dimensions: int) -> None:
    with pytest.raises(ValidationError, match="1024"):
        Settings(embedding_dimensions=dimensions, _env_file=None)  # pyright: ignore[reportCallIssue]


@pytest.mark.parametrize("batch_size", [0, 11])
def test_embedding_batch_size_stays_within_provider_contract(batch_size: int) -> None:
    with pytest.raises(ValidationError):
        Settings(embedding_batch_size=batch_size, _env_file=None)  # pyright: ignore[reportCallIssue]


@pytest.mark.parametrize(
    "field_name",
    ["object_store_bucket", "embedding_provider_key", "embedding_model"],
)
def test_knowledge_identifiers_reject_blank_values(field_name: str) -> None:
    with pytest.raises(ValidationError, match="blank"):
        Settings(**{field_name: " \t "}, _env_file=None)  # pyright: ignore[reportCallIssue]


def test_knowledge_credentials_are_redacted_from_settings_representations() -> None:
    plaintext_values = {
        "object_store_access_key": "visible-access-key",
        "object_store_secret_key": "visible-secret-key",
        "embedding_api_key": "visible-embedding-key",
        "search_audit_secret": "visible-audit-secret",
    }

    settings = Settings(**plaintext_values, _env_file=None)  # pyright: ignore[reportCallIssue]

    for field_name, plaintext in plaintext_values.items():
        secret = getattr(settings, field_name)
        assert isinstance(secret, SecretStr)
        assert secret.get_secret_value() == plaintext
        assert plaintext not in repr(settings)
        assert plaintext not in settings.model_dump_json()


@pytest.mark.parametrize(
    ("field_name", "example_value"),
    [
        ("object_store_access_key", "cairn-local"),
        ("object_store_secret_key", "cairn-local-only-change-before-deploying"),
        (
            "search_audit_secret",
            "local-development-search-audit-secret-change-before-deploying-32-bytes",
        ),
    ],
)
def test_production_rejects_example_knowledge_secrets(
    field_name: str, example_value: str
) -> None:
    with pytest.raises(ValidationError, match="example"):
        production_settings(**{field_name: example_value})


@pytest.mark.parametrize(
    "field_name",
    ["object_store_access_key", "object_store_secret_key"],
)
@pytest.mark.parametrize("value", ["", " \t "])
def test_production_rejects_blank_object_store_credentials(
    field_name: str, value: str
) -> None:
    with pytest.raises(ValidationError, match="object-store.*blank"):
        production_settings(**{field_name: value})


@pytest.mark.parametrize(
    ("field_name", "example_value"),
    [
        ("object_store_access_key", " \t cairn-local "),
        (
            "object_store_secret_key",
            " cairn-local-only-change-before-deploying \n",
        ),
        (
            "search_audit_secret",
            " local-development-search-audit-secret-change-before-deploying-32-bytes ",
        ),
    ],
)
def test_production_rejects_padded_example_knowledge_secrets(
    field_name: str, example_value: str
) -> None:
    with pytest.raises(ValidationError, match="example"):
        production_settings(**{field_name: example_value})


@pytest.mark.parametrize("secret", ["", " \t ", "x", "x" * 31])
def test_production_requires_32_utf8_bytes_for_search_audit_secret(secret: str) -> None:
    with pytest.raises(ValidationError, match="search audit secret.*32 bytes"):
        production_settings(search_audit_secret=secret)


def test_production_counts_search_audit_secret_length_in_utf8_bytes() -> None:
    settings = production_settings(search_audit_secret="密" * 16)

    assert settings.search_audit_secret.get_secret_value() == "密" * 16


def test_production_rejects_blank_embedding_api_key() -> None:
    with pytest.raises(ValidationError, match="Embedding API key"):
        production_settings(embedding_api_key=" \t ")


def test_production_requires_enabled_organization_search_limit() -> None:
    with pytest.raises(ValidationError, match="organization search rate limit"):
        production_settings(search_org_limit_per_minute=0)


@pytest.mark.parametrize("port", [0, 65536])
def test_settings_rejects_invalid_port(port: int) -> None:
    with pytest.raises(ValidationError):
        Settings(http_port=port, _env_file=None)  # pyright: ignore[reportCallIssue]


def test_settings_parses_comma_separated_cors_origins() -> None:
    settings = Settings(
        cors_origins=" https://one.example,https://two.example ,, ",
        _env_file=None,  # pyright: ignore[reportCallIssue]
    )

    assert settings.cors_origins == ["https://one.example", "https://two.example"]


def test_settings_rejects_wildcard_cors_origin() -> None:
    with pytest.raises(ValidationError):
        Settings(cors_origins="*", _env_file=None)  # pyright: ignore[reportCallIssue]


def test_settings_rejects_invalid_app_url_and_origin() -> None:
    with pytest.raises(ValidationError):
        Settings(app_url="not-a-url", _env_file=None)  # pyright: ignore[reportCallIssue]
    with pytest.raises(ValidationError, match="APP_URL"):
        Settings(app_url="https://example.com/application", _env_file=None)  # pyright: ignore[reportCallIssue]
    with pytest.raises(ValidationError):
        Settings(cors_origins="https://example.com/path", _env_file=None)  # pyright: ignore[reportCallIssue]


def test_settings_rejects_wildcard_subdomain_origin() -> None:
    with pytest.raises(ValidationError):
        Settings(cors_origins="https://*.example.com", _env_file=None)  # pyright: ignore[reportCallIssue]


@pytest.mark.parametrize(
    "database_url",
    [
        "sqlite:///local.db",
        "postgresql://cairn:password@localhost/cairn",
        "postgresql+asyncpg://cairn:password@localhost/cairn",
    ],
)
def test_settings_require_postgresql_psycopg_driver(database_url: str) -> None:
    with pytest.raises(ValidationError):
        Settings(database_url=database_url, _env_file=None)  # pyright: ignore[reportCallIssue]


@pytest.mark.parametrize(
    "csrf_secret",
    ["", "short", "local-development-secret-change-before-deploying-32-bytes"],
)
def test_production_rejects_missing_short_or_example_csrf_secrets(csrf_secret: str) -> None:
    with pytest.raises(ValidationError):
        production_settings(csrf_secret=csrf_secret)


def test_production_requires_secure_session_cookie() -> None:
    with pytest.raises(ValidationError):
        production_settings(session_cookie_secure=False)


def test_production_requires_app_url() -> None:
    with pytest.raises(ValidationError, match="APP_URL"):
        production_settings(app_url=None)


def test_production_accepts_secure_cookie_and_non_example_secret() -> None:
    settings = production_settings()

    assert settings.session_cookie_secure is True


def test_production_rejects_reused_csrf_and_rate_limit_secret() -> None:
    shared_secret = "production-shared-secret-with-at-least-32-bytes"
    with pytest.raises(ValidationError, match="rate-limit secret"):
        production_settings(
            cors_origins="https://cairn.example",
            csrf_secret=shared_secret,
            auth_rate_limit_secret=shared_secret,
        )


@pytest.mark.parametrize("app_url", ["http://cairn.example", "http://localhost:8080"])
def test_production_rejects_http_app_url(app_url: str) -> None:
    with pytest.raises(ValidationError, match="HTTPS"):
        production_settings(
            app_url=app_url,
        )


def test_production_rejects_http_cors_origin() -> None:
    with pytest.raises(ValidationError, match="HTTPS"):
        production_settings(
            cors_origins="http://frontend.example",
        )


@pytest.mark.parametrize("secret", ["", "short", "local-development-auth-rate-limit-secret-change-before-deploying-32-bytes"])
def test_production_rejects_missing_short_or_example_rate_limit_secret(secret: str) -> None:
    with pytest.raises(ValidationError):
        production_settings(
            auth_rate_limit_secret=secret,
        )


def test_settings_rejects_invalid_trusted_proxy_cidrs() -> None:
    with pytest.raises(ValidationError, match="CIDR"):
        Settings(trusted_proxy_cidrs="10.0.0.0/not-cidr", _env_file=None)  # pyright: ignore[reportCallIssue]


def test_settings_parses_comma_separated_trusted_proxy_cidrs_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CAIRN_TRUSTED_PROXY_CIDRS", "10.0.0.0/8, 2001:db8::/32")

    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert [str(network) for network in settings.trusted_proxy_cidrs] == [
        "10.0.0.0/8",
        "2001:db8::/32",
    ]


def test_production_accepts_https_values_and_normalizes_origins() -> None:
    settings = production_settings(
        app_url="https://cairn.example/",
        cors_origins="https://frontend.example/",
        trusted_proxy_cidrs="10.0.0.0/8, 2001:db8::/32",
    )
    assert str(settings.app_url) == "https://cairn.example/"
    assert settings.cors_origins == ["https://frontend.example"]
    assert [str(network) for network in settings.trusted_proxy_cidrs] == ["10.0.0.0/8", "2001:db8::/32"]
