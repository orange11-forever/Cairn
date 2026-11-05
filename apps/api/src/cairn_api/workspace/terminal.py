import logging
import threading
import time
from collections.abc import Callable
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field, field_validator

from cairn_api.errors import ApiProblem
from cairn_api.workspace.editor import RepositoryEditor
from cairn_api.workspace.local import DesktopWorkspace
from cairn_api.workspace.schemas import WorkspaceModel
from cairn_api.workspace.terminal_process import TerminalProcess

logger = logging.getLogger(__name__)


class TerminalSize(WorkspaceModel):
    cols: int = Field(default=100, ge=2, le=500, strict=True)
    rows: int = Field(default=24, ge=2, le=200, strict=True)


class TerminalStart(TerminalSize):
    workspace_id: str = Field(pattern=r'^[0-9a-f]{64}$')
    allow_execution: bool = Field(strict=True)


class TerminalInput(WorkspaceModel):
    data: str = Field(min_length=1, max_length=8192)

    @field_validator('data')
    @classmethod
    def valid_utf8(cls, value: str) -> str:
        if len(value.encode('utf-8')) > 8192:
            raise ValueError('Terminal input exceeds 8 KiB')
        return value


class TerminalSnapshot(WorkspaceModel):
    id: UUID
    local_path: str
    shell: str
    status: Literal['running', 'exited', 'stopped', 'failed']
    exit_code: int | None = None
    error: str | None = None
    output: str
    start_offset: int
    next_offset: int


def problem(code: str, message: str, status: int = 409) -> ApiProblem:
    return ApiProblem(status_code=status, code=code, message=message)


class TerminalSession:
    def __init__(self, process: TerminalProcess, local_path: str, authorize: Callable[[], None]):
        self.id = uuid4()
        self.process = process
        self.local_path = local_path
        self.authorize = authorize
        self.lock = threading.RLock()
        self.input_lock = threading.Lock()
        self.stopping = threading.Event()
        self.status: Literal['running', 'exited', 'stopped', 'failed'] = 'running'
        self.error: str | None = None
        self.exit_code: int | None = None
        self.output = ''
        self.offset = 0
        self.thread = threading.Thread(target=self.run, daemon=True, name=f'terminal-{self.id}')
        self.thread.start()

    def append(self, text: str) -> None:
        with self.lock:
            self.output = (self.output + text)[-262144:]
            self.offset += len(text)

    def snapshot(self, after: int) -> TerminalSnapshot:
        with self.lock:
            start = max(self.offset - len(self.output), min(after, self.offset))
            return TerminalSnapshot(id=self.id, local_path=self.local_path, shell=self.process.shell,
                status=self.status, exit_code=self.exit_code, error=self.error,
                output=self.output[start - (self.offset - len(self.output)):],
                start_offset=start, next_offset=self.offset)

    def require_running(self) -> None:
        if self.status != 'running' or self.stopping.is_set():
            raise problem('terminal_closed', '终端已结束，请新建会话')

    def write(self, data: str) -> None:
        self.require_running()
        self.authorize()
        try:
            with self.input_lock:
                self.process.write(data, self.stopping)
        except Exception as error:
            if not self.stopping.is_set():
                self.fail(error)
            raise problem('terminal_input_failed', '终端输入失败，会话已停止；请查看终端错误') from error

    def resize(self, cols: int, rows: int) -> None:
        self.require_running()
        try:
            self.process.resize(cols, rows)
        except Exception as error:
            self.fail(error)
            raise problem('terminal_resize_failed', '无法调整终端尺寸，会话已停止') from error

    def fail(self, error: Exception) -> None:
        with self.lock:
            self.status = 'failed'
            self.error = error.message if isinstance(error, ApiProblem) else f'{type(error).__name__}: {error}'
        self.stopping.set()

    def run(self) -> None:
        next_authorization = 0.0
        try:
            while not self.stopping.is_set():
                if time.monotonic() >= next_authorization:
                    self.authorize()
                    next_authorization = time.monotonic() + 2
                text = self.process.read()
                if text:
                    self.append(text)
                elif not self.process.alive():
                    self.exit_code = self.process.exit_code()
                    break
                self.stopping.wait(0.02)
        except Exception as error:
            logger.exception('Terminal %s failed', self.id)
            self.fail(error)
        finally:
            stopped = self.stopping.is_set()
            self.stopping.set()
            try:
                with self.input_lock:
                    self.process.close()
            except Exception as error:
                logger.exception('Terminal %s cleanup failed', self.id)
                self.fail(error)
            with self.lock:
                if self.status == 'running':
                    self.status = 'stopped' if stopped else 'exited'

    def stop(self) -> None:
        self.stopping.set()
        self.thread.join(timeout=5)
        if self.thread.is_alive():
            raise problem('terminal_stop_failed', '终端进程尚未结束，请关闭 Cairn 后检查系统进程')


class TerminalManager:
    def __init__(self, workspace: DesktopWorkspace):
        self.workspace = workspace
        self.sessions: dict[tuple[UUID, UUID], TerminalSession] = {}

    def start(self, user: UUID, project: UUID, payload: TerminalStart,
              authorize: Callable[[], None]) -> TerminalSnapshot:
        if not payload.allow_execution:
            raise problem('terminal_consent_required', '请确认允许在本机运行终端命令', 422)
        with self.workspace.lock:
            self.require_idle(user, project)
            if sum(item.thread.is_alive() for item in self.sessions.values()) >= 8:
                raise problem('terminal_limit', '本机已有 8 个运行中的终端，请先关闭一个')
            root, _, _, _ = RepositoryEditor(self.workspace, user, project).context(payload.workspace_id)
            authorize()
            try:
                process = TerminalProcess(root, self.workspace.git, payload.cols, payload.rows)
            except Exception as error:
                raise problem('terminal_start_failed', f'无法启动本机终端：{type(error).__name__}: {error}', 503) from error
            session = TerminalSession(process, str(root), authorize)
            self.sessions[user, project] = session
            return session.snapshot(0)

    def current(self, user: UUID, project: UUID, after: int) -> TerminalSnapshot | None:
        with self.workspace.lock:
            session = self.sessions.get((user, project))
            return session.snapshot(after) if session else None

    def session(self, user: UUID, project: UUID, session_id: UUID) -> TerminalSession:
        with self.workspace.lock:
            session = self.sessions.get((user, project))
            if session is None or session.id != session_id:
                raise problem('terminal_not_found', '此终端会话不存在或已被替换', 404)
            return session

    def require_idle(self, user: UUID, project: UUID) -> None:
        session = self.sessions.get((user, project))
        if session and session.thread.is_alive():
            raise problem('terminal_running', '请先关闭此项目的交互终端')

    def close(self) -> None:
        with self.workspace.lock:
            sessions = list(self.sessions.values())
        for session in sessions:
            session.stop()
