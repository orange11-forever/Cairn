"""Private native model configuration; plaintext never crosses the WebView boundary."""

import ctypes
import json
import os
import tempfile
from ctypes import wintypes
from pathlib import Path
from typing import Literal

from cairn_api.settings import AnswerModelSettings
from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)

MODEL_FILE = "model-settings.dpapi"


class ModelSettingsError(RuntimeError):
    pass


class ModelConnection(BaseModel):
    model_config = ConfigDict(
        extra="forbid", populate_by_name=True, str_strip_whitespace=True, hide_input_in_errors=True
    )
    base_url: AnyHttpUrl = Field(alias="baseUrl")
    model: str = Field(min_length=1, max_length=200)
    api_key: SecretStr = Field(alias="apiKey", max_length=4096)
    protocol: Literal["openai-compatible", "openai-responses", "anthropic", "gemini"]

    @field_validator("api_key", mode="before")
    @classmethod
    def key_has_no_controls(cls, value):
        if isinstance(value, str) and any(character in value for character in "\r\n\x00"):
            raise ValueError("API Key cannot contain control characters")
        return value

    @model_validator(mode="after")
    def valid_connection(self):
        AnswerModelSettings(
            id="desktop",
            name="Desktop",
            model=self.model,
            protocol=self.protocol,
            base_url=self.base_url,
            api_key=self.api_key,
        )
        return self


class EmbeddingConnection(ModelConnection):
    protocol: Literal["openai-compatible"] = "openai-compatible"
    dimensions: Literal[1024] = 1024


class DesktopModels(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    version: Literal[1] = 1
    answer: ModelConnection | None = None
    embedding: EmbeddingConnection | None = None


def _crypt(data: bytes, *, decrypt: bool) -> bytes:
    if os.name != "nt":
        raise ModelSettingsError("模型凭据加密仅支持当前Windows用户。")

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    operation = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    operation.argtypes = [
        ctypes.POINTER(Blob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(Blob),
    ]
    operation.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ModelSettingsError(
            "模型配置无法解密，请重新配置或明确清除。"
            if decrypt
            else "模型配置加密失败，原配置未修改。"
        )
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(target.data)


def protect_bytes(value: bytes) -> bytes:
    return _crypt(value, decrypt=False)


def unprotect_bytes(value: bytes) -> bytes:
    return _crypt(value, decrypt=True)


def _validation_error(error: ValidationError) -> ModelSettingsError:
    allowed = {
        "answer",
        "embedding",
        "baseUrl",
        "base_url",
        "model",
        "apiKey",
        "api_key",
        "protocol",
        "dimensions",
    }
    fields = sorted(
        {
            ".".join(str(part) for part in item["loc"] if part in allowed) or "connection"
            for item in error.errors(include_input=False, include_url=False)
        }
    )
    return ModelSettingsError(
        "模型配置字段无效："
        + ", ".join(fields)
        + "。请检查协议、服务地址、模型及非空API Key；地址不能含用户名、密码、查询参数或片段。"
    )


def load_models(directory: Path) -> DesktopModels:
    path = directory / MODEL_FILE
    if not path.exists():
        return DesktopModels()
    try:
        if path.stat().st_size > 32_768:
            raise ModelSettingsError("模型配置文件过大，请明确清除后重新配置。")
        return DesktopModels.model_validate_json(unprotect_bytes(path.read_bytes()))
    except (ValidationError, OSError, ValueError):
        raise ModelSettingsError("模型配置损坏或无法读取，请重新配置或明确清除。") from None


def prepare_model_update(directory: Path, payload: object) -> DesktopModels:
    if not isinstance(payload, dict):
        raise ModelSettingsError("模型配置必须是JSON对象。")
    if payload == {"clearAll": True} and type(payload.get("clearAll")) is bool:
        return DesktopModels()
    if set(payload) != {"answer", "embedding"}:
        raise ModelSettingsError("模型配置必须分别提供answer与embedding，null表示明确清除该项。")
    previous = load_models(directory)
    values = {}
    for name in ("answer", "embedding"):
        value = payload[name]
        if isinstance(value, dict):
            value = dict(value)
            old = getattr(previous, name)
            if value.get("apiKey") == "" and old is not None:
                value["apiKey"] = old.api_key.get_secret_value()
        values[name] = value
    try:
        return DesktopModels.model_validate(values)
    except ValidationError as error:
        raise _validation_error(error) from None


def save_models(directory: Path, models: DesktopModels) -> None:
    values = {"version": 1}
    for name in ("answer", "embedding"):
        connection = getattr(models, name)
        values[name] = (
            None
            if connection is None
            else {
                **connection.model_dump(mode="json", by_alias=True),
                "apiKey": connection.api_key.get_secret_value(),
            }
        )
    encrypted = protect_bytes(json.dumps(values, ensure_ascii=False).encode("utf-8"))
    if len(encrypted) > 32_768:
        raise ModelSettingsError(
            "模型配置加密后超过保存上限，原配置未修改；请缩短服务地址或API Key。"
        )
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=directory, prefix=".model-settings-", delete=False
        ) as output:
            temporary = Path(output.name)
            output.write(encrypted)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, directory / MODEL_FILE)
    except OSError:
        raise ModelSettingsError("模型配置保存失败，原配置未修改。") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def public_status(models: DesktopModels) -> dict:
    result = {"corrupt": False, "indexingPaused": models.embedding is None}
    for name in ("answer", "embedding"):
        connection = getattr(models, name)
        result[name] = (
            None
            if connection is None
            else {
                key: value
                for key, value in connection.model_dump(mode="json", by_alias=True).items()
                if key != "apiKey"
            }
            | {"hasKey": bool(connection.api_key.get_secret_value())}
        )
    return result


def model_status(directory: Path) -> dict:
    try:
        return public_status(load_models(directory))
    except ModelSettingsError:
        return {"corrupt": True, "answer": None, "embedding": None, "indexingPaused": True}
