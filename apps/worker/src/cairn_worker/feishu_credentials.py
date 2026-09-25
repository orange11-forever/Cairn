import json
import os
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, NoReturn, Self, cast
from uuid import UUID

from cairn_worker.feishu import FeishuDocumentClient

_ENVIRONMENT_KEY = "CAIRN_FEISHU_CREDENTIALS_JSON"
_MAXIMUM_JSON_BYTES = 1024 * 1024
_MAXIMUM_BINDINGS = 256
_MAXIMUM_CREDENTIAL_LENGTH = 4096
_ALIAS = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z", re.ASCII)

type CredentialFailureCode = Literal[
    "feishu_credentials_invalid",
    "feishu_credentials_not_found",
    "feishu_credentials_unexpected",
]

_SAFE_DETAILS: dict[CredentialFailureCode, str] = {
    "feishu_credentials_invalid": "Feishu credential configuration is invalid",
    "feishu_credentials_not_found": "Feishu credentials were not found",
    "feishu_credentials_unexpected": "Feishu credential resolution failed unexpectedly",
}


@dataclass(frozen=True)
class FeishuCredentials:
    app_id: str = field(repr=False)
    app_secret: str = field(repr=False)


class FeishuCredentialFailure(Exception):
    def __init__(self, code: CredentialFailureCode) -> None:
        self.code = code
        self.safe_detail = _SAFE_DETAILS[code]
        self.retryable = False
        super().__init__(self.code, self.safe_detail)


class _InvalidConfiguration(ValueError):
    pass


def _failure(code: CredentialFailureCode) -> FeishuCredentialFailure:
    return FeishuCredentialFailure(code)


def _reject_json_constant(_value: str) -> NoReturn:
    raise _InvalidConfiguration


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _InvalidConfiguration
        result[key] = value
    return result


def _validate_credential(value: object) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > _MAXIMUM_CREDENTIAL_LENGTH
        or not value.strip()
        or any(unicodedata.category(character) in {"Cc", "Cs"} for character in value)
    ):
        raise _InvalidConfiguration
    return value


def _load_registry(raw_json: str) -> dict[UUID, dict[str, FeishuCredentials]]:
    if not raw_json:
        raise _InvalidConfiguration
    try:
        encoded = raw_json.encode("utf-8")
    except UnicodeError:
        raise _InvalidConfiguration from None
    if len(encoded) > _MAXIMUM_JSON_BYTES:
        raise _InvalidConfiguration
    decoded = json.loads(
        raw_json,
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=_reject_json_constant,
    )
    if type(decoded) is not dict:
        raise _InvalidConfiguration

    registry: dict[UUID, dict[str, FeishuCredentials]] = {}
    binding_count = 0
    for organization_key, aliases_value in cast(dict[object, object], decoded).items():
        if type(organization_key) is not str or type(aliases_value) is not dict:
            raise _InvalidConfiguration
        try:
            organization_id = UUID(organization_key)
        except (AttributeError, ValueError):
            raise _InvalidConfiguration from None
        if str(organization_id) != organization_key:
            raise _InvalidConfiguration

        aliases: dict[str, FeishuCredentials] = {}
        for alias, credential_value in cast(dict[object, object], aliases_value).items():
            if (
                type(alias) is not str
                or _ALIAS.fullmatch(alias) is None
                or type(credential_value) is not dict
            ):
                raise _InvalidConfiguration
            credential = cast(dict[object, object], credential_value)
            if set(credential) != {"appId", "appSecret"}:
                raise _InvalidConfiguration
            binding_count += 1
            if binding_count > _MAXIMUM_BINDINGS:
                raise _InvalidConfiguration
            aliases[alias] = FeishuCredentials(
                app_id=_validate_credential(credential["appId"]),
                app_secret=_validate_credential(credential["appSecret"]),
            )
        registry[organization_id] = aliases
    return registry


class FeishuCredentialResolver:
    def __init__(self, raw_json: str | None = None) -> None:
        if raw_json is None:
            self._registry: dict[UUID, dict[str, FeishuCredentials]] = {}
            return
        if type(raw_json) is not str:
            raise _failure("feishu_credentials_invalid") from None
        try:
            self._registry = _load_registry(raw_json)
        except (_InvalidConfiguration, json.JSONDecodeError, RecursionError, UnicodeError):
            raise _failure("feishu_credentials_invalid") from None
        except Exception:  # noqa: BLE001 -- the public boundary redacts arbitrary parser errors
            raise _failure("feishu_credentials_unexpected") from None

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None) -> Self:
        source = os.environ if environment is None else environment
        try:
            raw_json = source.get(_ENVIRONMENT_KEY)
        except Exception:  # noqa: BLE001 -- environment adapters are outside this boundary
            raise _failure("feishu_credentials_unexpected") from None
        return cls(raw_json)

    def __repr__(self) -> str:
        binding_count = sum(len(aliases) for aliases in self._registry.values())
        return f"FeishuCredentialResolver(bindings={binding_count})"

    def resolve(self, *, org_id: UUID, credential_ref: str) -> FeishuCredentials:
        if (
            type(org_id) is not UUID
            or type(credential_ref) is not str
            or _ALIAS.fullmatch(credential_ref) is None
        ):
            raise _failure("feishu_credentials_not_found") from None
        credentials = self._registry.get(org_id, {}).get(credential_ref)
        if credentials is None:
            raise _failure("feishu_credentials_not_found") from None
        return credentials

    def create_client(self, *, org_id: UUID, credential_ref: str) -> FeishuDocumentClient:
        credentials = self.resolve(org_id=org_id, credential_ref=credential_ref)
        try:
            return FeishuDocumentClient(
                app_id=credentials.app_id,
                app_secret=credentials.app_secret,
            )
        except Exception:  # noqa: BLE001 -- constructor failures must not expose credentials
            raise _failure("feishu_credentials_unexpected") from None


__all__ = [
    "FeishuCredentialFailure",
    "FeishuCredentialResolver",
    "FeishuCredentials",
]
