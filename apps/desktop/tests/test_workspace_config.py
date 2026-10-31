import json
from pathlib import Path

import pytest


def test_desktop_uses_only_publisher_client_id_not_inherited_oauth_secrets(tmp_path, monkeypatch):
    from cairn_desktop.workspace import load_workspace

    bundle, data = tmp_path / "bundle", tmp_path / "data"
    bundle.mkdir()
    data.mkdir()
    monkeypatch.setenv("CAIRN_OAUTH_GITHUB_CLIENT_ID", "unrelated-server-app")
    monkeypatch.setenv("CAIRN_OAUTH_GITHUB_CLIENT_SECRET", "must-not-use")
    (bundle / "github-app.json").write_text(json.dumps({"clientId": "cairn-public-id"}))
    workspace = load_workspace(bundle, data)
    assert workspace.client_id == "cairn-public-id"
    assert workspace.git == bundle / "git/cmd/git.exe"
    (bundle / "github-app.json").write_text('{"clientId": null}')
    assert load_workspace(bundle, data).github is None


def test_desktop_rejects_secret_in_publisher_configuration(tmp_path: Path):
    from cairn_desktop.workspace import load_workspace

    (tmp_path / "github-app.json").write_text('{"clientId":"app","clientSecret":"never-bundle"}')
    with pytest.raises(ValueError, match="GitHub"):
        load_workspace(tmp_path, tmp_path)


def test_dpapi_failure_is_reported_as_workspace_storage_failure(tmp_path, monkeypatch):
    from cairn_api.errors import ApiProblem
    from cairn_desktop.models import ModelSettingsError
    from cairn_desktop.workspace import load_workspace

    (tmp_path / "workspace-settings.dpapi").write_bytes(b"unreadable")

    def fail(_):
        raise ModelSettingsError("模型凭据无法解密")

    monkeypatch.setattr("cairn_desktop.workspace.unprotect_bytes", fail)
    with pytest.raises(ApiProblem) as error:
        load_workspace(tmp_path, tmp_path)
    assert error.value.code == "workspace_storage_failed"
    assert "仓库配置" in error.value.message
    assert "模型" not in error.value.message
