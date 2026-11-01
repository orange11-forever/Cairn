"""Real Git/workers: isolation, scheduling and result retention, without a cloud model."""

import base64
import json
import shutil
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
from cairn_api.workspace.coding_schemas import CodingRun, CodingStart, CodingStep, CommandDecision
from cairn_api.workspace.editor import RepositoryEditor
from cairn_api.workspace.local import DesktopWorkspace

from apps.api.tests.test_coding_runs import ScriptedModel, step


def git(root: Path, *args: str) -> str:
    return subprocess.run([shutil.which('git') or 'git', '-C', str(root), *args],
                          check=True, capture_output=True, text=True, encoding='utf-8').stdout.strip()


@pytest.fixture
def parallel(tmp_path: Path) -> Iterator[tuple[CodingRunner, UUID, UUID, Path]]:
    root, data = tmp_path / '代码仓库', tmp_path / 'data'
    root.mkdir(); data.mkdir()
    git(root, 'init', '-b', 'main')
    (root / 'main.py').write_text('value = 0\n')
    git(root, 'add', 'main.py')
    git(root, '-c', 'user.name=Test', '-c', 'user.email=test@example.test', 'commit', '-m', 'baseline')
    workspace = DesktopWorkspace(data, Path(shutil.which('git') or 'git'), None, base64.b64encode, base64.b64decode)
    user, project = uuid4(), uuid4()
    workspace.bind_local(user, project, str(root))
    runner = CodingRunner(workspace)
    yield runner, user, project, root
    runner.close()


def start_run(runner: CodingRunner, user: UUID, project: UUID, *, agent: UUID | None = None,
              depends_on: UUID | None = None, value: int = 1, provider: ScriptedModel | None = None) -> CodingRun:
    return runner.start(user, project, CodingStart(
        workspace_id=RepositoryEditor(runner.workspace, user, project).tree().workspace_id,
        task=f'Change value to {value}', assistant_id=agent or uuid4(), assistant_revision=0,
        depends_on=depends_on, allow_writes=True,
    ), assistant_name=f'Agent {value}', model=AnswerModelOption(
        id='default', name='Test model', model='fixture', protocol='openai-compatible'),
        provider=provider or ScriptedModel([
            step('read_file', path='main.py'),
            step('write_file', path='main.py', content=f'value = {value}\n', create=False),
            step('run_command', argv=[sys.executable, '-c', f'from main import value; assert value == {value}'], purpose='test', timeout_seconds=10),
            step('finish', summary=f'Checked value {value}'),
        ]), guidance=None, authorize=lambda: None)


def wait(runner: CodingRunner, run: CodingRun, status: str) -> CodingRun:
    deadline = time.monotonic() + 10
    current = run
    while time.monotonic() < deadline:
        current = runner.get(run.user_id, run.project_id, run.id)
        if current.status == status:
            return current
        assert current.status not in {'failed', 'blocked', 'cancelled'}, current
        time.sleep(0.02)
    pytest.fail(f'Expected {status}, got {current}')


def approve(runner: CodingRunner, run: CodingRun) -> None:
    current = wait(runner, run, 'awaiting_approval')
    assert current.pending_command
    runner.decide(run.user_id, run.project_id, run.id, CommandDecision(
        event_id=current.pending_command.event_id, approved=True, verify=True))


def test_same_project_agents_keep_separate_branches_changes_and_cancellation(parallel: tuple[CodingRunner, UUID, UUID, Path]) -> None:
    runner, user, project, root = parallel
    first = start_run(runner, user, project, value=1)
    second = start_run(runner, user, project, value=2)
    a, b = wait(runner, first, 'awaiting_approval'), wait(runner, second, 'awaiting_approval')
    assert a.local_path != b.local_path and a.branch != b.branch
    assert git(Path(a.local_path), 'branch', '--show-current') == a.branch
    assert git(Path(b.local_path), 'branch', '--show-current') == b.branch
    assert (root / 'main.py').read_text() == 'value = 0\n'
    assert (Path(a.local_path) / 'main.py').read_text() == 'value = 1\n'
    assert (Path(b.local_path) / 'main.py').read_text() == 'value = 2\n'
    assert [(item.run_id, item.paths) for item in runner.get(user, project, a.id).overlaps] == [(b.id, ['main.py'])]
    runner.cancel(user, project, first.id)
    wait(runner, first, 'cancelled')
    assert runner.get(user, project, second.id).status == 'awaiting_approval'
    approve(runner, second)
    wait(runner, second, 'succeeded')
    assert Path(a.local_path).is_dir() and Path(b.local_path).is_dir()
    assert git(root, 'status', '--porcelain') == ''


