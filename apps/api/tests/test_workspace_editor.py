import base64
import os
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
from cairn_api.errors import ApiProblem
from cairn_api.workspace.editor import FileDocument, RepositoryEditor, SaveFileRequest
from cairn_api.workspace.local import DesktopWorkspace


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


@pytest.fixture
def editor(tmp_path: Path) -> tuple[RepositoryEditor, Path]:
    data, root = tmp_path / "data", tmp_path / "repo"
    data.mkdir()
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "config", "user.name", "Test")
    (root / "main.py").write_bytes(b'\xef\xbb\xbfprint("before")\r\n')
    (root / "main.py").chmod(0o755)
    (root / ".gitignore").write_text("ignored/\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "fixture")
    workspace = DesktopWorkspace(
        data, Path("/usr/bin/git"), None, base64.b64encode, base64.b64decode
    )
    user, project = uuid4(), uuid4()
    workspace.bind_local(user, project, str(root))
    return RepositoryEditor(workspace, user, project), root


def save(editor: RepositoryEditor, doc: FileDocument, content: str) -> FileDocument:
    return editor.save(
        SaveFileRequest(
            workspace_id=doc.workspace_id, path=doc.path, revision=doc.revision, content=content
        )
    )


def test_read_save_diff_preserves_bom_newlines_mode_and_git_index(editor: tuple[RepositoryEditor, Path]) -> None:
    service, root = editor
    doc = service.read("main.py")
    assert doc.content == 'print("before")\r\n'
    saved = save(service, doc, 'print("after")\r\n')
    assert saved.content == 'print("after")\r\n'
    assert saved.revision != doc.revision
    assert (root / "main.py").read_bytes() == b'\xef\xbb\xbfprint("after")\r\n'
    assert os.stat(root / "main.py").st_mode & 0o111
    diff = service.diff("main.py")
    assert diff.original == doc.content and diff.modified == saved.content
    assert git(root, "diff", "--cached") == ""
    assert [(item.path, item.status) for item in service.changes().files] == [("main.py", " M")]


def test_external_change_and_rebind_reject_save_without_losing_either_version(editor: tuple[RepositoryEditor, Path]) -> None:
    service, root = editor
    doc = service.read("main.py")
    (root / "main.py").write_text("external")
    with pytest.raises(ApiProblem) as failure:
        save(service, doc, "mine")
    assert failure.value.code == "workspace_file_conflict"
    assert (root / "main.py").read_text() == "external"
    git(root, "switch", "-c", "other")
    with pytest.raises(ApiProblem) as failure:
        save(service, doc, "mine")
    assert failure.value.code == "workspace_changed"


@pytest.mark.parametrize(
    "path",
    [
        "../outside",
        "/etc/passwd",
        ".git/config",
        ".GIT/config",
        "a/../../b",
        "C:/test",
        "a\\b",
        "main.py:stream",
        "./main.py",
        "a//b",
    ],
)
def test_rejects_unsafe_paths(editor: tuple[RepositoryEditor, Path], path: str) -> None:
    service, _ = editor
    with pytest.raises(ApiProblem) as failure:
        service.read(path)
    assert failure.value.status_code == 422


def test_link_binary_large_and_non_utf8_files_are_not_editable(editor: tuple[RepositoryEditor, Path], tmp_path: Path) -> None:
    service, root = editor
    outside = tmp_path / "outside"
    outside.write_text("kept")
    (root / "link.py").symlink_to(outside)
    (root / "linked").symlink_to(tmp_path, target_is_directory=True)
    os.link(outside, root / "hard.py")
    (root / "binary").write_bytes(b"a\x00b")
    (root / "encoding").write_bytes(b"\xff")
    (root / "large").write_bytes(b"a" * 524289)
    for path in ["link.py", "linked/outside", "hard.py", "binary", "encoding", "large"]:
        with pytest.raises(ApiProblem):
            service.read(path)
    assert outside.read_text() == "kept"


def test_failed_atomic_replace_preserves_original_and_cleans_temporary(editor: tuple[RepositoryEditor, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    service, root = editor
    doc = service.read("main.py")
    original = (root / "main.py").read_bytes()

    def fail(*args: object, **kwargs: object) -> None:
        raise OSError("disk failure")

    monkeypatch.setattr("cairn_api.workspace.editor.os.replace", fail)
    with pytest.raises(ApiProblem) as failure:
        save(service, doc, "mine")
    assert failure.value.code == "workspace_write_failed"
    assert (root / "main.py").read_bytes() == original
    assert not list(root.glob(".cairn-save-*"))


def test_tree_and_diff_include_untracked_deleted_and_unborn_repo(editor: tuple[RepositoryEditor, Path]) -> None:
    service, root = editor
    (root / "new.ts").write_text("export const x = 1;\n")
    (root / "ignored").mkdir()
    (root / "ignored" / "secret").write_text("ignored")
    (root / "main.py").unlink()
    assert "new.ts" in service.tree().paths and "ignored/secret" not in service.tree().paths
    assert service.diff("new.ts").original == ""
    removed = service.diff("main.py")
    assert removed.modified == "" and removed.original == 'print("before")\r\n'
    git(root, "checkout", "--orphan", "empty")
    assert service.diff("new.ts").original == ""


def test_diff_does_not_run_git_textconv_or_external_diff(editor: tuple[RepositoryEditor, Path], tmp_path: Path) -> None:
    service, root = editor
    marker = tmp_path / "executed"
    git(root, "config", "diff.external", f"touch {marker}")
    git(root, "config", "diff.test.textconv", f"touch {marker}")
    (root / ".gitattributes").write_text("*.py diff=test\n")
    service.diff("main.py")
    service.changes()
    assert not marker.exists()


def test_parent_path_swap_cannot_redirect_atomic_save(editor: tuple[RepositoryEditor, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service, root = editor
    directory = root / "dir"
    directory.mkdir()
    (directory / "file.py").write_text("original")
    outside = tmp_path / "unrelated"
    outside.mkdir()
    (outside / "file.py").write_text("outside user work")
    moved = root / "moved"
    doc = service.read("dir/file.py")
    replace = os.replace

    def swapped(source: str, target: str, *, src_dir_fd: int | None = None, dst_dir_fd: int | None = None) -> None:
        directory.rename(moved)
        directory.symlink_to(outside, target_is_directory=True)
        replace(source, target, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

    monkeypatch.setattr("cairn_api.workspace.editor.os.replace", swapped)
    save(service, doc, "mine")
    assert (outside / "file.py").read_text() == "outside user work"
    assert (moved / "file.py").read_text() == "mine"
    assert not list(moved.glob(".cairn-save-*"))


def test_new_file_save_is_no_clobber(editor: tuple[RepositoryEditor, Path]) -> None:
    service, root = editor
    workspace_id = service.tree().workspace_id
    request = SaveFileRequest(workspace_id=workspace_id, path="new.py", content="new file")
    result = service.save(request)
    assert (root / "new.py").read_text() == result.content == "new file"
    with pytest.raises(ApiProblem) as failure:
        service.save(request)
    assert failure.value.code == "workspace_file_conflict"
