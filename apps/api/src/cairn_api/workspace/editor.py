"""Local text editing. Contents never enter the model pipeline or database."""

import hashlib
import os
import re
import secrets
import stat
from collections.abc import Generator
from contextlib import ExitStack, contextmanager
from pathlib import Path, PurePosixPath
from uuid import UUID

from pydantic import Field

from cairn_api.errors import ApiProblem
from cairn_api.workspace.architecture import opened_path
from cairn_api.workspace.github import github_problem
from cairn_api.workspace.local import DesktopWorkspace
from cairn_api.workspace.schemas import WorkspaceModel

MAX_FILE_BYTES = 524288


class FileDocument(WorkspaceModel):
    workspace_id: str
    path: str
    content: str
    revision: str


class SaveFileRequest(WorkspaceModel):
    workspace_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    path: str = Field(min_length=1, max_length=4096)
    revision: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    content: str = Field(max_length=MAX_FILE_BYTES)


class FileTree(WorkspaceModel):
    workspace_id: str
    branch: str | None
    paths: list[str]


class ChangedFile(WorkspaceModel):
    path: str
    status: str


class RepositoryChanges(WorkspaceModel):
    workspace_id: str
    files: list[ChangedFile]


class FileDiff(WorkspaceModel):
    workspace_id: str
    path: str
    original: str
    modified: str
    revision: str | None


def _valid_path(value: str) -> None:
    parts = PurePosixPath(value).parts
    if (
        not parts
        or PurePosixPath(value).is_absolute()
        or PurePosixPath(value).as_posix() != value
        or any(part in {".", ".."} or part.rstrip(". ").lower() == ".git" for part in parts)
        or any(char in value for char in "\\:")
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
        or any(part.endswith((".", " ")) for part in parts)
        or any(
            re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", part)
            for part in parts
        )
    ):
        raise github_problem(
            "workspace_path_invalid",
            "请选择仓库内的相对文件路径，不能访问 Git 内部文件或特殊路径",
            422,
        )


def _target(root: Path, relative: str) -> Path:
    _valid_path(relative)
    path = root
    for part in PurePosixPath(relative).parts:
        path /= part
        if path.is_symlink() or path.is_junction():
            raise github_problem(
                "workspace_link_unsupported", "链接路径不能在代码工作区中读写", 422
            )
    if not path.resolve().is_relative_to(root):
        raise github_problem("workspace_path_invalid", "文件路径已离开关联仓库", 422)
    return path


def _text(raw: bytes) -> str:
    if len(raw) > MAX_FILE_BYTES:
        raise github_problem(
            "workspace_file_too_large", "此文件超过 512 KiB，请使用外部编辑器", 422
        )
    try:
        if b"\x00" in raw:
            raise ValueError()
        return raw.decode("utf-8-sig")
    except (UnicodeDecodeError, ValueError):
        raise github_problem(
            "workspace_file_not_text",
            "仅支持 UTF-8 文本；二进制或其他编码文件请使用外部编辑器",
            422,
        ) from None


def _raw(root: Path, relative: str) -> tuple[bytes, os.stat_result]:
    path = _target(root, relative)
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_BINARY", 0),
        )
        with os.fdopen(descriptor, "rb") as source:
            metadata = os.fstat(source.fileno())
            if (
                not opened_path(source.fileno()).is_relative_to(root)
                or not stat.S_ISREG(metadata.st_mode)
                or metadata.st_nlink != 1
            ):
                raise github_problem(
                    "workspace_link_unsupported",
                    "仅支持仓库内的普通文件，不支持硬链接或特殊文件",
                    422,
                )
            if metadata.st_size > MAX_FILE_BYTES:
                raise github_problem(
                    "workspace_file_too_large", "此文件超过 512 KiB，请使用外部编辑器", 422
                )
            raw = source.read(MAX_FILE_BYTES + 1)
        _text(raw)
        return raw, metadata
    except FileNotFoundError:
        raise github_problem("workspace_file_missing", f"文件不存在：{relative}", 404) from None
    except OSError:
        raise github_problem(
            "workspace_read_failed", f"无法读取文件：{relative}，请检查权限", 409
        ) from None


