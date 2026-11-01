import base64
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from cairn_api.errors import ApiProblem
from cairn_api.knowledge.answer_models import AnswerModelOption
from cairn_api.workspace.coding import CodingRunner
from cairn_api.workspace.coding_process import run_command
from cairn_api.workspace.coding_schemas import CodingRun, CodingStart, CodingStep, CommandDecision
from cairn_api.workspace.editor import RepositoryEditor
from cairn_api.workspace.local import DesktopWorkspace

CodingFixture = tuple[CodingRunner, UUID, UUID, Path]


class ScriptedModel:
    def __init__(self, steps: list[dict[str, object]]):
        self.steps = iter(steps)

    def coding_step(self, *, context: dict[str, object], check_cancelled: Callable[[], None]) -> CodingStep:
        return CodingStep.model_validate(next(self.steps))


@pytest.fixture
def coding(tmp_path: Path) -> Iterator[CodingFixture]:
    root, data = tmp_path / 'repo', tmp_path / 'data'
    root.mkdir()
    data.mkdir()
    subprocess.run(['git', '-C', str(root), 'init', '-b', 'main'], check=True, capture_output=True)
    (root / 'main.py').write_text('print("before")\n')
    subprocess.run(['git', '-C', str(root), 'add', 'main.py'], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(root), '-c', 'user.name=Test', '-c', 'user.email=test@example.test', 'commit', '-m', 'baseline'], check=True, capture_output=True)
    workspace = DesktopWorkspace(data, Path('/usr/bin/git'), None, base64.b64encode, base64.b64decode)
    user, project = uuid4(), uuid4()
    workspace.bind_local(user, project, str(root))
    runner = CodingRunner(workspace)
    yield runner, user, project, root
    runner.close()


def start(coding: CodingFixture, steps: list[dict[str, object]], authorize: Callable[[], None] = lambda: None) -> CodingRun:
    runner, user, project, _ = coding
    tree = RepositoryEditor(runner.workspace, user, project).tree()
    return runner.start(user, project, CodingStart(
        workspace_id=tree.workspace_id, task='Make the change and test it',
        assistant_revision=0, allow_writes=True,
    ), assistant_name='Test Agent', model=AnswerModelOption(
        id='default', name='Test model', model='fixture', protocol='openai-compatible',
    ), provider=ScriptedModel(steps), guidance=None, authorize=authorize)


def wait_status(coding: CodingFixture, run_id: UUID, expected: set[str], seconds: float = 8) -> CodingRun:
    runner, user, project, _ = coding
    run = runner.get(user, project, run_id)
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        run = runner.get(user, project, run_id)
        if run.status in expected:
            return run
        time.sleep(0.02)
    pytest.fail(f'run did not reach {expected}: {run.status}, {run.events[-2:]}')


def step(kind: str, **kwargs: object) -> dict[str, object]:
    return {'message': kind, 'action': {'kind': kind, **kwargs}}


def test_real_file_edit_approved_command_test_and_encrypted_restart_history(coding: CodingFixture) -> None:
    runner, user, project, root = coding
    run = start(coding, [
        step('read_file', path='main.py'),
        step('write_file', path='main.py', content='print("after")\n', create=False),
        step('run_command', argv=[sys.executable, '-c', 'from pathlib import Path; assert "after" in Path("main.py").read_text(); print("TEST PASSED")'], purpose='test', timeout_seconds=10),
        step('finish', summary='Updated and checked'),
    ])
    waiting = wait_status(coding, run.id, {'awaiting_approval'})
    assert (Path(run.local_path) / 'main.py').read_text() == 'print("after")\n'
    assert (root / 'main.py').read_text() == 'print("before")\n'
    assert waiting.pending_command is not None
    assert not any(event.kind == 'command_result' for event in waiting.events)
    runner.decide(user, project, run.id, CommandDecision(event_id=waiting.pending_command.event_id, approved=True, verify=True))
    done = wait_status(coding, run.id, {'succeeded', 'failed'})
    assert done.status == 'succeeded'
    assert 'TEST PASSED' in ''.join(e.message for e in done.events)
    assert done.changes[0].before == 'print("before")\n'
    assert done.changes[0].after == 'print("after")\n'
    assert any(e.kind == 'command_result' and e.exit_code == 0 for e in done.events)
    assert not any(b'Updated and checked' in path.read_bytes() for path in (runner.workspace.data / 'coding-runs').iterdir())
    reopened = CodingRunner(runner.workspace)
    try:
        assert reopened.get(user, project, run.id).status == 'succeeded'
        with pytest.raises(ApiProblem) as denied:
            reopened.get(uuid4(), project, run.id)
        assert denied.value.status_code == 404
    finally:
        reopened.close()


