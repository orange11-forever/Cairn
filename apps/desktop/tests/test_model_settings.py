import json
from pathlib import Path

import pytest
from cairn_desktop.models import (
    ModelSettingsError,
    load_models,
    model_status,
    prepare_model_update,
    save_models,
)


def configure_models(directory, payload):
    save_models(directory, prepare_model_update(directory, payload))


def payload(*, key="test-secret-not-user", model="model", address="http://localhost:11434/v1"):
    return {
        "answerModels": [
            {
                "id": "default",
                "name": "默认模型",
                "protocol": "openai-responses",
                "baseUrl": address,
                "model": model,
                "apiKey": key,
            }
        ],
        "defaultModelId": "default",
        "embedding": None,
    }


@pytest.fixture
def cryptography(monkeypatch):
    from cairn_desktop import models

    monkeypatch.setattr(models, "protect_bytes", lambda value: b"sealed:" + value[::-1])

    def open_bytes(value):
        if not value.startswith(b"sealed:"):
            raise ModelSettingsError("模型配置无法解密，请重新配置或明确清除。")
        return value[7:][::-1]

    monkeypatch.setattr(models, "unprotect_bytes", open_bytes)


def test_encrypted_config_roundtrip_safe_status_and_empty_key_retention(
    tmp_path: Path, cryptography
):
    configure_models(tmp_path, payload())
    stored = (tmp_path / "model-settings.dpapi").read_bytes()
    assert b"test-secret-not-user" not in stored
    result = model_status(tmp_path)
    assert (
        result["answerModels"][0]["hasKey"] is True
        and result["answerModels"][0]["model"] == "model"
    )
    assert "test-secret-not-user" not in json.dumps(result)
    configure_models(tmp_path, payload(key="", model="new-model"))
    assert (
        load_models(tmp_path).answer_models[0].api_key.get_secret_value() == "test-secret-not-user"
    )
    assert load_models(tmp_path).answer_models[0].model == "new-model"
    configure_models(tmp_path, {"answerModels": [], "defaultModelId": None, "embedding": None})
    assert model_status(tmp_path)["answerModels"] == []


@pytest.mark.parametrize(
    "change",
    [
        {"baseUrl": "http://username:test-secret-not-user@localhost/v1"},
        {"baseUrl": "https://example.test/v1?key=test-secret-not-user"},
        {"baseUrl": "https://example.test/v1#test-secret-not-user"},
        {"model": ""},
        {"protocol": "script"},
        {"apiKey": "test-secret-not-user\n"},
    ],
)
def test_field_errors_never_include_secret_and_leave_previous_ciphertext(
    tmp_path: Path, cryptography, change
):
    configure_models(tmp_path, payload())
    before = (tmp_path / "model-settings.dpapi").read_bytes()
    value = payload()
    value["answerModels"][0].update(change)
    with pytest.raises(ModelSettingsError) as error:
        configure_models(tmp_path, value)
    assert "test-secret-not-user" not in str(error.value)
    assert (tmp_path / "model-settings.dpapi").read_bytes() == before


def test_blank_first_key_and_non_1024_embedding_fields_are_rejected(tmp_path: Path, cryptography):
    with pytest.raises(ModelSettingsError):
        configure_models(tmp_path, payload(key=""))
    value = payload()
    value["embedding"] = {
        "baseUrl": "http://localhost/v1",
        "model": "index",
        "apiKey": "explicit-placeholder",
        "dimensions": 768,
    }
    with pytest.raises(ModelSettingsError):
        configure_models(tmp_path, value)


def test_corruption_is_visible_and_explicit_clear_recovers_without_touching_data(
    tmp_path: Path, cryptography
):
    secret = tmp_path / "settings.json"
    secret.write_text("database-settings-kept")
    (tmp_path / "model-settings.dpapi").write_bytes(b"damaged")
    assert model_status(tmp_path)["corrupt"] is True
    with pytest.raises(ModelSettingsError):
        load_models(tmp_path)
    with pytest.raises(ModelSettingsError):
        configure_models(tmp_path, payload())
    configure_models(tmp_path, {"clearAll": True})
    assert model_status(tmp_path) == {
        "corrupt": False,
        "answerModels": [],
        "defaultModelId": None,
        "embedding": None,
        "indexingPaused": True,
    }
    assert secret.read_text() == "database-settings-kept"


def test_atomic_save_failure_preserves_existing_file(tmp_path: Path, cryptography, monkeypatch):
    from cairn_desktop import models

    configure_models(tmp_path, payload())
    before = (tmp_path / "model-settings.dpapi").read_bytes()

    def fail(*args):
        raise OSError("injected atomic replace failure")

    monkeypatch.setattr(models.os, "replace", fail)
    with pytest.raises(ModelSettingsError):
        configure_models(tmp_path, payload(key="replacement"))
    assert (tmp_path / "model-settings.dpapi").read_bytes() == before
    assert not list(tmp_path.glob(".model-settings-*"))


def test_oversized_ciphertext_is_rejected_before_replacing_previous_configuration(
    tmp_path: Path, cryptography, monkeypatch
):
    from cairn_desktop import models

    configure_models(tmp_path, payload())
    before = (tmp_path / "model-settings.dpapi").read_bytes()
    monkeypatch.setattr(
        models, "protect_bytes", lambda value: b"x" * (models.MAX_MODEL_FILE_BYTES + 1)
    )
    with pytest.raises(ModelSettingsError, match="超过保存上限"):
        configure_models(tmp_path, payload(model="new-model"))
    assert (tmp_path / "model-settings.dpapi").read_bytes() == before


