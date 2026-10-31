"""One local coding run at a time, with an encrypted, durable execution journal."""

import json
import logging
import os
import re
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

from cairn_api.errors import ApiProblem
from cairn_api.knowledge.answer_models import AnswerModelOption
from cairn_api.knowledge.answer_provider import (
    AnswerProviderInvalidResponse,
    AnswerProviderUnavailable,
)
from cairn_api.workspace.architecture import (
    KNOWN_TOKEN,
    SECRET_ASSIGNMENT,
    SECRET_UNQUOTED,
    SECRET_XML,
    URI_CREDENTIAL,
    eligible_source,
)
from cairn_api.workspace.coding_process import problem, run_command
from cairn_api.workspace.coding_schemas import (
    CodingChange,
    CodingEvent,
    CodingEventKind,
    CodingRun,
    CodingRunList,
    CodingStart,
    CodingStep,
    CommandDecision,
    ListFiles,
    PendingCommand,
    ReadFile,
    RunCommand,
    WriteFile,
)
from cairn_api.workspace.editor import FileDocument, RepositoryEditor, SaveFileRequest
from cairn_api.workspace.local import DesktopWorkspace

ACTIVE = {'running', 'awaiting_approval', 'cancelling'}
logger = logging.getLogger(__name__)


def sanitize(text: str) -> str:
    text = SECRET_ASSIGNMENT.sub(lambda m: m[1] + m[2] + '[REDACTED]' + m[2], text)
    text = SECRET_XML.sub(r'\1[REDACTED]\2', text)
    text = KNOWN_TOKEN.sub('[REDACTED]', text)
    text = URI_CREDENTIAL.sub(r'\1[REDACTED]@', text)
    text = re.sub(r'(?i)(https?://)[^\s/@]+@', r'\1[REDACTED]@', text)
    text = SECRET_UNQUOTED.sub(r'\1[REDACTED]', text)
    text = re.sub(r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b', '[REDACTED]', text)
    return re.sub(r'(?s)-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----.*?-----END (?:[A-Z ]+ )?PRIVATE KEY-----', '[REDACTED]', text)


class CodingProvider(Protocol):
    def coding_step(self, *, context: dict[str, object], check_cancelled: Callable[[], None]) -> CodingStep: ...


class Cancelled(Exception):
    pass


@dataclass
class Execution:
    run: CodingRun
    cancel: threading.Event = field(default_factory=threading.Event)
    decision: threading.Event = field(default_factory=threading.Event)
    approved: bool = False
    verified: bool = False
    thread: threading.Thread | None = None


class CodingRunner:
    def __init__(self, workspace: DesktopWorkspace):
        self.workspace = workspace
        self.directory = workspace.data / 'coding-runs'
        self.runs: dict[UUID, CodingRun] = {}
        self.active: Execution | None = None
        self.closed = False
        try:
            self.directory.mkdir(exist_ok=True)
            for path in self.directory.glob('*.dpapi'):
                if path.stat().st_size > 4_000_000:
                    raise ValueError('Run record is too large')
                run = CodingRun.model_validate_json(workspace.unprotect(path.read_bytes()))
                if path.stem != str(run.id):
                    raise ValueError('Run identity mismatch')
                self.runs[run.id] = run
                if run.status in ACTIVE:
                    run.status = 'interrupted'
                    run.pending_command = None
                    self._event(run, 'interrupted', '应用上次退出时运行尚未结束；已保留改动和记录，不会自动重跑命令。')
        except (OSError, ValueError):
            raise problem('coding_storage_failed', '编程运行记录无法读取或解密，原文件已保留') from None

    def _save(self, run: CodingRun) -> None:
        temporary: str | None = None
        try:
            data = self.workspace.protect(run.model_dump_json().encode())
            if len(data) > 4_000_000:
                raise ValueError('Run record is too large')
            with tempfile.NamedTemporaryFile(dir=self.directory, prefix='.run-', delete=False) as stream:
                temporary = stream.name
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.directory / f'{run.id}.dpapi')
        except (OSError, ValueError):
            raise problem('coding_storage_failed', '无法保存编程运行记录，请检查数据目录权限或空间；已停止执行') from None
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)

    def _event(self, run: CodingRun, kind: CodingEventKind, message: str,
               *, path: str | None = None, exit_code: int | None = None) -> None:
        with self.workspace.lock:
            run.updated_at = datetime.now(UTC)
            if kind == 'output' and run.events and run.events[-1].kind == 'output':
                run.events[-1].message += message
            else:
                if len(run.events) >= 998 and kind not in {'error', 'cancelled', 'interrupted', 'finished'}:
                    raise problem('coding_event_limit', '运行记录达到上限，已停止执行并保留现有记录')
                run.events.append(CodingEvent(id=len(run.events), at=run.updated_at, kind=kind, message=message, path=path, exit_code=exit_code))
            self._save(run)

    def require_idle(self) -> None:
        if self.active is not None:
            raise problem('coding_run_active', '已有编程 Agent 正在运行，请先停止或等待完成；草稿已保留')
        if self.closed:
            raise problem('coding_runtime_stopped', '编程执行服务正在关闭')

    def get(self, user: UUID, project: UUID, run_id: UUID) -> CodingRun:
        with self.workspace.lock:
            run = self.runs.get(run_id)
            if run is None or run.user_id != user or run.project_id != project:
                raise ApiProblem(status_code=404, code='coding_run_missing', message='运行记录不存在')
            return run.model_copy(deep=True)

    def list(self, user: UUID, project: UUID) -> CodingRunList:
        with self.workspace.lock:
            return CodingRunList(items=[run.model_copy(deep=True) for run in sorted(
                self.runs.values(), key=lambda item: item.created_at, reverse=True,
            ) if run.user_id == user and run.project_id == project][:20])

    def start(self, user: UUID, project: UUID, payload: CodingStart, *, assistant_name: str,
              model: AnswerModelOption, provider: CodingProvider, guidance: dict[str, object] | None,
              authorize: Callable[[], None]) -> CodingRun:
        with self.workspace.lock:
            self.require_idle()
            editor = RepositoryEditor(self.workspace, user, project)
            root, _, _, workspace_id = editor.context(payload.workspace_id)
            now = datetime.now(UTC)
            run = CodingRun(id=uuid4(), user_id=user, project_id=project, workspace_id=workspace_id,
                local_path=str(root), task=payload.task, assistant_id=payload.assistant_id,
                assistant_name=assistant_name, model=model, skill_id=payload.skill_id,
                status='running', created_at=now, updated_at=now, events=[], changes=[])
            self._event(run, 'started', '已开始；文件写入限关联仓库，命令逐条确认后以当前系统用户权限运行。')
            self.runs[run.id] = run
            execution = Execution(run)
            self.active = execution
            execution.thread = threading.Thread(target=self._execute, args=(execution, editor, provider, guidance, authorize), daemon=True)
            execution.thread.start()
            return run.model_copy(deep=True)

    def decide(self, user: UUID, project: UUID, run_id: UUID, decision: CommandDecision) -> CodingRun:
        with self.workspace.lock:
            self.get(user, project, run_id)
            execution = self.active
            if (execution is None or execution.run.id != run_id or execution.run.status != 'awaiting_approval'
                    or execution.run.pending_command is None or execution.run.pending_command.event_id != decision.event_id):
                raise problem('coding_approval_changed', '此命令已处理或运行状态已变化，请刷新记录')
            execution.approved = decision.approved
            execution.verified = decision.verify and execution.run.pending_command.purpose == 'test'
            execution.run.status = 'running' if decision.approved else 'cancelling'
            if not decision.approved:
                execution.cancel.set()
            self._event(execution.run, 'approval', ('用户批准了此命令并确认其用于验证任务' if execution.verified else '用户批准了此命令，未将其认定为任务验证') if decision.approved else '用户拒绝了此命令，停止本次运行')
            execution.decision.set()
            return execution.run.model_copy(deep=True)

    def cancel(self, user: UUID, project: UUID, run_id: UUID) -> CodingRun:
        with self.workspace.lock:
            run = self.get(user, project, run_id)
            if self.active is not None and self.active.run.id == run_id:
                if self.active.cancel.is_set():
                    return run
                self.active.cancel.set()
                self.active.decision.set()
                self.active.run.status = 'cancelling'
                self._event(self.active.run, 'cancelled', '正在停止；已发生的文件修改和输出将保留。')
                return self.active.run.model_copy(deep=True)
            return run

    def close(self) -> None:
        with self.workspace.lock:
            self.closed = True
            execution = self.active
            if execution:
                execution.cancel.set()
                execution.decision.set()
        if execution and execution.thread:
            execution.thread.join(timeout=3)

    def _execute(self, execution: Execution, editor: RepositoryEditor, provider: CodingProvider,
                 guidance: dict[str, object] | None, authorize: Callable[[], None]) -> None:
        run = execution.run
        documents: dict[str, FileDocument] = {}
        history: list[dict[str, object]] = []
        tested = False
        tested_versions: dict[str, str | None] | None = None
        last_auth = 0.0

        def check() -> None:
            if execution.cancel.is_set():
                raise Cancelled()

        def boundary() -> None:
            check()
            authorize()
            with self.workspace.lock:
                editor.context(run.workspace_id)

        def command_check() -> None:
            nonlocal last_auth
            check()
            if time.monotonic() - last_auth >= 1:
                boundary()
                last_auth = time.monotonic()

        def safe_document(path: str) -> FileDocument:
            if not eligible_source(path) or path not in editor.tree().paths:
                raise problem('coding_file_excluded', f'文件不在可发送给模型的源码范围内：{path}')
            doc = editor.read(path)
            if len(doc.content.encode()) > 32768:
                raise problem('coding_file_limit', f'编程 Agent 当前支持最多 32 KiB 的源码文件：{path}')
            if sanitize(doc.content) != doc.content:
                raise problem('coding_sensitive_file', f'文件含疑似凭据，未发送给模型：{path}')
            return doc

        def changed_documents() -> dict[str, FileDocument | None]:
            result: dict[str, FileDocument | None] = {}
            for item in editor.changes().files:
                if not eligible_source(item.path):
                    continue
                try:
                    doc = editor.read(item.path)
                except ApiProblem as error:
                    if error.code != 'workspace_file_missing':
                        raise
                    doc = None
                if doc is not None and (len(doc.content.encode()) > 32768 or sanitize(doc.content) != doc.content):
                    raise problem('coding_change_not_recordable', f'变更文件过大或含疑似凭据，无法记录本次差异：{item.path}')
                result[item.path] = doc
                if len(result) > 50:
                    raise problem('coding_change_limit', '工作目录变更超过 50 个源码文件，请先整理后再运行')
            return result

        def versions(values: dict[str, FileDocument | None]) -> dict[str, str | None]:
            return {path: doc.revision if doc else None for path, doc in values.items()}

        def record_change(path: str, before: str, after: FileDocument | None, origin: str) -> None:
            change = next((item for item in run.changes if item.path == path), None)
            if change is None:
                if len(run.changes) >= 50:
                    raise problem('coding_change_limit', '单次运行最多记录 50 个修改文件，请拆分任务')
                change = CodingChange(path=path, before=before, after='', revision=None, origin='file_tool')
                run.changes.append(change)
            change.after, change.revision = (after.content, after.revision) if after else ('', None)
            change.origin = 'command' if origin == 'command' else 'file_tool'

        try:
            for _ in range(40):
                boundary()
                paths = [path for path in editor.tree().paths if eligible_source(path)]
                context: dict[str, object] = {'task': run.task, 'guidance': guidance,
                    'files': paths[:1000], 'fileCount': len(paths), 'history': history,
                    'platform': sys.platform, 'pythonExecutable': sys.executable,
                    'gitExecutable': str(self.workspace.git), 'workingDirectory': run.local_path}
                if len(json.dumps(context, ensure_ascii=False).encode()) > 256000:
                    raise problem('coding_context_limit', '本次执行上下文超过 256 KiB，已保留结果，请拆分任务')
                result = provider.coding_step(context=context, check_cancelled=check)
                step = CodingStep.model_validate(result)
                boundary()
                self._event(run, 'step', sanitize(step.message))
                action = step.action
                response: object
                if isinstance(action, ListFiles):
                    matching = [path for path in paths if action.query.lower() in path.lower()]
                    response = {'paths': matching[:1000], 'count': len(matching)}
                elif isinstance(action, ReadFile):
                    doc = safe_document(action.path)
                    documents[action.path] = doc
                    response = {'path': doc.path, 'content': doc.content}
                    self._event(run, 'read', '已读取文件', path=doc.path)
                elif isinstance(action, WriteFile):
                    if not eligible_source(action.path) or sanitize(action.content) != action.content:
                        raise problem('coding_file_excluded', '不能写入敏感文件或疑似凭据内容')
                    previous = documents.get(action.path)
                    if not action.create and previous is None:
                        raise problem('coding_read_required', '修改已有文件前必须先读取文件')
                    with self.workspace.lock:
                        check()
                        if len(run.changes) >= 50 and all(item.path != action.path for item in run.changes):
                            raise problem('coding_change_limit', '单次运行最多记录 50 个修改文件，请拆分任务')
                        saved = editor.save(SaveFileRequest(workspace_id=run.workspace_id,
                            path=action.path, revision=None if action.create else previous.revision if previous else None,
                            content=action.content))
                        record_change(action.path, previous.content if previous else '', saved, 'file_tool')
                        documents[action.path] = saved
                        tested = False
                        self._event(run, 'write', f'{run.assistant_name} 已写入文件', path=action.path)
                    response = {'path': saved.path, 'saved': True}
                elif isinstance(action, RunCommand):
                    with self.workspace.lock:
                        check()
                        execution.decision.clear()
                        execution.approved = False
                        execution.verified = False
                        run.pending_command = PendingCommand(**action.model_dump(), event_id=len(run.events))
                        run.status = 'awaiting_approval'
                        self._event(run, 'approval', json.dumps(action.argv, ensure_ascii=False))
                    while not execution.decision.wait(0.2):
                        command_check()
                    boundary()
                    if not execution.approved:
                        raise Cancelled()
                    before_command = changed_documents()
                    try:
                        code, output = run_command(action.argv, Path(run.local_path), self.workspace.git,
                            action.timeout_seconds, command_check, lambda text: self._event(run, 'output', text))
                    finally:
                        after_command = changed_documents()
                        with self.workspace.lock:
                            for path in before_command.keys() | after_command.keys():
                                before, after = before_command.get(path), after_command.get(path)
                                if (before.revision if before else None) == (after.revision if after else None) and (path in before_command) == (path in after_command):
                                    continue
                                prior = (before.content if before else '') if path in before_command else editor.diff(path).original
                                current = after
                                if path not in after_command:
                                    try:
                                        current = editor.read(path)
                                    except ApiProblem as error:
                                        if error.code != 'workspace_file_missing':
                                            raise
                                record_change(path, prior, current, 'command')
                                self._event(run, 'write', '命令执行期间发生源码变化；请核对差异', path=path)
                    with self.workspace.lock:
                        run.pending_command = None
                        self._event(run, 'command_result', f'{"测试" if action.purpose == "test" else "命令"}退出码：{code}', exit_code=code)
                    if code != 0:
                        raise problem('coding_command_failed', f'命令失败（退出码 {code}），请查看输出并调整任务')
                    boundary()
                    tested = action.purpose == 'test' and execution.verified
                    tested_versions = versions(after_command) if tested else None
                    if tested and versions(before_command) != tested_versions:
                        tested = False
                    response = {'exitCode': code, 'output': sanitize(output)}
                else:
                    if not tested:
                        raise problem('coding_verification_required', '模型请求完成，但最近修改后没有成功的测试命令；不能标记成功')
                    if tested_versions != versions(changed_documents()):
                        raise problem('coding_verification_stale', '测试后源码发生变化，原测试结果已失效；改动已保留')
                    with self.workspace.lock:
                        check()
                        run.status = 'succeeded'
                        run.summary = sanitize(action.summary)
                        self._event(run, 'finished', run.summary)
                    return
                history.append({'step': step.model_dump(mode='json'), 'result': response})
            raise problem('coding_step_limit', '已达到单次 40 步上限，改动和记录已保留，请拆分后续任务')
        except Cancelled:
            self._finish_failure(run, 'cancelled', None, '已停止执行。修改和运行记录已保留；重新开始需新建任务。')
        except ApiProblem as error:
            self._finish_failure(run, 'failed', error.code, error.message)
        except AnswerProviderUnavailable:
            self._finish_failure(run, 'failed', 'coding_model_unavailable', '模型请求失败，请检查当前 Agent 的模型配置和连接')
        except (AnswerProviderInvalidResponse, ValueError):
            self._finish_failure(run, 'failed', 'coding_invalid_response', '模型未返回有效的执行步骤；运行已停止')
        except OSError as error:
            self._finish_failure(run, 'failed', 'coding_process_failed', f'无法执行本机命令：{error.strerror or type(error).__name__}')
        except Exception:
            logger.exception('Coding run %s failed unexpectedly', run.id)
            self._finish_failure(run, 'failed', 'coding_execution_failed', f'执行出现未预期错误，运行编号：{run.id}')
        finally:
            with self.workspace.lock:
                self.active = None

    def _finish_failure(self, run: CodingRun, status: str, code: str | None, message: str) -> None:
        with self.workspace.lock:
            run.status = 'cancelled' if status == 'cancelled' else 'failed'
            run.pending_command = None
            run.error_code, run.summary = code, message
            try:
                self._event(run, 'cancelled' if status == 'cancelled' else 'error', message)
            except ApiProblem:
                run.status = 'failed'
                run.error_code = 'coding_storage_failed'
                run.summary = '执行已停止，但最终记录未能保存；请检查数据目录权限或空间。'
                logger.error('Cannot persist stopped coding run %s', run.id)
