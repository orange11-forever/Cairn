"""Explicit commit, create-only push, draft PR and reconciliation of uncertain writes."""

import hashlib
import json
import os
import tempfile
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

from cairn_api.errors import ApiProblem
from cairn_api.workspace.architecture import eligible_source
from cairn_api.workspace.coding import CodingRunner, sanitize
from cairn_api.workspace.coding_process import problem
from cairn_api.workspace.coding_schemas import CodingRun
from cairn_api.workspace.coding_worktree import WorktreeEditor, require_plain_git
from cairn_api.workspace.delivery_schemas import (
    CodingDeliveryState,
    CommitRequest,
    DeliveryReview,
    PullRequestInput,
    PushRequest,
    RemoteTarget,
)
from cairn_api.workspace.editor import read_file_bytes
from cairn_api.workspace.github import GitHubClient, RemotePullRequest


class CodingDelivery:
    def __init__(self, runner: CodingRunner, user: UUID, project: UUID, run_id: UUID,
                 *, authorize: Callable[[], None] = lambda: None):
        self.runner, self.workspace = runner, runner.workspace
        self.user, self.project, self.run_id = user, project, run_id
        self.authorize = authorize

    def _run(self) -> CodingRun:
        run = self.runner.get(self.user, self.project, self.run_id)
        if run.status != 'succeeded' or not run.base_head or run.branch != f'cairn/agent-{run.id}':
            raise problem('coding_delivery_unverified', '仅支持已完成验证的独立工作区任务；旧版原目录记录和未成功任务仍可查看。')
        return run

    @contextmanager
    def _operation(self) -> Generator[CodingRun]:
        with self.workspace.lock:
            run = self._run()
            if self.runner.closed:
                raise problem('coding_runtime_stopped', '编程执行服务正在关闭')
            if run.id in self.runner.delivering or run.id in self.runner.executions:
                raise problem('coding_delivery_busy', '此任务仍在收尾，或已有提交/远端操作，请稍后刷新状态。')
            self.runner.delivering.add(run.id)
        try:
            self.authorize()
            yield run
        except OSError as error:
            raise problem('coding_delivery_io_failed', f'文件或 Git 数据写入失败：{error.strerror or type(error).__name__}；文件保留，请核对状态。') from None
        finally:
            with self.workspace.lock:
                self.runner.delivering.discard(run.id)

    def _save(self, state: CodingDeliveryState) -> CodingRun:
        return self.runner.save_delivery(self.run_id, state)

    def _git(self, root: Path, arguments: list[str], *, index: Path | None = None, data: bytes | None = None) -> str:
        result = self.workspace.run_git(['-C', str(root), *arguments], index=index, input_data=data)
        assert result is not None
        return result

    def _snapshot(self, run: CodingRun, state: CodingDeliveryState) -> tuple[str, dict[str, tuple[str, bytes | None]], list[str]]:
        expected = state.commit_sha if state.phase != 'uncommitted' else run.base_head
        editor = WorktreeEditor(self.workspace, run, expected_head=expected)
        root, _, _, _ = editor.context()
        require_plain_git(self.workspace, root)
        if state.phase == 'uncommitted' and self._git(root, ['diff', '--cached', '--name-only']):
            raise problem('coding_delivery_staged', '任务目录已有暂存内容，请先在外部核对并取消暂存；内容不会被覆盖。')
        flags = self.workspace.read_git(root, ['ls-files', '-v', '-z'])
        if any(item[:1] != b'H' for item in flags.split(b'\0') if item):
            raise problem('coding_delivery_index_unsupported', '任务暂存区含跳过检查或特殊标记，请先在外部核对；未提交。')
        recorded = {item.path: item for item in run.changes}
        excluded: list[str] = []
        for change in editor.changes().files:
            if change.status == '??' and not eligible_source(change.path):
                excluded.append(change.path)
                continue
            if state.phase != 'uncommitted' or change.path not in recorded:
                raise problem('coding_delivery_changed', f'验证后出现额外改动：{change.path}；请重新验证，未提交或推送。')
        files: dict[str, tuple[str, bytes | None]] = {}
        for path, change in recorded.items():
            try:
                raw, _ = read_file_bytes(root, path)
            except ApiProblem as error:
                if error.code != 'workspace_file_missing':
                    raise
                raw = None
            if (hashlib.sha256(raw).hexdigest() if raw is not None else None) != change.revision:
                raise problem('coding_delivery_changed', f'验证后文件已变化：{path}；已保留内容，请重新验证。')
            entry = self.workspace.read_git(root, ['ls-tree', '-z', run.base_head or '', '--', path])
            mode = entry.split(b' ', 1)[0].decode('ascii') if entry else '100644'
            if mode not in {'100644', '100755'}:
                raise problem('coding_delivery_file_unsupported', f'不支持提交此 Git 文件类型：{path}')
            # A mode-only change was not part of the runner's content verification.
            diff = self.workspace.read_git(root, ['diff', '--raw', '--no-ext-diff', '--no-textconv', '--', path])
            if raw is not None and diff and diff.split()[0][1:] != diff.split()[1]:
                raise problem('coding_delivery_mode_changed', f'文件权限发生变化：{path}；请先核对并重新验证。')
            files[path] = mode, raw
        digest = hashlib.sha256(json.dumps([str(run.id), run.base_head, run.branch,
            [(path, mode, hashlib.sha256(raw).hexdigest() if raw is not None else None)
             for path, (mode, raw) in sorted(files.items())]], ensure_ascii=False).encode()).hexdigest()
        return digest, files, excluded

    def review(self) -> DeliveryReview:
        run = self._run()
        state = run.delivery or CodingDeliveryState()
        if state.phase in {'committing', 'commit_unknown', 'pushing', 'push_unknown', 'creating_pr', 'pr_unknown'}:
            digest, excluded = state.snapshot_id or '0' * 64, []
        else:
            digest, _, excluded = self._snapshot(run, state)
        title = sanitize(run.task.splitlines()[0])[:200]

        def excerpt(value: str, limit: int) -> str:
            clean = sanitize(value)
            return clean if len(clean) <= limit else clean[:limit] + '\n（节选；完整内容见 Cairn 运行记录）'

        result = next((item for item in reversed(run.events) if item.kind == 'command_result'), None)
        approvals = [item for item in run.events if item.kind == 'approval' and result and item.id < result.id][-2:]
        evidence = '\n'.join(excerpt(item.message, 2500) for item in approvals)
        if result:
            evidence += f'\n{result.at.isoformat()} · {excerpt(result.message, 300)}'
        # Reserve bounded space for the actual final approved check, before the
        # optional narrative/file inventory. Indented code keeps argv literal.
        checks = '\n'.join('    ' + line for line in evidence.split('\n'))
        body = f'## 任务\n{excerpt(run.task, 2000)}\n\n## 本地验证\n{checks}\n'
        body += '\n## 修改文件\n' + excerpt('\n'.join('- `' + item.path + '`' for item in run.changes), 2500)
        body += f'\n\n## 结果说明\n{excerpt(run.summary or "", 1000)}\n\nCairn 运行：{run.id}\n完成状态对应上述用户确认的检查退出码 0；未执行合并后的验证。'
        return DeliveryReview(snapshot_id=digest, files=[item.path for item in run.changes], excluded_paths=excluded,
            suggested_message=title, suggested_title=title, suggested_body=body, delivery=state)

    def _index_path(self, root: Path) -> Path:
        path = Path(self._git(root, ['rev-parse', '--path-format=absolute', '--git-path', 'index']))
        if path.is_symlink() or path.is_junction() or (path.exists() and path.stat().st_nlink != 1):
            raise problem('coding_delivery_index_unsafe', 'Git 暂存区为链接，未修改；请检查任务仓库。')
        return path

    def commit(self, payload: CommitRequest) -> CodingRun:
        with self._operation() as run:
            state = run.delivery or CodingDeliveryState()
            if state.phase != 'uncommitted':
                raise problem('coding_delivery_state_changed', '已有提交或结果待核对，请刷新；不会重复提交。')
            if sanitize(payload.message) != payload.message:
                raise problem('coding_delivery_sensitive', '提交说明含疑似凭据，请修改后再提交。')
            digest, files, _ = self._snapshot(run, state)
            if digest != payload.snapshot_id:
                raise problem('coding_delivery_changed', '待提交快照已变化，请重新审阅。')
            root = Path(run.local_path)
            index = self._index_path(root)
            lock = index.with_name(index.name + '.lock')
            with tempfile.TemporaryDirectory(dir=self.workspace.data, prefix='.commit-') as temporary:
                prepared = Path(temporary) / 'index'
                self._git(root, ['read-tree', run.base_head or ''], index=prepared)
                entries: list[str] = []
                for path, (mode, raw) in files.items():
                    oid = self._git(root, ['hash-object', '-w', '--stdin', '--path=' + path], data=raw) if raw is not None else '0' * len(run.base_head or '')
                    entries.append(f'{mode if raw is not None else "0"} {oid}\t{path}\0')
                self._git(root, ['update-index', '-z', '--index-info'], index=prepared, data=''.join(entries).encode())
                tree = self._git(root, ['write-tree'], index=prepared)
                if tree == self._git(root, ['rev-parse', (run.base_head or '') + '^{tree}']):
                    raise problem('coding_delivery_empty', '此运行没有可提交的有效源码差异。')
                sha = self._git(root, ['-c', 'commit.gpgSign=false', '-c', 'user.name=' + payload.author_name,
                    '-c', 'user.email=' + str(payload.author_email), 'commit-tree', tree, '-p', run.base_head or '', '-F', '-'],
                    data=(payload.message + '\n\nCairn-Run: ' + str(run.id) + '\n').encode())
                prepared_bytes = prepared.read_bytes()
                state = CodingDeliveryState(phase='committing', snapshot_id=digest, commit_sha=sha, tree_sha=tree,
                    index_digest=hashlib.sha256(prepared_bytes).hexdigest(), message=payload.message,
                    author_name=payload.author_name, author_email=str(payload.author_email))
                self._save(state)  # Durable intent precedes the branch update.
                owned, may_have_updated = False, False
                try:
                    with lock.open('xb') as stream:
                        owned = True
                        stream.write(prepared_bytes); stream.flush(); os.fsync(stream.fileno())
                    self.authorize()
                    self._snapshot(run, CodingDeliveryState())
                    may_have_updated = True
                    self._git(root, ['update-ref', '--no-deref', 'refs/heads/' + (run.branch or ''), sha, run.base_head or ''])
                    os.replace(lock, index)
                    owned = False
                    state.phase = 'committed'
                    return self._save(state)
                except (ApiProblem, OSError) as error:
                    state.phase, state.error = 'commit_unknown', '提交未完成或结果待核对；工作区已保留，请先核对状态。'
                    self._save(state)
                    if isinstance(error, FileExistsError):
                        raise problem('coding_delivery_index_locked', 'Git 暂存区已被占用；未覆盖，请结束其他 Git 操作后核对状态。') from None
                    raise
                finally:
                    if owned and not may_have_updated:
                        lock.unlink(missing_ok=True)

    def _remote(self, run: CodingRun, base_branch: str) -> tuple[GitHubClient, str, RemoteTarget]:
        state = run.delivery
        if state is None or state.commit_sha is None:
            raise problem('coding_commit_required', '请先创建本次任务的本地提交。')
        self._snapshot(run, state)
        root = Path(run.local_path)
        self._git(root, ['check-ref-format', 'refs/heads/' + base_branch])
        binding = self.workspace.binding(self.user, self.project)
        if binding is None or binding.repository is None or binding.account is None or binding.local_path != run.repository_path:
            raise problem('coding_remote_not_bound', '请将此项目关联到该本地仓库对应的 GitHub 仓库并授权后再继续。')
        credential = self.workspace.token(self.user)
        github = self.workspace.github
        if github is None:
            raise problem('github_not_configured', '尚未配置 GitHub 授权应用。')
        token = credential.token.get_secret_value()
        account = github.account(token)
        repository = github.repository(token, binding.repository.id)
        if account.id != binding.account.id or account.id != credential.account.id or repository.full_name != binding.repository.full_name:
            raise problem('coding_remote_changed', 'GitHub 账号或仓库标识已变化，请重新关联并核对目标。')
        if not repository.can_push:
            raise ApiProblem(status_code=403, code='coding_push_forbidden', message='当前 GitHub 授权没有此仓库的写入权限。')
        self.workspace.verify_remote(Path(run.repository_path or ''), repository)
        worktree_config = self.workspace.run_git(['-C', str(root), 'config', '--bool', '--get', 'extensions.worktreeConfig'], allow_one=True)
        scopes = ('--local', '--worktree') if worktree_config == 'true' else ('--local',)
        for scope in scopes:
            if self.workspace.run_git(['-C', str(root), 'config', scope, '--includes', '--name-only', '--get-regexp', r'^(url\.|http\.|credential\.)'], allow_one=True):
                raise problem('coding_git_network_config', '仓库配置了 HTTP、凭据或 URL 覆盖项，可能改变推送账号或目标；请先在外部核对，未推送。')
        base_sha = github.branch(token, repository.full_name, base_branch)
        if base_sha is None:
            raise problem('coding_base_missing', '目标 GitHub 基础分支不存在，请核对分支名。')
        if not github.contains_base(token, repository.full_name, run.base_head or '', base_sha):
            raise problem('coding_base_not_remote', '本次任务基准不在目标分支历史中，可能包含额外本地提交；未推送，请从目标分支重新开始。')
        target = RemoteTarget(repository_id=repository.id, full_name=repository.full_name, private=repository.private,
            account_id=account.id, account_login=account.login, base_branch=base_branch, base_sha=base_sha,
            head_branch=run.branch or '', head_sha=state.commit_sha)
        if state.target and (state.target.repository_id, state.target.full_name, state.target.account_id, state.target.base_branch) != (target.repository_id, target.full_name, target.account_id, target.base_branch):
            raise problem('coding_remote_changed', '此提交已有远端操作记录，不能改用其他仓库、账号或基础分支。')
        return github, token, target

    def prepare_remote(self, base_branch: str) -> RemoteTarget:
        with self._operation() as run:
            return self._remote(run, base_branch)[2]

    def push(self, payload: PushRequest) -> CodingRun:
        with self._operation() as run:
            state = run.delivery
            if state is None or state.phase != 'committed':
                raise problem('coding_delivery_state_changed', '请先提交或核对上次推送结果，不会重复推送。')
            github, token, target = self._remote(run, payload.target.base_branch)
            if target != payload.target:
                raise problem('coding_remote_changed', '远端目标或基础提交已变化，请重新核对后再授权推送。')
            current = github.branch(token, target.full_name, target.head_branch)
            if current is not None and current != target.head_sha:
                raise problem('coding_remote_branch_conflict', '远端同名分支含其他提交，未覆盖；本地成果已保留。')
            state.target, state.error = target, None
            if current == target.head_sha:
                state.phase = 'pushed'
                return self._save(state)
            state.phase = 'pushing'
            self._save(state)
            try:
                self.authorize()
                self.workspace.run_git(['-C', run.local_path, '-c', 'push.followTags=false', '-c', 'push.gpgSign=false',
                    'push', '--porcelain', '--no-verify', '--no-follow-tags', '--recurse-submodules=no',
                    '--force-with-lease=refs/heads/' + target.head_branch + ':',
                    'https://github.com/' + target.full_name + '.git', target.head_sha + ':refs/heads/' + target.head_branch],
                    token=token, timeout=120)
                if github.branch(token, target.full_name, target.head_branch) != target.head_sha:
                    raise problem('coding_push_unconfirmed', '推送后尚未确认远端提交，请先核对结果。')
                state.phase = 'pushed'
                return self._save(state)
            except ApiProblem as error:
                state.phase, state.error = 'push_unknown', error.message + '。请先核对远端状态，不会自动重推。'
                self._save(state)
                raise

    def _save_pr(self, state: CodingDeliveryState, pr: RemotePullRequest) -> CodingRun:
        state.phase, state.error = 'pr_created', None
        state.pr_number, state.pr_url, state.pr_state = pr.number, pr.html_url, pr.state
        state.pr_draft = pr.draft
        return self._save(state)

    def create_pr(self, payload: PullRequestInput) -> CodingRun:
        with self._operation() as run:
            state = run.delivery
            if state is None or state.phase != 'pushed':
                raise problem('coding_delivery_state_changed', '请先确认推送或核对已有 PR，不会重复创建。')
            if sanitize(payload.title) != payload.title or sanitize(payload.body) != payload.body:
                raise problem('coding_delivery_sensitive', 'PR 内容含疑似凭据，请修改后再创建。')
            github, token, target = self._remote(run, payload.target.base_branch)
            if target != payload.target or github.branch(token, target.full_name, target.head_branch) != target.head_sha:
                raise problem('coding_remote_changed', '远端分支已变化，请重新核对；未创建 PR。')
            existing = github.find_pull(token, target.full_name, target.repository_id, target.head_branch, target.base_branch, target.head_sha)
            if existing:
                return self._save_pr(state, existing)
            state.phase, state.target, state.error = 'creating_pr', target, None
            self._save(state)
            try:
                self.authorize()
                pr = github.create_pull(token, target.full_name, target.repository_id, target.head_branch,
                    target.base_branch, target.head_sha, payload.title, payload.body, payload.draft)
                return self._save_pr(state, pr)
            except ApiProblem as error:
                state.phase, state.error = 'pr_unknown', error.message + '。请先核对远端 PR，不会自动重复创建。'
                self._save(state)
                raise

    def reconcile(self) -> CodingRun:
        with self._operation() as run:
            state = run.delivery
            if state is None:
                return run
            if state.phase in {'committing', 'commit_unknown'}:
                root, branch = self.workspace.inspect(run.local_path)
                head = self.workspace.head(root)
                if branch != run.branch or head not in {run.base_head, state.commit_sha}:
                    raise problem('coding_delivery_changed', '任务分支已被外部修改，未修复或覆盖暂存区，请人工核对。')
                index = self._index_path(root)
                lock = index.with_name(index.name + '.lock')
                if lock.exists():
                    if lock.is_symlink() or lock.stat().st_nlink != 1 or hashlib.sha256(lock.read_bytes()).hexdigest() != state.index_digest:
                        raise problem('coding_delivery_index_locked', 'Git 锁文件不属于此提交，已保留，请先核对其他 Git 操作。')
                    if head == state.commit_sha:
                        os.replace(lock, index)
                    else:
                        lock.unlink()
                if head == state.commit_sha:
                    if self._git(root, ['diff', '--cached', '--name-only']):
                        raise problem('coding_delivery_staged', '提交存在但暂存区不同，请人工核对，未覆盖。')
                    state.phase, state.error = 'committed', None
                else:
                    state = CodingDeliveryState(error='已确认分支未提交，可重新审阅后提交。')
                return self._save(state)
            if state.target and state.phase in {'pushing', 'push_unknown', 'creating_pr', 'pr_unknown', 'pushed'}:
                github, token, target = self._remote(run, state.target.base_branch)
                remote = github.branch(token, target.full_name, target.head_branch)
                if remote is not None and remote != target.head_sha:
                    raise problem('coding_remote_branch_conflict', '远端分支含其他提交，已保留所有成果；不会覆盖。')
                if state.phase in {'creating_pr', 'pr_unknown'}:
                    existing = github.find_pull(token, target.full_name, target.repository_id, target.head_branch, target.base_branch, target.head_sha)
                    if existing:
                        return self._save_pr(state, existing)
                state.target, state.error = target, '已核对远端状态；如需继续，请再次明确确认操作。'
                state.phase = 'pushed' if remote == target.head_sha else 'committed'
                return self._save(state)
            return run
