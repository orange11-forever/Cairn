import base64
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
from cairn_api.errors import ApiProblem


def git(path: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(path), *args], text=True).strip()


def repository(path: Path) -> Path:
    path.mkdir()
    git(path, "init", "-b", "main")
    (path / "kept.txt").write_text("user work")
    return path


def data_directory(path: Path) -> Path:
    data = path / "data"
    data.mkdir()
    return data


def test_local_binding_survives_restart_is_private_to_user_and_unlink_keeps_files(
    tmp_path: Path,
) -> None:
    from cairn_api.workspace.local import DesktopWorkspace

    data = tmp_path / "data"
    data.mkdir()
    repo = repository(tmp_path / "code")
    user, other, project = uuid4(), uuid4(), uuid4()
    workspace = DesktopWorkspace(
        data, Path("/usr/bin/git"), "cairn-test", base64.b64encode, base64.b64decode
    )
    bound = workspace.bind_local(user, project, str(repo))
    assert bound.local_path == str(repo.resolve())
    assert bound.branch == "main"
    reopened = DesktopWorkspace(
        data, Path("/usr/bin/git"), "cairn-test", base64.b64encode, base64.b64decode
    )
    retained = reopened.binding(user, project)
    assert retained is not None and retained.local_path == str(repo)
    assert reopened.binding(other, project) is None
    reopened.unbind(user, project)
    assert reopened.binding(user, project) is None
    assert (repo / "kept.txt").read_text() == "user work"
    assert (repo / ".git").is_dir()


def test_local_binding_requires_repository_root_and_never_initializes_user_folder(
    tmp_path: Path,
) -> None:
    from cairn_api.workspace.local import DesktopWorkspace

    workspace = DesktopWorkspace(
        data_directory(tmp_path), Path("/usr/bin/git"), None, base64.b64encode, base64.b64decode
    )
    repo = repository(tmp_path / "repo")
    (repo / "nested").mkdir()
    outside = tmp_path / "other"
    outside.mkdir()
    for path in [repo / "nested", outside]:
        with pytest.raises(ApiProblem):
            workspace.bind_local(uuid4(), uuid4(), str(path))
    assert not (outside / ".git").exists()


def test_local_git_reads_do_not_execute_configured_fsmonitor(tmp_path: Path) -> None:
    from cairn_api.workspace.local import DesktopWorkspace

    repo = repository(tmp_path / "repo")
    marker = tmp_path / "executed"
    git(repo, "config", "core.fsmonitor", f"touch {marker}")
    workspace = DesktopWorkspace(
        data_directory(tmp_path), Path("/usr/bin/git"), None, base64.b64encode, base64.b64decode
    )
    workspace.bind_local(uuid4(), uuid4(), str(repo))
    assert not marker.exists()


def test_clone_rejects_existing_destination_without_touching_files(tmp_path: Path) -> None:
    from cairn_api.workspace.local import DesktopWorkspace
    from cairn_api.workspace.schemas import GitHubRepository

    dest = repository(tmp_path / "existing")
    workspace = DesktopWorkspace(
        data_directory(tmp_path),
        Path("/usr/bin/git"),
        "cairn-test",
        base64.b64encode,
        base64.b64decode,
    )
    remote = GitHubRepository(
        id=42, full_name="octo/project", private=True, default_branch="main", can_push=False
    )
    with pytest.raises(ApiProblem) as failure:
        workspace.clone(uuid4(), uuid4(), remote, str(dest), "secret-token")
    assert failure.value.code == "workspace_destination_exists"
    assert (dest / "kept.txt").read_text() == "user work"


def test_failed_persistence_is_not_reported_as_saved(tmp_path: Path) -> None:
    from cairn_api.workspace.local import DesktopWorkspace

    repo = repository(tmp_path / "repo")

    def failed(_: bytes) -> bytes:
        raise OSError("controlled storage failure")

    workspace = DesktopWorkspace(
        data_directory(tmp_path), Path("/usr/bin/git"), None, failed, base64.b64decode
    )
    user, project = uuid4(), uuid4()
    with pytest.raises(ApiProblem) as failure:
        workspace.bind_local(user, project, str(repo))
    assert failure.value.code == "workspace_storage_failed"
    assert workspace.binding(user, project) is None


def test_noninteractive_git_does_not_wait_for_supervisor_command_pipe(tmp_path: Path) -> None:
    import sys

    executable = tmp_path / "git-probe"
    executable.write_text('#!/bin/sh\ncat >/dev/null\nprintf "completed\\n"\n')
    executable.chmod(0o755)
    data = data_directory(tmp_path)
    code = """
import base64,sys
from pathlib import Path
from cairn_api.workspace.local import DesktopWorkspace
workspace=DesktopWorkspace(Path(sys.argv[1]),Path(sys.argv[2]),None,base64.b64encode,base64.b64decode)
print(workspace._run(['probe'],timeout=2))
"""
    process = subprocess.Popen(
        [sys.executable, "-c", code, str(data), str(executable)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        process.wait(timeout=5)  # Keep supervisor input open until the Git operation finishes.
    finally:
        if process.poll() is None:
            process.kill()
    output, error = process.communicate()
    assert process.returncode == 0, error
    assert output.strip() == "completed"
