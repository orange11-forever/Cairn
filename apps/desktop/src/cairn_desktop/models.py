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
MAX_MODEL_FILE_BYTES = 512 * 1024


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


class LegacyDesktopModels(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    version: Literal[1] = 1
    answer: ModelConnection | None = None
    embedding: EmbeddingConnection | None = None


class AnswerConnection(ModelConnection):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        return AnswerModelSettings.valid_model_text(value)


class DesktopModels(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, hide_input_in_errors=True)
    version: Literal[2] = 2
    answer_models: list[AnswerConnection] = Field(
        default_factory=list, alias="answerModels", max_length=20
    )
    default_model_id: str | None = Field(default=None, alias="defaultModelId")
    embedding: EmbeddingConnection | None = None

    @model_validator(mode="after")
    def valid_catalog(self):
        ids = [item.id for item in self.answer_models]
        if len(ids) != len(set(ids)):
            raise ValueError("answer model IDs must be unique")
        if (ids and self.default_model_id not in ids) or (
            not ids and self.default_model_id is not None
        ):
            raise ValueError("select an existing default answer model")
        return self


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
        "answerModels",
        "defaultModelId",
        "id",
        "name",
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
        + "。请检查名称、协议、服务地址、模型及非空API Key；模型标识不能重复，默认模型必须在目录中；地址不能含用户名、密码、查询参数或片段。"
    )


def load_models(directory: Path) -> DesktopModels:
    path = directory / MODEL_FILE
    if not path.exists():
        return DesktopModels()
    try:
        if path.stat().st_size > MAX_MODEL_FILE_BYTES:
            raise ModelSettingsError("模型配置文件过大，请明确清除后重新配置。")
        value = json.loads(unprotect_bytes(path.read_bytes()))
        if isinstance(value, dict) and value.get("version", 1) == 1:
            old = LegacyDesktopModels.model_validate(value)
            return DesktopModels(
                answer_models=[]
                if old.answer is None
                else [
                    AnswerConnection(
                        **old.answer.model_dump(), id="default", name=old.answer.model[:80]
                    )
                ],
                default_model_id="default" if old.answer else None,
                embedding=old.embedding,
            )
        return DesktopModels.model_validate(value)
    except (ValidationError, OSError, ValueError):
        raise ModelSettingsError("模型配置损坏或无法读取，请重新配置或明确清除。") from None


def prepare_model_update(directory: Path, payload: object) -> DesktopModels:
    if not isinstance(payload, dict):
        raise ModelSettingsError("模型配置必须是JSON对象。")
    if payload == {"clearAll": True} and type(payload.get("clearAll")) is bool:
        return DesktopModels()
    if set(payload) != {"answerModels", "defaultModelId", "embedding"}:
        raise ModelSettingsError("模型配置必须提供answerModels、defaultModelId与embedding。")
    previous = load_models(directory)
    values = dict(payload)

    def retain_key(value, old):
        if isinstance(value, dict):
            value = dict(value)
            if value.get("apiKey") == "" and old is not None:
                value["apiKey"] = old.api_key.get_secret_value()
        return value

    old_models = {model.id: model for model in previous.answer_models}
    if isinstance(values["answerModels"], list):
        values["answerModels"] = [
            retain_key(
                value,
                old_models.get(value.get("id"))
                if isinstance(value, dict) and isinstance(value.get("id"), str)
                else None,
            )
            for value in values["answerModels"]
        ]
    values["embedding"] = retain_key(values["embedding"], previous.embedding)
    try:
        return DesktopModels.model_validate(values)
    except ValidationError as error:
        raise _validation_error(error) from None


def save_models(directory: Path, models: DesktopModels) -> None:
    def private_connection(connection):
        return (
            None
            if connection is None
            else {
                **connection.model_dump(mode="json", by_alias=True),
                "apiKey": connection.api_key.get_secret_value(),
            }
        )

    values = {
        "version": 2,
        "answerModels": [private_connection(item) for item in models.answer_models],
        "defaultModelId": models.default_model_id,
        "embedding": private_connection(models.embedding),
    }
    encrypted = protect_bytes(json.dumps(values, ensure_ascii=False).encode("utf-8"))
    if len(encrypted) > MAX_MODEL_FILE_BYTES:
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
    def safe_connection(connection):
        return (
            None
            if connection is None
            else {
                key: value
                for key, value in connection.model_dump(mode="json", by_alias=True).items()
                if key != "apiKey"
            }
            | {"hasKey": bool(connection.api_key.get_secret_value())}
        )

    return {
        "corrupt": False,
        "indexingPaused": models.embedding is None,
        "answerModels": [safe_connection(item) for item in models.answer_models],
        "defaultModelId": models.default_model_id,
        "embedding": safe_connection(models.embedding),
    }


def model_status(directory: Path) -> dict:
    try:
        return public_status(load_models(directory))
    except ModelSettingsError:
        return {
            "corrupt": True,
            "answerModels": [],
            "defaultModelId": None,
            "embedding": None,
            "indexingPaused": True,
        }