def test_published_binding_rejection_happens_before_old_credentials_are_replaced(
    tmp_path: Path, cryptography, monkeypatch
):
    from cairn_desktop import runtime

    configure_models(tmp_path, payload())
    before = (tmp_path / "model-settings.dpapi").read_bytes()

    def reject(*args):
        raise ModelSettingsError("已存在索引，不能修改地址或model")

    monkeypatch.setattr(runtime, "check_model_binding", reject)
    value = payload(key="replacement-secret")
    value["embedding"] = {
        "baseUrl": "http://localhost/v1",
        "model": "different-model",
        "apiKey": "replacement-index-secret",
    }
    with pytest.raises(ModelSettingsError, match="已存在索引"):
        runtime.configure_model_settings(tmp_path, tmp_path, value, None)
    assert (tmp_path / "model-settings.dpapi").read_bytes() == before


def test_runtime_uses_only_explicit_settings_and_no_repository_or_process_keys(
    tmp_path: Path, monkeypatch
):
    from cairn_api.knowledge.search_service import EmbeddingUnavailable
    from cairn_desktop.models import DesktopModels
    from cairn_desktop.runtime import PausedEmbeddingClient, build_desktop_settings

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "ANSWER_MODEL=should-not-load\nANSWER_API_KEY=private-env-secret\n"
    )
    monkeypatch.setenv("ANSWER_API_KEY", "process-secret")
    monkeypatch.setenv("ANSWER_MODEL", "process-model")
    values = {key: "a" * 64 for key in ("csrfSecret", "rateLimitSecret", "searchSecret")}
    settings = build_desktop_settings(
        values,
        "http://127.0.0.1:8000",
        "postgresql+psycopg://test",
        DesktopModels(),
        "profile-identity",
        "bound-model",
    )
    assert (
        settings.answer_model is None
        and settings.answer_api_key is None
        and settings.answer_models == []
    )
    assert settings.embedding_model == "bound-model" and settings.embedding_dimensions == 1024
    with pytest.raises(EmbeddingUnavailable):
        PausedEmbeddingClient("profile-identity", "bound-model").embed_query("query")


def test_restored_source_jobs_cannot_inherit_server_environment_credentials(monkeypatch):
    from uuid import uuid4

    import cairn_worker.feishu_sync as sync
    from cairn_api.knowledge.models import JobKind
    from cairn_desktop.runtime import build_desktop_handlers
    from cairn_worker import runner
    from cairn_worker.feishu_credentials import FeishuCredentialFailure, FeishuCredentialResolver

    org = uuid4()
    monkeypatch.setenv(
        "CAIRN_FEISHU_CREDENTIALS_JSON",
        json.dumps(
            {str(org): {"test": {"appId": "synthetic-app", "appSecret": "synthetic-server-secret"}}}
        ),
    )
    assert (
        FeishuCredentialResolver.from_environment()
        .resolve(org_id=org, credential_ref="test")
        .app_id
        == "synthetic-app"
    )
    monkeypatch.setattr(runner, "build_runtime_handlers", lambda **kwargs: {})
    monkeypatch.setattr(sync, "build_feishu_sync_handler", lambda **kwargs: kwargs["resolver"])
    resolver = build_desktop_handlers(None, None, None)[JobKind.SYNC_FEISHU_SOURCE]
    with pytest.raises(FeishuCredentialFailure) as error:
        resolver.resolve(org_id=org, credential_ref="test")
    assert error.value.code == "feishu_credentials_not_found"


def test_expected_cli_model_error_returns_nonzero_with_safe_actionable_stderr(
    tmp_path, monkeypatch, capsys, caplog
):
    import sys

    from cairn_desktop import runtime, windows

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "runtime",
            "serve",
            "--bundle",
            str(tmp_path / "bundle"),
            "--data",
            str(tmp_path / "data"),
        ],
    )
    monkeypatch.setattr(windows, "contain_process_tree", lambda: object())
    monkeypatch.setattr(
        runtime, "protect_directory", lambda directory: directory.mkdir(parents=True, exist_ok=True)
    )

    def invalid_model(_bundle, directory, _log):
        prepare_model_update(
            directory, payload(address="https://example.test/v1?key=test-secret-not-user")
        )

    monkeypatch.setattr(runtime, "serve", invalid_model)
    assert runtime.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "模型配置字段无效" in captured.err and "runtime.log" in captured.err
    assert "Traceback" not in captured.err and "test-secret-not-user" not in captured.err
    assert any(record.exc_info is not None for record in caplog.records)


def test_unexpected_cli_failure_is_logged_and_still_raises(tmp_path, monkeypatch):
    import sys

    from cairn_desktop import runtime, windows

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "runtime",
            "serve",
            "--bundle",
            str(tmp_path / "bundle"),
            "--data",
            str(tmp_path / "data"),
        ],
    )
    monkeypatch.setattr(windows, "contain_process_tree", lambda: object())
    monkeypatch.setattr(
        runtime, "protect_directory", lambda directory: directory.mkdir(parents=True, exist_ok=True)
    )

    def fail(*args):
        raise RuntimeError("unexpected programming failure")

    monkeypatch.setattr(runtime, "serve", fail)
    with pytest.raises(RuntimeError, match="unexpected programming failure"):
        runtime.main()
