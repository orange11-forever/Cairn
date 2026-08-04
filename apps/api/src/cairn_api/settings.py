from typing import Annotated, Literal, cast

from pydantic import AnyHttpUrl, Field, TypeAdapter, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


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
        return self

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
