"""Publisher-owned public OAuth configuration, isolated from server environment settings."""

from pathlib import Path

from cairn_api.workspace.local import DesktopWorkspace
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from cairn_desktop.models import ModelSettingsError, protect_bytes, unprotect_bytes


class GitHubApplication(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_id: str | None = Field(
        default=None, alias="clientId", pattern=r"^[A-Za-z0-9_.-]{1,160}$"
    )


def _protect(value: bytes) -> bytes:
    try:
        return protect_bytes(value)
    except ModelSettingsError:
        raise OSError("Cannot encrypt workspace settings") from None


def _unprotect(value: bytes) -> bytes:
    try:
        return unprotect_bytes(value)
    except ModelSettingsError:
        raise OSError("Cannot decrypt workspace settings") from None


def load_workspace(bundle: Path, data: Path) -> DesktopWorkspace:
    path = bundle / "github-app.json"
    try:
        configuration = (
            GitHubApplication.model_validate_json(path.read_bytes())
            if path.is_file()
            else GitHubApplication()
        )
    except (OSError, ValidationError):
        raise ValueError(
            "Cairn GitHub 授权应用配置无效，请修复安装包；不应在该文件填写凭据"
        ) from None
    return DesktopWorkspace(
        data, bundle / "git/cmd/git.exe", configuration.client_id, _protect, _unprotect
    )