def test_capacity_is_shared_across_projects_and_cancelling_queued_task_does_not_start_it(parallel: tuple[CodingRunner, UUID, UUID, Path]) -> None:
    runner, user, project, root = parallel
    other = uuid4()
    runner.workspace.bind_local(user, other, str(root))
    first = start_run(runner, user, project)
    second = start_run(runner, user, other, value=2)
    wait(runner, first, 'awaiting_approval'); wait(runner, second, 'awaiting_approval')
    queued = start_run(runner, user, project, value=3)
    assert queued.status == 'queued' and not Path(queued.local_path).exists()
    next_run = start_run(runner, user, other, value=4)
    runner.cancel(user, project, queued.id)
    assert runner.get(user, project, queued.id).status == 'cancelled'
    runner.cancel(user, project, first.id)
    wait(runner, next_run, 'awaiting_approval')
    assert not Path(queued.local_path).exists()
    assert runner.get(user, other, second.id).status == 'awaiting_approval'


def test_dependency_waits_without_using_slot_and_failure_blocks_only_dependents(parallel: tuple[CodingRunner, UUID, UUID, Path]) -> None:
    runner, user, project, _ = parallel
    first = start_run(runner, user, project)
    dependent = start_run(runner, user, project, depends_on=first.id)
    independent = start_run(runner, user, project, value=3)
    wait(runner, independent, 'awaiting_approval')
    assert runner.get(user, project, dependent.id).status == 'queued'
    runner.cancel(user, project, first.id)
    blocked = wait(runner, dependent, 'blocked')
    assert blocked.error_code == 'coding_dependency_failed' and not Path(blocked.local_path).exists()
    assert runner.get(user, project, independent.id).status == 'awaiting_approval'


def test_successful_dependency_exposes_results_and_same_agent_runs_serially(parallel: tuple[CodingRunner, UUID, UUID, Path]) -> None:
    runner, user, project, _ = parallel
    agent = uuid4()
    captured: list[dict[str, object]] = []

    class RecordingModel(ScriptedModel):
        def coding_step(self, *, context: dict[str, object], check_cancelled: Callable[[], None]) -> CodingStep:
            captured.append(context)
            return super().coding_step(context=context, check_cancelled=check_cancelled)

    first = start_run(runner, user, project, agent=agent)
    same_agent = start_run(runner, user, project, agent=agent, value=2)
    dependent = start_run(runner, user, project, depends_on=first.id, provider=RecordingModel([
        step('run_command', argv=[sys.executable, '-c', 'assert 1 == 1'], purpose='test', timeout_seconds=10),
    ]))
    assert same_agent.status == 'queued' and not captured
    approve(runner, first)
    wait(runner, first, 'succeeded')
    wait(runner, same_agent, 'awaiting_approval'); wait(runner, dependent, 'awaiting_approval')
    dependency = json.loads(json.dumps(captured[0]['dependency']))
    assert dependency['summary'] == 'Checked value 1'
    assert dependency['changes'][0]['after'] == 'value = 1\n'


def test_dirty_main_files_stay_in_place_and_worktree_checkout_never_runs_filters(parallel: tuple[CodingRunner, UUID, UUID, Path]) -> None:
    runner, user, project, root = parallel
    (root / '.gitattributes').write_text('*.py filter=probe\n')
    git(root, 'add', '.gitattributes')
    git(root, '-c', 'user.name=Test', '-c', 'user.email=test@example.test', 'commit', '-m', 'attributes')
    marker = root.parent / 'filter-executed'
    git(root, 'config', 'filter.probe.smudge', f'touch "{marker}"; cat')
    git(root, 'config', 'filter.probe.required', 'true')
    (root / 'main.py').write_text('manual unsaved to Git\n')
    with pytest.raises(ApiProblem) as rejected:
        start_run(runner, user, project)
    assert rejected.value.code == 'coding_git_filter_unsupported'
    assert not marker.exists()
    git(root, 'config', '--remove-section', 'filter.probe')
    run = start_run(runner, user, project)
    current = wait(runner, run, 'awaiting_approval')
    assert current.changes[0].before == 'value = 0\n'
    assert (root / 'main.py').read_text() == 'manual unsaved to Git\n'



