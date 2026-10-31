from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, field_validator

from cairn_api.knowledge.answer_models import AnswerModelOption
from cairn_api.workspace.delivery_schemas import CodingDeliveryState, DeliveryPhase
from cairn_api.workspace.schemas import WorkspaceModel


class ListFiles(WorkspaceModel):
    kind: Literal['list_files']
    query: str = Field(max_length=200)


class ReadFile(WorkspaceModel):
    kind: Literal['read_file']
    path: str = Field(min_length=1, max_length=4096)


class WriteFile(WorkspaceModel):
    kind: Literal['write_file']
    path: str = Field(min_length=1, max_length=4096)
    content: str = Field(max_length=32768)
    create: bool = Field(strict=True)

    @field_validator('content')
    @classmethod
    def bounded_utf8(cls, value: str) -> str:
        if len(value.encode('utf-8')) > 32768:
            raise ValueError('Source content exceeds 32 KiB')
        return value


class RunCommand(WorkspaceModel):
    kind: Literal['run_command']
    argv: list[str] = Field(min_length=1, max_length=64)
    purpose: Literal['command', 'test']
    timeout_seconds: int = Field(ge=1, le=120, strict=True)

    @field_validator('argv')
    @classmethod
    def valid_argv(cls, value: list[str]) -> list[str]:
        if not value[0].strip() or any('\x00' in item or len(item) > 8192 for item in value):
            raise ValueError('Invalid command arguments')
        if sum(map(len, value)) > 16384:
            raise ValueError('Command is too long')
        return value


class Finish(WorkspaceModel):
    kind: Literal['finish']
    summary: str = Field(min_length=1, max_length=4000)


CodingAction = Annotated[ListFiles | ReadFile | WriteFile | RunCommand | Finish, Field(discriminator='kind')]


class CodingStep(WorkspaceModel):
    message: str = Field(min_length=1, max_length=2000)
    action: CodingAction


class CodingStart(WorkspaceModel):
    workspace_id: str = Field(pattern=r'^[0-9a-f]{64}$')
    task: str = Field(min_length=1, max_length=6000)
    assistant_id: UUID | None = None
    assistant_revision: int = Field(ge=0, strict=True)
    skill_id: str | None = Field(default=None, max_length=100)
    allow_writes: Literal[True]
    depends_on: UUID | None = None

    @field_validator('task')
    @classmethod
    def task_not_blank(cls, value: str) -> str:
        if not value.strip() or '\x00' in value:
            raise ValueError('Task cannot be blank')
        return value.strip()


class CommandDecision(WorkspaceModel):
    event_id: int = Field(ge=0, strict=True)
    approved: bool = Field(strict=True)
    verify: bool = Field(default=False, strict=True)


class PendingCommand(RunCommand):
    event_id: int


CodingEventKind = Literal['queued', 'started', 'step', 'read', 'write', 'approval', 'output', 'command_result', 'finished', 'error', 'cancelled', 'interrupted']


class CodingEvent(WorkspaceModel):
    id: int
    at: datetime
    kind: CodingEventKind
    message: str
    path: str | None = None
    exit_code: int | None = None


class CodingChange(WorkspaceModel):
    path: str
    before: str
    after: str
    revision: str | None
    origin: Literal['file_tool', 'command']


class CodingOverlap(WorkspaceModel):
    run_id: UUID
    assistant_name: str
    paths: list[str]


CodingStatus = Literal['queued', 'blocked', 'running', 'awaiting_approval', 'cancelling', 'cancelled', 'failed', 'succeeded', 'interrupted']


class CodingRun(WorkspaceModel):
    id: UUID
    user_id: UUID
    project_id: UUID
    workspace_id: str
    local_path: str
    task: str
    assistant_id: UUID | None
    assistant_name: str
    model: AnswerModelOption
    skill_id: str | None
    status: CodingStatus
    created_at: datetime
    updated_at: datetime
    events: list[CodingEvent] = Field(max_length=1000)
    changes: list[CodingChange] = Field(max_length=50)
    pending_command: PendingCommand | None = None
    error_code: str | None = None
    summary: str | None = None
    # Defaults allow reading the existing encrypted single-Agent journals.
    repository_path: str | None = None
    branch: str | None = None
    base_head: str | None = None
    assistant_revision: int = 0
    depends_on: UUID | None = None
    overlaps: list[CodingOverlap] = Field(default_factory=list[CodingOverlap])
    delivery: CodingDeliveryState | None = None


class CodingConcurrency(WorkspaceModel):
    limit: int = Field(ge=1, le=4, strict=True)


class CodingRunSummary(WorkspaceModel):
    id: UUID
    project_id: UUID
    project_name: str
    assistant_name: str
    task: str
    model_name: str
    status: CodingStatus
    updated_at: datetime
    progress: str
    changed_files: int
    depends_on: UUID | None
    delivery_phase: DeliveryPhase | None = None
    pr_url: str | None = None


class CodingOverview(WorkspaceModel):
    concurrency: int
    items: list[CodingRunSummary]


class CodingRunList(WorkspaceModel):
    items: list[CodingRun]