def test_model_finish_cannot_claim_success_without_real_test(coding: CodingFixture) -> None:
    run = start(coding, [step('finish', summary='Everything passed')])
    done = wait_status(coding, run.id, {'failed', 'succeeded'})
    assert done.status == 'failed'
    assert done.error_code == 'coding_verification_required'


def test_nonzero_command_is_failure_even_if_model_would_claim_success(coding: CodingFixture) -> None:
    runner, user, project, _ = coding
    run = start(coding, [step('run_command', argv=[sys.executable, '-c', 'print("broken"); raise SystemExit(7)'], purpose='test', timeout_seconds=10), step('finish', summary='all passed')])
    pending = wait_status(coding, run.id, {'awaiting_approval'}).pending_command
    assert pending is not None
    runner.decide(user, project, run.id, CommandDecision(event_id=pending.event_id, approved=True, verify=True))
    done = wait_status(coding, run.id, {'failed'})
    assert done.error_code == 'coding_command_failed'
    assert any(e.exit_code == 7 for e in done.events)


def test_cancel_stops_command_and_its_child_before_delayed_write(coding: CodingFixture) -> None:
    runner, user, project, _ = coding
    child = 'import time; from pathlib import Path; time.sleep(2); Path("escaped.txt").write_text("bad")'
    command = f'import subprocess,sys,time; subprocess.Popen([sys.executable,"-c",{child!r}]); print("READY",flush=True); time.sleep(30)'
    run = start(coding, [step('run_command', argv=[sys.executable, '-c', command], purpose='command', timeout_seconds=30)])
    pending = wait_status(coding, run.id, {'awaiting_approval'}).pending_command
    assert pending is not None
    runner.decide(user, project, run.id, CommandDecision(event_id=pending.event_id, approved=True, verify=True))
    deadline = time.monotonic() + 5
    while not any('READY' in e.message for e in runner.get(user, project, run.id).events):
        assert time.monotonic() < deadline
        time.sleep(0.02)
    runner.cancel(user, project, run.id)
    assert wait_status(coding, run.id, {'cancelled'}).status == 'cancelled'
    time.sleep(2.1)
    assert not (Path(run.local_path) / 'escaped.txt').exists()


def test_authorization_loss_between_steps_prevents_file_write(coding: CodingFixture) -> None:
    _, _, _, root = coding
    def revoked() -> None:
        raise ApiProblem(status_code=403, code='permission_revoked', message='Access removed')
    run = start(coding, [step('write_file', path='main.py', content='bad', create=True)], authorize=revoked)
    assert wait_status(coding, run.id, {'failed'}).error_code == 'permission_revoked'
    assert (root / 'main.py').read_text() == 'print("before")\n'


