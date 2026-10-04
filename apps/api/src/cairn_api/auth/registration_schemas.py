import re

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class RegistrationRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    email: EmailStr = Field(max_length=320)
    password: str = Field(min_length=12, max_length=128)
    display_name: str | None = Field(default=None, alias="displayName", max_length=120)


class RegistrationResendRequest(BaseModel):
    email: EmailStr = Field(max_length=320)
    password: str = Field(min_length=12, max_length=128)
    registration_receipt: str = Field(
        alias="registrationReceipt",
        min_length=1,
        max_length=128,
        json_schema_extra={"pattern": r"^[A-Za-z0-9_-]+$(?![\s\S])"},
    )

    @field_validator("registration_receipt")
    @classmethod
    def ascii_receipt(cls, value: str) -> str:
        if re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
            raise ValueError("invalid registration receipt")
        return value


class RegistrationVerifyRequest(BaseModel):
    token: str = Field(
        min_length=1, max_length=128, json_schema_extra={"pattern": r"^[A-Za-z0-9_-]+$(?![\s\S])"}
    )
    password: str = Field(min_length=1, max_length=128)

    @field_validator("token")
    @classmethod
    def ascii_token(cls, value: str) -> str:
        if re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
            raise ValueError("invalid verification token")
        return value


class RegistrationAvailability(BaseModel):
    enabled: bool


class RegistrationAccepted(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True, json_schema_serialization_defaults_required=True
    )
    message: str = "如可为此邮箱创建账号，请查收验证邮件；已有账号请直接登录。"
    registration_receipt: str = Field(serialization_alias="registrationReceipt")
    resend_after_seconds: int = Field(default=60, serialization_alias="resendAfterSeconds")


class RegistrationVerified(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)
    message: str = "邮箱验证成功，请使用邮箱和密码登录。"
