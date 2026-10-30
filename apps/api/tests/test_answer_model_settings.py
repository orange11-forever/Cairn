import json

import pytest
from cairn_api.settings import Settings
from pydantic import ValidationError

PROFILE = {
    "id": "reasoning",
    "name": "推理模型",
    "model": "synthetic-reasoner",
    "protocol": "openai-responses",
    "base_url": "https://controlled.example/v1",
    "api_key": "synthetic-model-secret",
}


def test_model_profiles_load_from_environment_without_exposing_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANSWER_MODELS", json.dumps([PROFILE]))
    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]
    assert settings.answer_models[0].model == "synthetic-reasoner"
    assert settings.answer_models[0].api_key.get_secret_value() == "synthetic-model-secret"
    assert "synthetic-model-secret" not in repr(settings)


@pytest.mark.parametrize(
    "profiles",
    [
        [PROFILE, PROFILE],
        [{**PROFILE, "id": "../unlisted"}],
        [{**PROFILE, "api_key": " "}],
        [{**PROFILE, "model": " "}],
        [{**PROFILE, "base_url": "https://secret@controlled.example/v1"}],
        [{**PROFILE, "base_url": "https://controlled.example/v1?key=secret"}],
        [{**PROFILE, "protocol": "unsupported"}],
        [{**PROFILE, "name": "bad\x00name"}],
        [{**PROFILE, "api_key": "secret\nheader"}],
    ],
)
def test_invalid_model_catalog_fails_at_configuration_boundary(
    profiles: list[dict[str, str]],
) -> None:
    with pytest.raises(ValidationError):
        Settings(answer_models=profiles, _env_file=None)  # pyright: ignore[reportArgumentType, reportCallIssue]


def test_invalid_profile_error_does_not_print_the_api_key() -> None:
    with pytest.raises(ValidationError) as error:
        Settings(answer_models=[{**PROFILE, "id": "../invalid"}], _env_file=None)  # pyright: ignore[reportArgumentType, reportCallIssue]
    assert "synthetic-model-secret" not in str(error.value)


def test_legacy_default_id_is_retained_in_catalog_but_cannot_shadow_legacy_provider() -> None:
    settings = Settings(answer_models=[{**PROFILE, "id": "default"}], _env_file=None)  # pyright: ignore[reportArgumentType, reportCallIssue]
    assert settings.answer_models[0].id == "default"
    with pytest.raises(ValidationError):
        Settings(answer_models=[{**PROFILE, "id": "default"}], answer_model="legacy", answer_api_key="test-key", answer_base_url="http://localhost/v1", _env_file=None)  # pyright: ignore[reportArgumentType, reportCallIssue]