def test_one_agent_runs_serially_and_restart_does_not_resume_commands(coding: CodingFixture) -> None:
    runner, user, project, root = coding
    run = start(coding, [step('run_command', argv=[sys.executable, '-c', 'from pathlib import Path; Path("never.txt").touch()'], purpose='test', timeout_seconds=10)])
    wait_status(coding, run.id, {'awaiting_approval'})
    second = start(coding, [step('finish', summary='second')])
    assert second.status == 'queued'
    # Loading the persisted record after a stopped runtime must not execute it.
    runner.close()
    reopened = CodingRunner(runner.workspace)
    try:
        assert reopened.get(user, project, run.id).status in {'cancelled', 'interrupted'}
        assert not (root / 'never.txt').exists()
    finally:
        reopened.close()


def test_test_success_is_invalidated_by_later_external_edit(coding: CodingFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    runner, user, project, _ = coding
    original = ScriptedModel.coding_step
    def change_before_finish(self: ScriptedModel, *, context: dict[str, object], check_cancelled: Callable[[], None]) -> CodingStep:
        value = original(self, context=context, check_cancelled=check_cancelled)
        if value.action.kind == 'finish':
            (Path(str(context['workingDirectory'])) / 'main.py').write_text('external untested code')
        return value
    monkeypatch.setattr(ScriptedModel, 'coding_step', change_before_finish)
    run = start(coding, [step('run_command', argv=[sys.executable, '-c', 'from pathlib import Path; assert "before" in Path("main.py").read_text()'], purpose='test', timeout_seconds=10), step('finish', summary='done')])
    pending = wait_status(coding, run.id, {'awaiting_approval'}).pending_command
    assert pending
    runner.decide(user, project, run.id, CommandDecision(event_id=pending.event_id, approved=True, verify=True))
    done = wait_status(coding, run.id, {'failed', 'succeeded'})
    assert done.status == 'failed' and done.error_code == 'coding_verification_stale'


def test_command_changes_are_recorded_in_worktree_without_copying_main_edits(coding: CodingFixture) -> None:
    runner, user, project, root = coding
    (root / 'main.py').write_text('manual before\n')
    run = start(coding, [
        step('run_command', argv=[sys.executable, '-c', 'from pathlib import Path; Path("main.py").write_text("command after\\n")'], purpose='command', timeout_seconds=10),
        step('run_command', argv=[sys.executable, '-c', 'from pathlib import Path; assert Path("main.py").read_text() == "command after\\n"'], purpose='test', timeout_seconds=10),
        step('finish', summary='done'),
    ])
    for _ in range(2):
        pending = wait_status(coding, run.id, {'awaiting_approval'}).pending_command
        assert pending
        runner.decide(user, project, run.id, CommandDecision(event_id=pending.event_id, approved=True, verify=True))
    done = wait_status(coding, run.id, {'succeeded', 'failed'})
    assert done.status == 'succeeded'
    assert [(change.path, change.before, change.after) for change in done.changes] == [('main.py', 'print("before")\n', 'command after\n')]
    assert (root / 'main.py').read_text() == 'manual before\n'


def test_external_change_after_model_read_is_not_overwritten(coding: CodingFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    original = ScriptedModel.coding_step
    def change_after_read(self: ScriptedModel, *, context: dict[str, object], check_cancelled: Callable[[], None]) -> CodingStep:
        value = original(self, context=context, check_cancelled=check_cancelled)
        if value.action.kind == 'write_file':
            (Path(str(context['workingDirectory'])) / 'main.py').write_text('external kept')
        return value
    monkeypatch.setattr(ScriptedModel, 'coding_step', change_after_read)
    run = start(coding, [step('read_file', path='main.py'), step('write_file', path='main.py', content='agent change', create=False)])
    assert wait_status(coding, run.id, {'failed'}).error_code == 'workspace_file_conflict'
    assert (Path(run.local_path) / 'main.py').read_text() == 'external kept'


def test_model_labelled_print_command_is_not_verification_without_user_confirmation(coding: CodingFixture) -> None:
    runner, user, project, _ = coding
    run = start(coding, [step('run_command', argv=[sys.executable, '-c', 'print("ok")'], purpose='test', timeout_seconds=10), step('finish', summary='everything passed')])
    pending = wait_status(coding, run.id, {'awaiting_approval'}).pending_command
    assert pending
    runner.decide(user, project, run.id, CommandDecision(event_id=pending.event_id, approved=True))
    done = wait_status(coding, run.id, {'failed', 'succeeded'})
    assert done.status == 'failed' and done.error_code == 'coding_verification_required'


def test_command_deleting_tracked_file_keeps_its_before_content(coding: CodingFixture) -> None:
    runner, user, project, _ = coding
    run = start(coding, [
        step('run_command', argv=[sys.executable, '-c', 'from pathlib import Path; Path("main.py").unlink()'], purpose='command', timeout_seconds=10),
        step('run_command', argv=[sys.executable, '-c', 'from pathlib import Path; assert not Path("main.py").exists()'], purpose='test', timeout_seconds=10),
        step('finish', summary='removed and checked'),
    ])
    for _ in range(2):
        pending = wait_status(coding, run.id, {'awaiting_approval'}).pending_command
        assert pending
        runner.decide(user, project, run.id, CommandDecision(event_id=pending.event_id, approved=True, verify=True))
    done = wait_status(coding, run.id, {'succeeded', 'failed'})
    assert done.status == 'succeeded'
    assert done.changes[0].before == 'print("before")\n' and done.changes[0].after == ''
    assert done.changes[0].revision is None and done.changes[0].origin == 'command'


def test_persisted_active_record_becomes_interrupted_without_replaying(coding: CodingFixture) -> None:
    runner, user, project, root = coding
    run = start(coding, [step('run_command', argv=[sys.executable, '-c', 'raise SystemExit(0)'], purpose='command', timeout_seconds=10)])
    saved = wait_status(coding, run.id, {'awaiting_approval'})
    runner.close()
    # Simulate the last durable snapshot after abrupt runtime exit, not a graceful stop.
    path = runner.directory / f'{run.id}.dpapi'
    path.write_bytes(runner.workspace.protect(saved.model_dump_json().encode()))
    reopened = CodingRunner(runner.workspace)
    try:
        restored = reopened.get(user, project, run.id)
        assert restored.status == 'interrupted' and restored.pending_command is None
        assert restored.events[-1].kind == 'interrupted'
        assert (root / 'main.py').read_text() == 'print("before")\n'
    finally:
        reopened.close()


def test_command_does_not_inherit_service_credentials(coding: CodingFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    runner, _, _, root = coding
    monkeypatch.setenv('CAIRN_ANSWER_API_KEY', 'private-model-key')
    monkeypatch.setenv('PGPASSWORD', 'private-db-password')
    monkeypatch.setenv('GITHUB_TOKEN', 'private-github-token')
    code, output = run_command([sys.executable, '-c',
        'import os; assert all(name not in os.environ for name in ("CAIRN_ANSWER_API_KEY", "PGPASSWORD", "GITHUB_TOKEN")); print("environment checked")'],
        root, runner.workspace.git, 10, lambda: None, lambda _: None)
    assert code == 0 and output.strip() == 'environment checked'


def test_command_timeout_stops_before_delayed_write(coding: CodingFixture) -> None:
    runner, _, _, root = coding
    with pytest.raises(ApiProblem) as failure:
        run_command([sys.executable, '-c', 'import time; from pathlib import Path; time.sleep(2); Path("too-late.txt").touch()'],
            root, runner.workspace.git, 1, lambda: None, lambda _: None)
    assert failure.value.code == 'coding_command_timeout'
    assert not (root / 'too-late.txt').exists()


def test_multibyte_file_limit_rejects_model_write_before_touching_disk(coding: CodingFixture) -> None:
    _, _, _, root = coding
    run = start(coding, [step('write_file', path='large.py', content='#' + '文' * 12000, create=True)])
    assert wait_status(coding, run.id, {'failed'}).error_code == 'coding_invalid_response'
    assert not (root / 'large.py').exists()
