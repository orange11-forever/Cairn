from ipaddress import IPv4Network, IPv6Network, ip_address
from typing import Annotated, Literal, cast

from pydantic import AnyHttpUrl, Field, SecretStr, TypeAdapter, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from cairn_api.client_ip import parse_trusted_proxy_cidrs


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="",
        extra="ignore",
        populate_by_name=True,
    )

    environment: Literal["development", "test", "production"] = Field(
        default="development",
        validation_alias="CAIRN_ENVIRONMENT",
    )
    database_url: str = Field(
        default="postgresql+psycopg://cairn:cairn-local-only@127.0.0.1:5432/cairn",
        validation_alias="DATABASE_URL",
    )
    object_store_endpoint_url: AnyHttpUrl = Field(
        default=AnyHttpUrl("http://127.0.0.1:9000"),
        validation_alias="CAIRN_OBJECT_STORE_ENDPOINT_URL",
    )
    object_store_public_endpoint_url: AnyHttpUrl = Field(
        default=AnyHttpUrl("http://127.0.0.1:9000"),
        validation_alias="CAIRN_OBJECT_STORE_PUBLIC_ENDPOINT_URL",
    )
    embedding_base_url: AnyHttpUrl = Field(
        default=AnyHttpUrl("http://127.0.0.1:58081/v1"),
        validation_alias="EMBEDDING_BASE_URL",
    )
    object_store_region: str = Field(
        default="us-east-1",
        validation_alias="CAIRN_OBJECT_STORE_REGION",
    )
    object_store_bucket: str = Field(
        default="cairn",
        validation_alias="CAIRN_OBJECT_STORE_BUCKET",
    )
    object_store_access_key: SecretStr = Field(
        default=SecretStr("cairn-local"),
        validation_alias="CAIRN_OBJECT_STORE_ACCESS_KEY",
    )
    object_store_secret_key: SecretStr = Field(
        default=SecretStr("cairn-local-only-change-before-deploying"),
        validation_alias="CAIRN_OBJECT_STORE_SECRET_KEY",
    )
    object_store_path_style: bool = Field(
        default=True,
        validation_alias="CAIRN_OBJECT_STORE_PATH_STYLE",
    )
    upload_session_ttl_seconds: int = Field(
        default=900,
        gt=0,
        validation_alias="CAIRN_UPLOAD_SESSION_TTL_SECONDS",
    )
    download_url_ttl_seconds: int = Field(
        default=300,
        gt=0,
        validation_alias="CAIRN_DOWNLOAD_URL_TTL_SECONDS",
    )
    embedding_provider_key: str = Field(
        default="local-fake",
        validation_alias="EMBEDDING_PROVIDER",
    )
    embedding_api_key: SecretStr = Field(
        default=SecretStr("local-fake-embedding-key"),
        validation_alias="EMBEDDING_API_KEY",
    )
    embedding_model: str = Field(
        default="text-embedding-v4",
        validation_alias="EMBEDDING_MODEL",
    )
    embedding_dimensions: int = Field(
        default=1024,
        validation_alias="EMBEDDING_DIM",
    )
    embedding_batch_size: int = Field(
        default=10,
        ge=1,
        le=10,
        validation_alias="EMBEDDING_BATCH_SIZE",
    )
    embedding_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        validation_alias="EMBEDDING_TIMEOUT_SECONDS",
    )
    search_user_limit_per_minute: int = Field(
        default=30,
        ge=1,
        validation_alias="CAIRN_SEARCH_USER_LIMIT_PER_MINUTE",
    )
    search_org_limit_per_minute: int = Field(
        default=300,
        ge=0,
        validation_alias="CAIRN_SEARCH_ORG_LIMIT_PER_MINUTE",
    )
    search_audit_secret: SecretStr = Field(
        default=SecretStr(
            "local-development-search-audit-secret-change-before-deploying-32-bytes"
        ),
        validation_alias="CAIRN_SEARCH_AUDIT_SECRET",
    )
    bind_host: str = Field(default="127.0.0.1", validation_alias="CAIRN_BIND_HOST")
    http_port: int = Field(default=8080, ge=1, le=65535, validation_alias="CAIRN_HTTP_PORT")
    app_url: AnyHttpUrl | None = Field(default=None, validation_alias="APP_URL")
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=list,
        validation_alias="CORS_ORIGINS",
    )
    log_level: Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"] = Field(
        default="INFO",
        validation_alias="LOG_LEVEL",
    )
    session_cookie_name: str = Field(
        default="cairn_session",
        min_length=1,
        validation_alias="CAIRN_SESSION_COOKIE_NAME",
    )
    session_cookie_secure: bool = Field(
        default=False,
        validation_alias="CAIRN_SESSION_COOKIE_SECURE",
    )
    session_ttl_seconds: int = Field(
        default=604800,
        gt=0,
        validation_alias="CAIRN_SESSION_TTL_SECONDS",
    )
    csrf_secret: str = Field(
        default="local-development-secret-change-before-deploying-32-bytes",
        validation_alias="CAIRN_CSRF_SECRET",
    )
    auth_rate_limit_secret: str = Field(
        default="local-development-auth-rate-limit-secret-change-before-deploying-32-bytes",
        validation_alias="CAIRN_AUTH_RATE_LIMIT_SECRET",
    )
    trusted_proxy_cidrs: Annotated[tuple[IPv4Network | IPv6Network, ...], NoDecode] = Field(
        default=(),
        validation_alias="CAIRN_TRUSTED_PROXY_CIDRS",
    )

    @model_validator(mode="after")
    def validate_production_session_security(self) -> "Settings":
        if self.environment != "production":
            return self
        if self.app_url is None:
            raise ValueError("production requires APP_URL")
        if not self.session_cookie_secure:
            raise ValueError("production requires secure session cookies")
        if len(self.csrf_secret.encode("utf-8")) < 32:
            raise ValueError("production requires a CSRF secret of at least 32 bytes")
        if self.csrf_secret == "local-development-secret-change-before-deploying-32-bytes":
            raise ValueError("production cannot use the example CSRF secret")
        if self.app_url.scheme != "https":
            raise ValueError("production requires HTTPS APP_URL")
        if any(not origin.lower().startswith("https://") for origin in self.cors_origins):
            raise ValueError("production requires HTTPS CORS origins")
        if self.object_store_public_endpoint_url.scheme != "https":
            raise ValueError("production requires HTTPS public object-store URL")
        embedding_host = (self.embedding_base_url.host or "").removeprefix("[").removesuffix("]")
        embedding_is_loopback = embedding_host.lower() == "localhost"
        if not embedding_is_loopback:
            try:
                embedding_is_loopback = ip_address(embedding_host).is_loopback
            except ValueError:
                embedding_is_loopback = False
        if self.embedding_base_url.scheme != "https" and not embedding_is_loopback:
            raise ValueError("production Embedding URL requires HTTPS or a loopback-only host")
        if len(self.auth_rate_limit_secret.encode("utf-8")) < 32:
            raise ValueError("production requires an auth rate-limit secret of at least 32 bytes")
        if self.auth_rate_limit_secret in {
            "local-development-auth-rate-limit-secret-change-before-deploying-32-bytes",
            "local-development-secret-change-before-deploying-32-bytes",
        }:
            raise ValueError("production cannot use the example auth rate-limit secret")
        if self.auth_rate_limit_secret == self.csrf_secret:
            raise ValueError("production auth rate-limit secret must differ from the CSRF secret")
        object_store_access_key = self.object_store_access_key.get_secret_value().strip()
        object_store_secret_key = self.object_store_secret_key.get_secret_value().strip()
        search_audit_secret = self.search_audit_secret.get_secret_value().strip()
        if not object_store_access_key:
            raise ValueError("production object-store access key cannot be blank")
        if not object_store_secret_key:
            raise ValueError("production object-store secret key cannot be blank")
        if object_store_access_key == "cairn-local":
            raise ValueError("production cannot use the example object-store access key")
        if object_store_secret_key == "cairn-local-only-change-before-deploying":
            raise ValueError("production cannot use the example object-store secret key")
        if not self.embedding_api_key.get_secret_value().strip():
            raise ValueError("production requires a nonblank Embedding API key")
        if len(search_audit_secret.encode("utf-8")) < 32:
            raise ValueError("production search audit secret must be at least 32 bytes")
        if search_audit_secret == (
            "local-development-search-audit-secret-change-before-deploying-32-bytes"
        ):
            raise ValueError("production cannot use the example search audit secret")
        if self.search_org_limit_per_minute < 1:
            raise ValueError("production organization search rate limit must be at least 1")
        return self

    @field_validator(
        "object_store_endpoint_url",
        "object_store_public_endpoint_url",
        "embedding_base_url",
    )
    @classmethod
    def reject_url_credentials(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if value.username is not None or value.password is not None:
            raise ValueError("service URLs cannot contain credentials")
        return value

    @field_validator(
        "object_store_region",
        "object_store_bucket",
        "embedding_provider_key",
        "embedding_model",
    )
    @classmethod
    def reject_blank_knowledge_identifiers(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("knowledge setting cannot be blank")
        return normalized

    @field_validator("embedding_dimensions")
    @classmethod
    def require_stage_3a_embedding_dimensions(cls, value: int) -> int:
        if value != 1024:
            raise ValueError("Stage 3A requires exactly 1024 Embedding dimensions")
        return value

    @field_validator("app_url")
    @classmethod
    def require_app_origin(cls, value: AnyHttpUrl | None) -> AnyHttpUrl | None:
        if value is None:
            return None
        if value.username is not None or value.password is not None:
            raise ValueError("APP_URL cannot contain credentials")
        if value.path not in (None, "", "/") or value.query is not None or value.fragment is not None:
            raise ValueError("APP_URL must be an origin without path, query, or fragment")
        return value

    @field_validator("database_url")
    @classmethod
    def require_postgresql_psycopg(cls, value: str) -> str:
        if not value.startswith("postgresql+psycopg://"):
            raise ValueError("DATABASE_URL must use the postgresql+psycopg driver")
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> list[str]:
        if value is None:
            origins: list[str] = []
        elif isinstance(value, str):
            origins = [origin.strip() for origin in value.split(",") if origin.strip()]
        elif isinstance(value, list):
            raw_origins = cast(list[object], value)
            if not all(isinstance(origin, str) for origin in raw_origins):
                raise ValueError("CORS_ORIGINS must be a comma-separated string or string list")
            string_origins = cast(list[str], raw_origins)
            origins = [origin.strip() for origin in string_origins if origin.strip()]
        else:
            raise ValueError("CORS_ORIGINS must be a comma-separated string or string list")

        origin_adapter = TypeAdapter(AnyHttpUrl)
        normalized_origins: list[str] = []
        for origin in origins:
            if "*" in origin:
                raise ValueError("CORS_ORIGINS cannot contain wildcard hosts")
            parsed = origin_adapter.validate_python(origin)
            if parsed.username is not None or parsed.password is not None:
                raise ValueError("CORS_ORIGINS cannot contain credentials")
            if parsed.path not in (None, "", "/") or parsed.query is not None or parsed.fragment is not None:
                raise ValueError("CORS_ORIGINS entries must be origins without path, query, or fragment")
            normalized_origins.append(str(parsed).rstrip("/"))
        return normalized_origins

    @field_validator("trusted_proxy_cidrs", mode="before")
    @classmethod
    def parse_trusted_proxy_networks(
        cls, value: object
    ) -> tuple[IPv4Network | IPv6Network, ...]:
        if value is None or value == "":
            return ()
        if isinstance(value, str):
            raw: str | list[str] = value
        elif isinstance(value, list):
            raw = cast(list[str], value)
        elif isinstance(value, tuple) and all(
            isinstance(item, (IPv4Network, IPv6Network))
            for item in cast(tuple[object, ...], value)
        ):
            return cast(tuple[IPv4Network | IPv6Network, ...], value)
        elif isinstance(value, tuple):
            raw = list(cast(tuple[str, ...], value))
        else:
            raise ValueError("CAIRN_TRUSTED_PROXY_CIDRS must be a comma-separated string or string list")
        try:
            return parse_trusted_proxy_cidrs(raw)
        except ValueError as exc:
            raise ValueError(f"invalid trusted proxy CIDR: {exc}") from exc
