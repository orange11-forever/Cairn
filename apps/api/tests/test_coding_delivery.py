"""Delivery exercises real Git commits and refs; only GitHub HTTP is controlled."""

import errno
import json
import os
import threading
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from cairn_api.errors import ApiProblem
from cairn_api.workspace.coding import CodingRunner
from cairn_api.workspace.coding_delivery import CodingDelivery
from cairn_api.workspace.coding_schemas import CodingRun
from cairn_api.workspace.delivery_schemas import CommitRequest, PullRequestInput, PushRequest
from cairn_api.workspace.github import GitHubClient, GitHubToken
from cairn_api.workspace.schemas import GitHubAccount, GitHubRepository
from pydantic import SecretStr

from apps.api.tests.test_coding_parallel import approve, git, parallel, start_run, wait
from apps.api.tests.test_coding_runs import ScriptedModel, step

__all__ = ['parallel']
Fixture = tuple[CodingRunner, UUID, UUID, Path]


def completed(fixture: Fixture) -> tuple[CodingDelivery, UUID]:
    runner, user, project, _ = fixture
    run = start_run(runner, user, project)
    approve(runner, run)
    wait(runner, run, 'succeeded')
    return CodingDelivery(runner, user, project, run.id), run.id


def commit(delivery: CodingDelivery):
    review = delivery.review()
    return delivery.commit(CommitRequest(snapshot_id=review.snapshot_id,
        message='Fix value', author_name='Test Author', author_email='test@example.test'))


def test_commit_contains_exact_verified_files_and_preserves_main_and_other_agent(parallel: Fixture) -> None:
    runner, user, project, root = parallel
    delivery, run_id = completed(parallel)
    peer = start_run(runner, user, project, value=2)
    wait(runner, peer, 'awaiting_approval')
    before = git(root, 'rev-parse', 'HEAD')
    saved = commit(delivery)
    assert saved.delivery and saved.delivery.commit_sha
    target = Path(saved.local_path)
    assert git(target, 'show', 'HEAD:main.py') == 'value = 1'
    assert git(target, 'log', '-1', '--format=%an <%ae>') == 'Test Author <test@example.test>'
    assert git(target, 'diff', '--cached', '--name-only') == ''
    assert git(target, 'diff', '--name-only') == ''
    assert git(root, 'rev-parse', 'HEAD') == before
    assert (root / 'main.py').read_text() == 'value = 0\n'
    assert runner.get(user, project, peer.id).status == 'awaiting_approval'
    assert saved.id == run_id and saved.delivery.phase == 'committed'
    reopened = CodingRunner(runner.workspace)
    try:
        restored = reopened.get(user, project, run_id).delivery
        assert restored and restored.commit_sha == saved.delivery.commit_sha
    finally:
        reopened.close()


def test_changed_verified_source_or_external_staging_is_not_committed(parallel: Fixture) -> None:
    delivery, run_id = completed(parallel)
    runner, user, project, _ = parallel
    run = runner.get(user, project, run_id)
    review = delivery.review()
    target = Path(run.local_path)
    (target / 'main.py').write_text('unverified manual edit\n')
    with pytest.raises(ApiProblem) as rejected:
        delivery.commit(CommitRequest(snapshot_id=review.snapshot_id,
            message='Must not commit', author_name='Test', author_email='test@example.test'))
    assert rejected.value.code == 'coding_delivery_changed'
    assert git(target, 'rev-parse', 'HEAD') == run.base_head
    assert (target / 'main.py').read_text() == 'unverified manual edit\n'
    (target / 'main.py').write_text('value = 1\n')
    git(target, 'add', 'main.py')
    with pytest.raises(ApiProblem) as staged:
        commit(delivery)
    assert staged.value.code == 'coding_delivery_staged'
    assert git(target, 'diff', '--cached', '--name-only') == 'main.py'


