from typing import Annotated, Literal

from pydantic import Field, field_validator

from cairn_api.workspace.schemas import WorkspaceModel

Sha = Annotated[str, Field(pattern=r'^(?:[0-9a-f]{40}|[0-9a-f]{64})$')]
Digest = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
BranchName = Annotated[str, Field(min_length=1, max_length=1024, pattern=r'^[^\x00-\x20\x7f\\~^:?*\[]+$')]


class RemoteTarget(WorkspaceModel):
    repository_id: int = Field(gt=0, strict=True)
    full_name: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}$')
    private: bool
    account_id: int = Field(gt=0, strict=True)
    account_login: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9-]{0,38}$')
    base_branch: BranchName
    base_sha: Sha
    head_branch: str
    head_sha: Sha


DeliveryPhase = Literal['uncommitted', 'committing', 'commit_unknown', 'committed', 'pushing', 'push_unknown', 'pushed', 'creating_pr', 'pr_unknown', 'pr_created']


class CodingDeliveryState(WorkspaceModel):
    phase: DeliveryPhase = 'uncommitted'
    snapshot_id: Digest | None = None
    commit_sha: Sha | None = None
    tree_sha: Sha | None = None
    index_digest: Digest | None = None
    message: str | None = None
    author_name: str | None = None
    author_email: str | None = None
    target: RemoteTarget | None = None
    pr_number: int | None = None
    pr_url: str | None = Field(default=None, pattern=r'^https://github\.com/[A-Za-z0-9-]+/[A-Za-z0-9_.-]+/pull/[1-9][0-9]*$')
    pr_state: Literal['open', 'closed'] | None = None
    pr_draft: bool | None = None
    error: str | None = None


class CommitRequest(WorkspaceModel):
    snapshot_id: Digest
    message: str = Field(min_length=1, max_length=4000)
    author_name: str = Field(min_length=1, max_length=100)
    author_email: str = Field(min_length=3, max_length=254, pattern=r'^[^\s\x00-\x1f\x7f<>@]+@[^\s\x00-\x1f\x7f<>@]+$')

    @field_validator('message', 'author_name')
    @classmethod
    def valid_text(cls, value: str) -> str:
        if not value.strip() or '\x00' in value:
            raise ValueError('Text cannot be blank or contain NUL')
        return value.strip()

    @field_validator('author_name')
    @classmethod
    def valid_author(cls, value: str) -> str:
        if any(ord(char) < 32 or char in '<>' for char in value):
            raise ValueError('Invalid Git author name')
        return value


class PrepareRemoteRequest(WorkspaceModel):
    base_branch: BranchName


class PushRequest(WorkspaceModel):
    target: RemoteTarget
    allow_push: Literal[True]


class PullRequestInput(WorkspaceModel):
    target: RemoteTarget
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=12000)
    allow_create: Literal[True]
    draft: bool = Field(default=True, strict=True)

    @field_validator('title', 'body')
    @classmethod
    def valid_text(cls, value: str) -> str:
        if not value.strip() or '\x00' in value:
            raise ValueError('Text cannot be blank or contain NUL')
        return value.strip()


class DeliveryReview(WorkspaceModel):
    snapshot_id: Digest
    files: list[str]
    excluded_paths: list[str]
    suggested_message: str
    suggested_title: str
    suggested_body: str = Field(max_length=12000)
    delivery: CodingDeliveryState
