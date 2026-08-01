from typing import Annotated, Literal, cast

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="",
        extra="ignore",
        populate_by_name=True,
    )

    bind_host: str = Field(default="127.0.0.1", validation_alias="CAIRN_BIND_HOST")
    http_port: int = Field(default=8080, ge=1, le=65535, validation_alias="CAIRN_HTTP_PORT")
    app_url: str | None = Field(default=None, validation_alias="APP_URL")
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=list,
        validation_alias="CORS_ORIGINS",
    )
    log_level: Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"] = Field(
        default="INFO",
        validation_alias="LOG_LEVEL",
    )

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

        if "*" in origins:
            raise ValueError("CORS_ORIGINS cannot contain wildcard '*' when cookies are used")
        return origins