class Remote:
    def __init__(self, base_sha: str):
        self.base_sha = base_sha
        self.branch_sha: str | None = None
        self.pull: dict[str, Any] | None = None
        self.created = 0
        self.lose_create_response = False
        self.can_push = True
        self.ancestor = True
        self.requests: list[httpx.Request] = []

    def request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == '/user':
            body: object = {'id': 7, 'login': 'test-owner'}
        elif path == '/repositories/11':
            body = {'id': 11, 'full_name': 'test-owner/fixture', 'private': True,
                'default_branch': 'main', 'permissions': {'pull': True, 'push': self.can_push}}
        elif '/branches/' in path:
            branch = path.split('/branches/', 1)[1]
            sha = self.base_sha if branch == 'main' else self.branch_sha
            if sha is None:
                return httpx.Response(404, json={'message': 'Not Found'})
            body = {'name': branch, 'commit': {'sha': sha}}
        elif '/compare/' in path:
            body = {'status': 'identical' if self.ancestor else 'diverged',
                    'merge_base_commit': {'sha': self.base_sha}}
        elif path.endswith('/pulls') and request.method == 'GET':
            body = [self.pull] if self.pull else []
        elif path.endswith('/pulls') and request.method == 'POST':
            data = json.loads(request.content)
            self.created += 1
            self.pull = {'number': 17, 'html_url': 'https://github.com/test-owner/fixture/pull/17',
                'state': 'open', 'draft': True, 'head': {'ref': data['head'], 'sha': self.branch_sha,
                'repo': {'id': 11}}, 'base': {'ref': data['base'], 'repo': {'id': 11}}}
            if self.lose_create_response:
                raise httpx.ReadTimeout('response lost')
            return httpx.Response(201, json=self.pull)
        else:
            raise AssertionError((request.method, str(request.url)))
        return httpx.Response(200, json=body)


def remote_for(parallel: Fixture, delivery: CodingDelivery) -> Remote:
    runner, user, project, root = parallel
    workspace = runner.workspace
    workspace.client_id = 'fixture-client'
    remote = Remote(git(root, 'rev-parse', 'HEAD'))
    workspace.github = GitHubClient('fixture-client', transport=httpx.MockTransport(remote.request))
    account = GitHubAccount(id=7, login='test-owner')
    workspace.connect(user, account, GitHubToken(access_token=SecretStr('fixture-token'), token_type='bearer', scope='repo'))
    git(root, 'remote', 'add', 'origin', 'https://github.com/test-owner/fixture.git')
    workspace.bind_local(user, project, str(root), GitHubRepository(id=11, full_name='test-owner/fixture',
        private=True, default_branch='main', can_push=True), account)
    return remote


def test_remote_target_must_have_permission_and_contain_original_base(parallel: Fixture) -> None:
    delivery, _ = completed(parallel)
    commit(delivery)
    remote = remote_for(parallel, delivery)
    remote.can_push = False
    with pytest.raises(ApiProblem) as denied:
        delivery.prepare_remote('main')
    assert denied.value.code == 'coding_push_forbidden'
    remote.can_push, remote.ancestor = True, False
    with pytest.raises(ApiProblem) as ancestry:
        delivery.prepare_remote('main')
    assert ancestry.value.code == 'coding_base_not_remote'
    assert not any(request.method == 'POST' for request in remote.requests)


def test_uncertain_pr_creation_is_reconciled_without_duplicate(parallel: Fixture, monkeypatch: pytest.MonkeyPatch) -> None:
    delivery, _ = completed(parallel)
    saved = commit(delivery)
    assert saved.delivery and saved.delivery.commit_sha and saved.branch
    sha, branch = saved.delivery.commit_sha, saved.branch
    remote = remote_for(parallel, delivery)
    plan = delivery.prepare_remote('main')
    workspace = parallel[0].workspace
    original = workspace.run_git

    def push(arguments: list[str], **kwargs: Any):
        if 'push' not in arguments:
            return original(arguments, **kwargs)
        assert arguments[-2] == 'https://github.com/test-owner/fixture.git'
        assert arguments[-1] == sha + ':refs/heads/' + branch
        assert '--force-with-lease=refs/heads/' + branch + ':' in arguments
        remote.branch_sha = sha
        return ''

    monkeypatch.setattr(workspace, 'run_git', push)
    delivery.push(PushRequest(target=plan, allow_push=True))
    remote.lose_create_response = True
    with pytest.raises(ApiProblem):
        delivery.create_pr(PullRequestInput(target=plan, title='Fix value', body='Checked in Cairn', allow_create=True))
    assert delivery.review().delivery.phase == 'pr_unknown'
    with pytest.raises(ApiProblem):
        delivery.create_pr(PullRequestInput(target=plan, title='Fix value', body='Checked in Cairn', allow_create=True))
    assert remote.created == 1
    reconciled = delivery.reconcile()
    assert reconciled.delivery
    assert reconciled.delivery.phase == 'pr_created'
    assert reconciled.delivery.pr_url == 'https://github.com/test-owner/fixture/pull/17'
    assert remote.created == 1


def test_delivery_is_scoped_to_run_owner(parallel: Fixture) -> None:
    _, run_id = completed(parallel)
    with pytest.raises(ApiProblem) as denied:
        CodingDelivery(parallel[0], uuid4(), parallel[2], run_id).review()
    assert denied.value.status_code == 404