def _revision(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


@contextmanager
def _save_directory(root: Path, parent: Path) -> Generator[int | None]:
    """Pin each parent: Windows denies renames; POSIX writes use directory FDs."""
    with ExitStack() as stack:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            create = kernel.CreateFileW
            create.argtypes = [
                wintypes.LPCWSTR,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.LPVOID,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.HANDLE,
            ]
            create.restype = wintypes.HANDLE
            close = kernel.CloseHandle
            close.argtypes = [wintypes.HANDLE]
            close.restype = wintypes.BOOL
            path = root
            for part in ("", *parent.relative_to(root).parts):
                path /= part
                # FILE_SHARE_READ | FILE_SHARE_WRITE, deliberately no SHARE_DELETE.
                # FILE_LIST_DIRECTORY participates in share-mode checks;
                # FILE_READ_ATTRIBUTES alone does not prevent a concurrent rename.
                handle = create(str(path), 0x1, 3, None, 3, 0x02000000 | 0x00200000, None)
                if handle == wintypes.HANDLE(-1).value:
                    raise OSError(ctypes.get_last_error(), "Cannot pin save directory")
                stack.callback(close, handle)
                if path.is_symlink() or path.is_junction():
                    raise github_problem(
                        "workspace_link_unsupported", "保存目录已变为链接，草稿已保留", 422
                    )
            yield None
        else:
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            descriptor = os.open(root, flags)
            stack.callback(os.close, descriptor)
            for part in parent.relative_to(root).parts:
                descriptor = os.open(part, flags, dir_fd=descriptor)
                stack.callback(os.close, descriptor)
            if not opened_path(descriptor).is_relative_to(root):
                raise github_problem("workspace_path_invalid", "保存目录已离开关联仓库", 422)
            yield descriptor


class RepositoryEditor:
    def __init__(self, workspace: DesktopWorkspace, user_id: UUID, project_id: UUID):
        self.workspace, self.user_id, self.project_id = workspace, user_id, project_id

    def context(self, expected: str | None = None) -> tuple[Path, str | None, str | None, str]:
        binding = self.workspace.binding(self.user_id, self.project_id)
        if binding is None:
            raise github_problem("workspace_not_bound", "请先关联此项目的本地代码仓库", 409)
        root, branch = self.workspace.inspect(binding.local_path)
        head = self.workspace.head(root)
        identity = _revision(
            (binding.model_dump_json() + str(root) + str(branch) + str(head)).encode()
        )
        if expected is not None and identity != expected:
            raise github_problem(
                "workspace_changed",
                "仓库关联、分支或 HEAD 已变化；草稿已保留，请重新打开文件核对",
                409,
            )
        return root, branch, head, identity

    def tree(self) -> FileTree:
        with self.workspace.lock:
            root, branch, _, identity = self.context()
            paths = sorted(set(self.workspace.source_paths(root).split("\0")) - {""})
            visible: list[str] = []
            for path in paths:
                try:
                    _valid_path(path)
                except ApiProblem:
                    continue
                visible.append(path)
            if len(visible) > 10000:
                raise github_problem(
                    "workspace_tree_too_large", "仓库文件超过 10000 个，请选择较小的工作目录", 422
                )
            return FileTree(workspace_id=identity, branch=branch, paths=visible)

    def read(self, path: str) -> FileDocument:
        with self.workspace.lock:
            root, _, _, identity = self.context()
            raw, _ = _raw(root, path)
            return FileDocument(
                workspace_id=identity, path=path, content=_text(raw), revision=_revision(raw)
            )

    def save(self, payload: SaveFileRequest) -> FileDocument:
        with self.workspace.lock:
            root, _, _, identity = self.context(payload.workspace_id)
            target = _target(root, payload.path)
            previous: bytes | None = None
            mode = 0o644
            if payload.revision is not None:
                try:
                    previous, metadata = _raw(root, payload.path)
                except ApiProblem as error:
                    if error.code != "workspace_file_missing":
                        raise
                    raise github_problem(
                        "workspace_file_conflict", "文件已被外部删除，草稿已保留", 409
                    ) from None
                if _revision(previous) != payload.revision:
                    raise github_problem(
                        "workspace_file_conflict",
                        "文件已被外部修改，草稿已保留；请对照磁盘版本后再保存",
                        409,
                    )
                mode = stat.S_IMODE(metadata.st_mode)
            elif target.exists():
                raise github_problem("workspace_file_conflict", "同名文件已存在，草稿已保留", 409)
            try:
                raw = payload.content.encode("utf-8")
            except UnicodeEncodeError:
                raise github_problem(
                    "workspace_file_not_text", "内容包含无效的 Unicode 字符", 422
                ) from None
            if previous and previous.startswith(b"\xef\xbb\xbf"):
                raw = b"\xef\xbb\xbf" + raw
            _text(raw)
            try:
                with _save_directory(root, target.parent) as parent_fd:
                    name = ".cairn-save-" + secrets.token_hex(12)
                    temporary = str(target.parent / name) if parent_fd is None else name
                    destination = str(target) if parent_fd is None else target.name
                    descriptor = os.open(
                        temporary,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
                        mode,
                        dir_fd=parent_fd,
                    )
                    try:
                        with os.fdopen(descriptor, "wb") as output:
                            if not opened_path(output.fileno()).is_relative_to(root):
                                raise github_problem(
                                    "workspace_path_invalid", "保存目录已离开关联仓库", 422
                                )
                            output.write(raw)
                            output.flush()
                            os.fsync(output.fileno())
                            if os.name != "nt":
                                os.fchmod(output.fileno(), mode)
                        _target(root, payload.path)
                        if parent_fd is not None and not opened_path(parent_fd).is_relative_to(
                            root
                        ):
                            raise github_problem(
                                "workspace_path_invalid", "保存目录已离开关联仓库", 422
                            )
                        if previous is not None:
                            current, _ = _raw(root, payload.path)
                            if current != previous:
                                raise github_problem(
                                    "workspace_file_conflict",
                                    "保存期间文件发生变化，草稿已保留",
                                    409,
                                )
                            os.replace(
                                temporary, destination, src_dir_fd=parent_fd, dst_dir_fd=parent_fd
                            )
                        else:
                            try:
                                if os.name == "nt":
                                    os.rename(
                                        temporary, destination
                                    )  # Windows: fails if name exists.
                                else:
                                    os.link(
                                        temporary,
                                        destination,
                                        src_dir_fd=parent_fd,
                                        dst_dir_fd=parent_fd,
                                    )
                            except FileExistsError:
                                raise github_problem(
                                    "workspace_file_conflict", "同名文件已存在，草稿已保留", 409
                                ) from None
                    finally:
                        try:
                            os.unlink(temporary, dir_fd=parent_fd)
                        except FileNotFoundError:
                            pass  # Successful atomic replacement consumed the temporary name.
            except OSError:
                raise github_problem(
                    "workspace_write_failed",
                    f"无法保存 {payload.path}，请检查目录权限和磁盘空间；草稿已保留",
                    409,
                ) from None
            return FileDocument(
                workspace_id=identity,
                path=payload.path,
                content=payload.content,
                revision=_revision(raw),
            )

    def changes(self) -> RepositoryChanges:
        with self.workspace.lock:
            root, _, _, identity = self.context()
            raw = self.workspace.read_git(
                root,
                ["status", "--porcelain=v1", "-z", "--untracked-files=all", "--no-renames"],
                global_excludes=True,
            )
            try:
                entries = raw.decode("utf-8").split("\0")
            except UnicodeDecodeError:
                raise github_problem(
                    "workspace_path_invalid", "Git 变更包含无法识别的文件名编码", 422
                ) from None
            return RepositoryChanges(
                workspace_id=identity,
                files=[ChangedFile(path=entry[3:], status=entry[:2]) for entry in entries if entry],
            )

    def diff(self, path: str) -> FileDiff:
        with self.workspace.lock:
            root, _, head, identity = self.context()
            _valid_path(path)
            original = ""
            if head:
                entry = self.workspace.read_git(root, ["ls-tree", "-z", head, "--", path])
                if entry:
                    metadata = entry.split(b"\t", 1)[0].split()
                    if metadata[0] not in (b"100644", b"100755") or metadata[1] != b"blob":
                        raise github_problem(
                            "workspace_file_not_text", "此 Git 条目不是普通文本文件", 422
                        )
                    oid = metadata[2].decode("ascii")
                    size = int(self.workspace.read_git(root, ["cat-file", "-s", oid]))
                    if size > MAX_FILE_BYTES:
                        raise github_problem(
                            "workspace_file_too_large", "Git 原始文件超过 512 KiB", 422
                        )
                    original = _text(
                        self.workspace.read_git(
                            root, ["cat-file", "blob", oid], limit=MAX_FILE_BYTES
                        )
                    )
            try:
                raw, _ = _raw(root, path)
                modified, revision = _text(raw), _revision(raw)
            except ApiProblem as error:
                if error.code != "workspace_file_missing":
                    raise
                modified, revision = "", None
            return FileDiff(
                workspace_id=identity,
                path=path,
                original=original,
                modified=modified,
                revision=revision,
            )
