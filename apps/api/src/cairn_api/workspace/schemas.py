from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field
from pydantic.alias_generators import to_camel


class WorkspaceModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class GitHubAccount(WorkspaceModel):
    id: int = Field(gt=0, strict=True)
    login: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}$")


class GitHubRepository(WorkspaceModel):
    id: int = Field(gt=0, strict=True)
    full_name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}$")
    private: bool
    default_branch: str = Field(min_length=1, max_length=1024)
    can_push: bool

    @computed_field
    @property
    def url(self) -> str:
        return "https://github.com/" + self.full_name


class GitHubRepositoryPage(WorkspaceModel):
    items: list[GitHubRepository]
    next_page: int | None


class GitHubConnection(WorkspaceModel):
    configured: bool
    status: Literal["disconnected", "connected", "expired", "revoked", "unavailable"]
    account: GitHubAccount | None = None
    message: str | None = None


class GitHubDeviceStart(WorkspaceModel):
    intent: Literal["login", "link", "repositories"]


class GitHubDeviceStarted(WorkspaceModel):
    attempt_id: str
    user_code: str
    verification_uri: Literal["https://github.com/login/device"] = "https://github.com/login/device"
    expires_in: int
    interval: int


class GitHubDevicePoll(WorkspaceModel):
    attempt_id: str = Field(min_length=32, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class GitHubDeviceResult(WorkspaceModel):
    status: Literal["pending", "login_ready", "linked", "connected"]
    interval: int = 5
    account: GitHubAccount | None = None


class RepositoryBinding(WorkspaceModel):
    local_path: str
    branch: str | None
    repository: GitHubRepository | None = None
    account: GitHubAccount | None = None


class WorkspaceStatus(WorkspaceModel):
    binding: RepositoryBinding | None
    git_available: bool
    repository_status: Literal["local", "available", "unavailable", "changed"] = "local"
    message: str | None = None


class RepositoryBindRequest(WorkspaceModel):
    local_path: str = Field(min_length=1, max_length=4096, pattern=r"^[^\x00-\x1f]+$")
    repository_id: int | None = Field(default=None, gt=0, strict=True)
    mode: Literal["existing", "clone"] = "existing"
