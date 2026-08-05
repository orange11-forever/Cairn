import pytest
from cairn_api.settings import Settings
from pydantic import ValidationError


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
        Settings(
            environment="production",
            app_url="https://cairn.example",
            session_cookie_secure=True,
            csrf_secret=csrf_secret,
            _env_file=None,  # pyright: ignore[reportCallIssue]
        )


def test_production_requires_secure_session_cookie() -> None:
    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            app_url="https://cairn.example",
            session_cookie_secure=False,
            csrf_secret="production-only-csrf-secret-with-at-least-32-bytes",
            _env_file=None,  # pyright: ignore[reportCallIssue]
        )


def test_production_requires_app_url() -> None:
    with pytest.raises(ValidationError, match="APP_URL"):
        Settings(
            environment="production",
            session_cookie_secure=True,
            csrf_secret="production-only-csrf-secret-with-at-least-32-bytes",
            _env_file=None,  # pyright: ignore[reportCallIssue]
        )


def test_production_accepts_secure_cookie_and_non_example_secret() -> None:
    settings = Settings(
        environment="production",
        app_url="https://cairn.example",
        session_cookie_secure=True,
        csrf_secret="production-only-csrf-secret-with-at-least-32-bytes",
        auth_rate_limit_secret="production-only-rate-limit-secret-with-at-least-32-bytes",
        _env_file=None,  # pyright: ignore[reportCallIssue]
    )

    assert settings.session_cookie_secure is True


@pytest.mark.parametrize("app_url", ["http://cairn.example", "http://localhost:8080"])
def test_production_rejects_http_app_url(app_url: str) -> None:
    with pytest.raises(ValidationError, match="HTTPS"):
        Settings(
            environment="production",
            app_url=app_url,
            session_cookie_secure=True,
            csrf_secret="production-only-csrf-secret-with-at-least-32-bytes",
            auth_rate_limit_secret="production-only-rate-limit-secret-with-at-least-32-bytes",
            _env_file=None,  # pyright: ignore[reportCallIssue]
        )


def test_production_rejects_http_cors_origin() -> None:
    with pytest.raises(ValidationError, match="HTTPS"):
        Settings(
            environment="production",
            app_url="https://cairn.example",
            cors_origins="http://frontend.example",
            session_cookie_secure=True,
            csrf_secret="production-only-csrf-secret-with-at-least-32-bytes",
            auth_rate_limit_secret="production-only-rate-limit-secret-with-at-least-32-bytes",
            _env_file=None,  # pyright: ignore[reportCallIssue]
        )


@pytest.mark.parametrize("secret", ["", "short", "local-development-auth-rate-limit-secret-change-before-deploying-32-bytes"])
def test_production_rejects_missing_short_or_example_rate_limit_secret(secret: str) -> None:
    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            app_url="https://cairn.example",
            session_cookie_secure=True,
            csrf_secret="production-only-csrf-secret-with-at-least-32-bytes",
            auth_rate_limit_secret=secret,
            _env_file=None,  # pyright: ignore[reportCallIssue]
        )


def test_settings_rejects_invalid_trusted_proxy_cidrs() -> None:
    with pytest.raises(ValidationError, match="CIDR"):
        Settings(trusted_proxy_cidrs="10.0.0.0/not-cidr", _env_file=None)  # pyright: ignore[reportCallIssue]


def test_production_accepts_https_values_and_normalizes_origins() -> None:
    settings = Settings(
        environment="production",
        app_url="https://cairn.example/",
        cors_origins="https://frontend.example/",
        session_cookie_secure=True,
        csrf_secret="production-only-csrf-secret-with-at-least-32-bytes",
        auth_rate_limit_secret="production-only-rate-limit-secret-with-at-least-32-bytes",
        trusted_proxy_cidrs="10.0.0.0/8, 2001:db8::/32",
        _env_file=None,  # pyright: ignore[reportCallIssue]
    )
    assert str(settings.app_url) == "https://cairn.example/"
    assert settings.cors_origins == ["https://frontend.example"]
    assert [str(network) for network in settings.trusted_proxy_cidrs] == ["10.0.0.0/8", "2001:db8::/32"]
