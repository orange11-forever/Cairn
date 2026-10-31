"""Retained, per-run Git worktrees. No merge, commit, cleanup or remote operation."""

import hashlib
from pathlib import Path

from cairn_api.workspace.coding_process import problem
from cairn_api.workspace.coding_schemas import CodingRun
from cairn_api.workspace.editor import RepositoryEditor
from cairn_api.workspace.local import DesktopWorkspace


def require_plain_git(workspace: DesktopWorkspace, root: Path) -> None:
    # Checkout/status can execute repository-configured filters without a shell
    # command in the Agent protocol. These repositories need explicit tool support.
    filters = workspace.run_git(['-C', str(root), 'config', '--name-only', '--get-regexp',
                             r'^filter\..*\.(clean|smudge|process)$'], allow_one=True)
    if filters:
        raise problem('coding_git_filter_unsupported',
                      '仓库配置了 Git 内容过滤命令，当前不支持自动创建其 Agent 工作区；请使用不依赖过滤器的源码仓库。')


def worktree_path(root: Path, run_id: str) -> Path:
    # Keep user code beside the repository, outside Cairn's runtime/backup data.
    return root.parent / (root.name + '.cairn-worktrees') / run_id


def create_worktree(workspace: DesktopWorkspace, run: CodingRun) -> None:
    assert run.repository_path and run.base_head and run.branch
    root, target = Path(run.repository_path), Path(run.local_path)
    require_plain_git(workspace, root)
    if target.parent.is_symlink() or target.parent.is_junction() or target.exists():
        raise problem('coding_worktree_path_changed', 'Agent 工作目录已存在或变为链接；原文件已保留，请检查运行记录中的位置。')
    target.parent.mkdir(exist_ok=True)
    # An explicit SHA and a fresh branch prevent Git from guessing remote refs.
    # Lock against pruning; successful and partially created worktrees stay put.
    workspace.run_git(['-c', 'submodule.recurse=false', '-C', str(root), 'worktree', 'add', '--no-checkout',
                    '--lock', '--reason', 'Cairn coding run ' + str(run.id),
                    '-b', run.branch, str(target), run.base_head], timeout=120)
    # includeIf onbranch/gitdir can activate filters only in the new worktree.
    # Inspect that context before populating it; a rejected empty worktree stays
    # retained, just like any other failed run's files and branch.
    require_plain_git(workspace, target)
    workspace.run_git(['-c', 'submodule.recurse=false', '-C', str(target),
                       'reset', '--hard', run.base_head], timeout=120)


class WorktreeEditor(RepositoryEditor):
    def __init__(self, workspace: DesktopWorkspace, run: CodingRun, *, expected_head: str | None = None):
        super().__init__(workspace, run.user_id, run.project_id)
        self.run = run
        self.expected_head = expected_head or run.base_head

    def context(self, expected: str | None = None) -> tuple[Path, str | None, str | None, str]:
        run = self.run
        target = Path(run.local_path)
        if target.resolve() != target or target.is_symlink() or target.is_junction():
            raise problem('coding_worktree_path_changed', 'Agent 工作目录已变为链接；运行停止，文件已保留。')
        root, branch = self.workspace.inspect(run.local_path)
        head = self.workspace.head(root)
        identity = hashlib.sha256((str(run.id) + str(root) + str(branch) + str(head)).encode()).hexdigest()
        if branch != run.branch or head != self.expected_head or (expected is not None and expected != identity):
            raise problem('workspace_changed', 'Agent 工作区的分支或 HEAD 已变化；运行停止，改动已保留。')
        return root, branch, head, identity
