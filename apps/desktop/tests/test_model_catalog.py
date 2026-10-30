import json

import pytest
from cairn_desktop.models import (
    ModelSettingsError,
    load_models,
    model_status,
    prepare_model_update,
    save_models,
)
from cairn_desktop.runtime import build_desktop_settings

from apps.desktop.tests.test_model_settings import cryptography  # noqa: F401


def connection(identifier="first", key="test-first-secret", **overrides):
    return {
        "id": identifier,
        "name": identifier,
        "protocol": "openai-compatible",
        "baseUrl": "http://127.0.0.1:11434/v1",
        "model": identifier + "-model",
        "apiKey": key,
        **overrides,
    }


def catalog(*models, default="first", embedding=None):
    return {"answerModels": list(models), "defaultModelId": default, "embedding": embedding}


@pytest.mark.usefixtures("cryptography")
def test_legacy_encrypted_configuration_migrates_without_rewriting_or_losing_credentials(tmp_path):
    from cairn_desktop.models import protect_bytes

    original = connection()
    for field in ("id", "name"):
        original.pop(field)
    legacy = {"version": 1, "answer": original, "embedding": {**original, "dimensions": 1024}}
    path = tmp_path / "model-settings.dpapi"
    path.write_bytes(protect_bytes(json.dumps(legacy).encode()))
    before = path.read_bytes()
    loaded = load_models(tmp_path)
    assert loaded.version == 2
    assert loaded.default_model_id == "default"
    assert [(m.id, m.model, m.api_key.get_secret_value()) for m in loaded.answer_models] == [
        ("default", "first-model", "test-first-secret")
    ]
    assert loaded.embedding.api_key.get_secret_value() == "test-first-secret"
    assert path.read_bytes() == before
    save_models(tmp_path, loaded)
    assert load_models(tmp_path) == loaded


@pytest.mark.usefixtures("cryptography")
def test_two_models_keep_keys_by_id_and_default_reorders_runtime_without_aliasing(tmp_path):
    save_models(
        tmp_path,
        prepare_model_update(
            tmp_path,
            catalog(connection(), connection("second", "test-second-secret"), default="second"),
        ),
    )
    update = catalog(connection("second", "", model="second-revised"), connection(key=""))
    save_models(tmp_path, prepare_model_update(tmp_path, update))
    models = load_models(tmp_path)
    assert [(m.id, m.api_key.get_secret_value()) for m in models.answer_models] == [
        ("second", "test-second-secret"),
        ("first", "test-first-secret"),
    ]
    status = model_status(tmp_path)
    assert status["defaultModelId"] == "first"
    assert len(status["answerModels"]) == 2
    assert "test-first-secret" not in json.dumps(status) and "test-second-secret" not in json.dumps(
        status
    )
    assert b"test-first-secret" not in (tmp_path / "model-settings.dpapi").read_bytes()
    settings = build_desktop_settings(
        {key: "a" * 64 for key in ("csrfSecret", "rateLimitSecret", "searchSecret")},
        "http://127.0.0.1:8000",
        "postgresql+psycopg://test",
        models,
        "profile",
        "index",
    )
    assert settings.answer_model is None
    assert [m.id for m in settings.answer_models] == ["first", "second"]
    assert settings.answer_models[1].model == "second-revised"


@pytest.mark.parametrize(
    "value",
    [
        catalog(connection(), connection()),
        catalog(connection(), default="missing"),
        catalog(connection("second", ""), default="second"),
        catalog(connection(), default=None),
        catalog(default="first"),
    ],
)
@pytest.mark.usefixtures("cryptography")
def test_invalid_catalog_preserves_ciphertext(tmp_path, value):
    save_models(tmp_path, prepare_model_update(tmp_path, catalog(connection())))
    before = (tmp_path / "model-settings.dpapi").read_bytes()
    with pytest.raises(ModelSettingsError):
        save_models(tmp_path, prepare_model_update(tmp_path, value))
    assert (tmp_path / "model-settings.dpapi").read_bytes() == before


@pytest.mark.usefixtures("cryptography")
def test_deleting_one_model_does_not_reassign_its_identity_or_credentials(tmp_path):
    save_models(
        tmp_path,
        prepare_model_update(
            tmp_path, catalog(connection(), connection("second", "test-second-secret"))
        ),
    )
    save_models(
        tmp_path,
        prepare_model_update(tmp_path, catalog(connection("second", ""), default="second")),
    )
    assert [m.id for m in load_models(tmp_path).answer_models] == ["second"]
    with pytest.raises(ModelSettingsError):
        prepare_model_update(tmp_path, catalog(connection(key="")))