def test_restart_interrupts_queue_and_preserves_existing_worktree(parallel: tuple[CodingRunner, UUID, UUID, Path]) -> None:
    runner, user, project, _ = parallel
    first = start_run(runner, user, project)
    active = wait(runner, first, 'awaiting_approval')
    queued = start_run(runner, user, project, depends_on=first.id)
    runner.close()
    # Restore the durable snapshots from before exit to simulate an abrupt crash.
    for run in (active, queued):
        (runner.directory / f'{run.id}.dpapi').write_bytes(runner.workspace.protect(run.model_dump_json().encode()))
    reopened = CodingRunner(runner.workspace)
    try:
        for run in (active, queued):
            assert reopened.get(user, project, run.id).status == 'interrupted'
        assert (Path(active.local_path) / 'main.py').read_text() == 'value = 1\n'
        assert not Path(queued.local_path).exists()
    finally:
        reopened.close()


def test_dependency_cannot_reference_another_users_or_projects_run(parallel: tuple[CodingRunner, UUID, UUID, Path]) -> None:
    runner, user, project, root = parallel
    first = start_run(runner, user, project)
    other = uuid4()
    runner.workspace.bind_local(user, other, str(root))
    with pytest.raises(ApiProblem) as rejected:
        start_run(runner, user, other, depends_on=first.id)
    assert rejected.value.status_code == 404


def test_concurrency_changes_affect_queue_without_cancelling_existing_workers(parallel: tuple[CodingRunner, UUID, UUID, Path]) -> None:
    runner, user, project, _ = parallel
    runner.set_concurrency(1)
    first = start_run(runner, user, project)
    wait(runner, first, 'awaiting_approval')
    second = start_run(runner, user, project, value=2)
    assert second.status == 'queued'
    runner.set_concurrency(2)
    wait(runner, second, 'awaiting_approval')
    runner.set_concurrency(1)
    third = start_run(runner, user, project, value=3)
    runner.cancel(user, project, first.id)
    wait(runner, first, 'cancelled')
    assert runner.get(user, project, third.id).status == 'queued'
    assert runner.get(user, project, second.id).status == 'awaiting_approval'
    runner.cancel(user, project, second.id)
    wait(runner, third, 'awaiting_approval')


def test_missing_commit_is_rejected_before_allocating_a_worktree(parallel: tuple[CodingRunner, UUID, UUID, Path], tmp_path: Path) -> None:
    runner, user, _, _ = parallel
    root, project = tmp_path / 'empty', uuid4()
    root.mkdir()
    git(root, 'init', '-b', 'main')
    (root / 'main.py').write_text('uncommitted code')
    runner.workspace.bind_local(user, project, str(root))
    with pytest.raises(ApiProblem) as rejected:
        start_run(runner, user, project)
    assert rejected.value.code == 'coding_commit_required'
    assert not (tmp_path / 'empty.cairn-worktrees').exists()
    assert (root / 'main.py').read_text() == 'uncommitted code'


def test_branch_conditional_filter_cannot_execute_during_worktree_creation(parallel: tuple[CodingRunner, UUID, UUID, Path]) -> None:
    runner, user, project, root = parallel
    (root / '.gitattributes').write_text('*.py filter=probe\n')
    git(root, 'add', '.gitattributes')
    git(root, '-c', 'user.name=Test', '-c', 'user.email=test@example.test', 'commit', '-m', 'attributes')
    marker = root.parent / 'conditional-filter-executed'
    config = root.parent / 'conditional-config'
    config.write_text('[filter "probe"]\n    smudge = touch "' + str(marker) + '"; cat\n')
    git(root, 'config', 'includeIf.onbranch:cairn/**.path', str(config))
    run = start_run(runner, user, project)
    current = wait(runner, run, 'failed')
    assert current.error_code == 'coding_git_filter_unsupported'
    assert not marker.exists()
    assert (Path(run.local_path) / '.git').exists()
    assert (root / 'main.py').read_text() == 'value = 0\n'