def test_commit_recovers_after_ref_update_without_repeating_commit(parallel: Fixture, monkeypatch: pytest.MonkeyPatch) -> None:
    delivery, run_id = completed(parallel)
    original = os.replace

    def fail_index(source: str | Path, target: str | Path, **kwargs: Any) -> None:
        if str(source).endswith('index.lock'):
            raise OSError(errno.EACCES, 'fixture index rename failure')
        return original(source, target, **kwargs)

    monkeypatch.setattr(os, 'replace', fail_index)
    with pytest.raises(ApiProblem) as failed:
        commit(delivery)
    assert failed.value.code == 'coding_delivery_io_failed'
    state = delivery.review().delivery
    assert state.phase == 'commit_unknown' and state.commit_sha
    run = parallel[0].get(parallel[1], parallel[2], run_id)
    root = Path(run.local_path)
    assert git(root, 'rev-parse', 'HEAD') == state.commit_sha
    monkeypatch.setattr(os, 'replace', original)
    reconciled = delivery.reconcile()
    assert reconciled.delivery and reconciled.delivery.phase == 'committed'
    assert git(root, 'rev-list', '--count', 'HEAD') == '2'
    assert git(root, 'diff', '--cached', '--name-only') == ''


def test_existing_index_lock_is_preserved(parallel: Fixture) -> None:
    delivery, run_id = completed(parallel)
    run = parallel[0].get(parallel[1], parallel[2], run_id)
    root = Path(run.local_path)
    index = Path(git(root, 'rev-parse', '--path-format=absolute', '--git-path', 'index'))
    lock = index.with_name('index.lock')
    lock.write_bytes(b'owned by another Git operation')
    with pytest.raises(ApiProblem) as failed:
        commit(delivery)
    assert failed.value.code == 'coding_delivery_index_locked'
    with pytest.raises(ApiProblem):
        delivery.reconcile()
    assert lock.read_bytes() == b'owned by another Git operation'
    assert git(root, 'rev-parse', 'HEAD') == run.base_head


@pytest.mark.parametrize('setting', ['url.https://other.example/.insteadOf', 'http.sslVerify', 'credential.helper'])
def test_repository_network_overrides_are_rejected_before_push(parallel: Fixture, setting: str) -> None:
    delivery, _ = completed(parallel)
    commit(delivery)
    remote = remote_for(parallel, delivery)
    git(parallel[3], 'config', setting, 'false' if setting == 'http.sslVerify' else 'https://github.com/')
    with pytest.raises(ApiProblem) as failed:
        delivery.prepare_remote('main')
    assert failed.value.code == 'coding_git_network_config'
    assert remote.branch_sha is None and remote.created == 0


@pytest.mark.parametrize('race', [False, True])
def test_real_push_is_create_only_and_lost_response_requires_reconciliation(parallel: Fixture, monkeypatch: pytest.MonkeyPatch, race: bool) -> None:
    delivery, run_id = completed(parallel)
    saved = commit(delivery)
    assert saved.delivery and saved.delivery.commit_sha and saved.branch
    sha, branch = saved.delivery.commit_sha, saved.branch
    runner, _, _, root = parallel
    bare = root.parent / 'controlled-remote.git'
    git(root, 'init', '--bare', str(bare))
    git(root, 'push', str(bare), 'main:refs/heads/main')
    remote = remote_for(parallel, delivery)
    plan = delivery.prepare_remote('main')
    original = runner.workspace.run_git
    pushes = 0

    def network(arguments: list[str], **kwargs: Any):
        nonlocal pushes
        if 'push' not in arguments:
            return original(arguments, **kwargs)
        pushes += 1
        assert arguments[-2] == 'https://github.com/test-owner/fixture.git'
        if race:
            git(bare, 'update-ref', 'refs/heads/' + branch, remote.base_sha)
        local = [*arguments]; local[-2] = str(bare)
        try:
            original(['-c', 'protocol.file.allow=always', *local], **kwargs)
        finally:
            remote.branch_sha = git(bare, 'rev-parse', 'refs/heads/' + branch)
        raise ApiProblem(status_code=504, code='git_timeout', message='Push response lost')

    monkeypatch.setattr(runner.workspace, 'run_git', network)
    with pytest.raises(ApiProblem):
        delivery.push(PushRequest(target=plan, allow_push=True))
    assert delivery.review().delivery.phase == 'push_unknown'
    with pytest.raises(ApiProblem):
        delivery.push(PushRequest(target=plan, allow_push=True))
    assert pushes == 1
    if race:
        with pytest.raises(ApiProblem) as conflict:
            delivery.reconcile()
        assert conflict.value.code == 'coding_remote_branch_conflict'
        assert git(bare, 'rev-parse', 'refs/heads/' + branch) == remote.base_sha
    else:
        result = delivery.reconcile()
        assert result.delivery and result.delivery.phase == 'pushed'
        assert git(bare, 'show', sha + ':main.py') == 'value = 1'
    assert git(bare, 'rev-parse', 'main') == remote.base_sha
    assert git(bare, 'tag') == ''
    assert runner.get(parallel[1], parallel[2], run_id).status == 'succeeded'


def test_crlf_working_file_is_committed_with_git_line_ending_rules(parallel: Fixture) -> None:
    import sys
    runner, user, project, root = parallel
    (root / '.gitattributes').write_text('*.py text eol=crlf\n')
    git(root, 'add', '.gitattributes')
    git(root, '-c', 'user.name=Test', '-c', 'user.email=test@example.test', 'commit', '-m', 'line endings')
    run = start_run(runner, user, project, provider=ScriptedModel([
        step('read_file', path='main.py'),
        step('write_file', path='main.py', content='value = 1\r\n', create=False),
        step('run_command', argv=[sys.executable, '-c', 'from main import value; assert value == 1'], purpose='test', timeout_seconds=10),
        step('finish', summary='Checked CRLF source'),
    ]))
    approve(runner, run); wait(runner, run, 'succeeded')
    result = commit(CodingDelivery(runner, user, project, run.id))
    target = Path(result.local_path)
    assert (target / 'main.py').read_bytes() == b'value = 1\r\n'
    assert runner.workspace.read_git(target, ['show', 'HEAD:main.py']) == b'value = 1\n'
    assert git(target, 'diff', '--name-only') == ''


def test_branch_ref_replacement_cannot_redirect_commit_to_main(parallel: Fixture, monkeypatch: pytest.MonkeyPatch) -> None:
    delivery, run_id = completed(parallel)
    runner, user, project, main = parallel
    run = runner.get(user, project, run_id)
    original = runner.workspace.run_git

    def swap_ref(arguments: list[str], **kwargs: Any):
        if 'update-ref' in arguments:
            git(main, 'symbolic-ref', 'refs/heads/' + str(run.branch), 'refs/heads/main')
        return original(arguments, **kwargs)

    monkeypatch.setattr(runner.workspace, 'run_git', swap_ref)
    result = commit(delivery)
    assert git(main, 'rev-parse', 'main') == run.base_head
    assert result.delivery and result.delivery.commit_sha == git(Path(run.local_path), 'rev-parse', 'HEAD')


def test_suggested_pr_reserves_actual_approved_verification_for_long_narratives(parallel: Fixture) -> None:
    delivery, run_id = completed(parallel)
    run = parallel[0].runs[run_id]
    run.task = 'Long task description ' * 280
    run.summary = 'Model narrative ' * 250
    review = delivery.review()
    assert 'assert value == 1' in review.suggested_body
    assert '用户批准了此命令并确认其用于验证任务' in review.suggested_body
    assert '测试退出码：0' in review.suggested_body
    assert len(review.suggested_body) <= 12000
    assert '节选' in review.suggested_body


def test_delivery_waits_for_worker_to_release_its_journal_after_finish_error(parallel: Fixture, monkeypatch: pytest.MonkeyPatch) -> None:
    runner, user, project, _ = parallel
    entered, release = threading.Event(), threading.Event()
    original_save, original_failure = runner._save, runner._finish_failure  # pyright: ignore[reportPrivateUsage]
    failed_once = False

    def fail_finish(run: CodingRun) -> None:
        nonlocal failed_once
        if run.status == 'succeeded' and not failed_once:
            failed_once = True
            raise ApiProblem(status_code=503, code='coding_storage_failed', message='fixture finish persistence failed')
        original_save(run)

    def delayed_failure(run: CodingRun, status: str, code: str | None, message: str) -> None:
        entered.set()
        assert release.wait(10)
        original_failure(run, status, code, message)

    monkeypatch.setattr(runner, '_save', fail_finish)
    monkeypatch.setattr(runner, '_finish_failure', delayed_failure)
    run = start_run(runner, user, project)
    approve(runner, run)
    try:
        assert entered.wait(5)
        service = CodingDelivery(runner, user, project, run.id)
        with pytest.raises(ApiProblem) as busy:
            commit(service)
        assert busy.value.code == 'coding_delivery_busy'
        assert git(Path(run.local_path), 'rev-parse', 'HEAD') == run.base_head
    finally:
        release.set()
