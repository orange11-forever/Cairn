"""Machine-local bindings and DPAPI-protected credentials; never part of a database backup."""

import base64
import json
import os
import re
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from cairn_api.errors import ApiProblem
from cairn_api.workspace.device import DeviceAuthorizations
from cairn_api.workspace.github import GitHubClient, GitHubToken, github_problem
from cairn_api.workspace.schemas import GitHubAccount, GitHubRepository, RepositoryBinding

WORKSPACE_FILE = "workspace-settings.dpapi"

if TYPE_CHECKING:
    from cairn_api.workspace.coding import CodingRunner
    from cairn_api.workspace.terminal import TerminalManager


class Credential(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_id: str
    account: GitHubAccount
    token: SecretStr
    expires_at: float | None = None


class UserWorkspace(BaseModel):
    model_config = ConfigDict(extra="forbid")
    credential: Credential | None = None
    projects: dict[UUID, RepositoryBinding] = Field(default_factory=dict[UUID, RepositoryBinding])


class WorkspaceFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(default=1, ge=1, le=1)
    users: dict[UUID, UserWorkspace] = Field(default_factory=dict[UUID, UserWorkspace])


class DesktopWorkspace:
    def __init__(
        self,
        data: Path,
        git: Path,
        client_id: str | None,
        protect: Callable[[bytes], bytes],
        unprotect: Callable[[bytes], bytes],
    ):
        self.data = data.resolve()
        self.git = git
        self.client_id = client_id
        self.github = GitHubClient(client_id) if client_id else None
        self.protect = protect
        self.unprotect = unprotect
        self.lock = threading.RLock()
        self.devices = DeviceAuthorizations()
        self.coding: CodingRunner | None = None
        self.terminals: TerminalManager | None = None
        self._values = WorkspaceFile()
        path = self.data / WORKSPACE_FILE
        if path.exists():
            try:
                if path.stat().st_size > 4_000_000:
                    raise ValueError("oversized settings")
                self._values = WorkspaceFile.model_validate_json(unprotect(path.read_bytes()))
            except (OSError, ValueError, ValidationError):
                raise github_problem(
                    "workspace_storage_failed", "本机仓库配置无法读取或解密，原文件已保留", 503
                ) from None

    def _save(self, values: WorkspaceFile) -> None:
        temporary: str | None = None
        try:
            serialized = values.model_dump(mode="json", exclude_computed_fields=True)
            for user_id, user in values.users.items():
                if user.credential:
                    serialized["users"][str(user_id)]["credential"]["token"] = (
                        user.credential.token.get_secret_value()
                    )
            encrypted = self.protect(json.dumps(serialized, ensure_ascii=False).encode())
            if len(encrypted) > 4_000_000:
                raise ValueError("oversized settings")
            with tempfile.NamedTemporaryFile(
                dir=self.data, prefix=".workspace-", delete=False
            ) as output:
                temporary = output.name
                output.write(encrypted)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.data / WORKSPACE_FILE)
            self._values = values
        except (OSError, ValueError):
            raise github_problem(
                "workspace_storage_failed",
                "无法保存本机仓库配置，请检查数据目录权限和可用空间",
                503,
            ) from None
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)

    def connect(self, user_id: UUID, account: GitHubAccount, token: GitHubToken) -> None:
        if "repo" not in token.scope.replace(",", " ").split():
            raise github_problem("github_scope_missing", "尚未授予仓库访问权限，请重新授权", 403)
        assert self.client_id is not None
        with self.lock:
            values = self._values.model_copy(deep=True)
            user = values.users.setdefault(user_id, UserWorkspace())
            user.credential = Credential(
                client_id=self.client_id,
                account=account,
                token=token.access_token,
                expires_at=time.time() + token.expires_in if token.expires_in else None,
            )
            self._save(values)

    def credential(self, user_id: UUID) -> Credential | None:
        with self.lock:
            user = self._values.users.get(user_id)
            credential = user.credential if user else None
            if credential and credential.client_id == self.client_id:
                return credential.model_copy(deep=True)
            return None

    def token(self, user_id: UUID) -> Credential:
        credential = self.credential(user_id)
        if credential is None:
            raise github_problem("github_not_connected", "请先授权 GitHub 仓库访问", 409)
        if credential.expires_at is not None and credential.expires_at <= time.time():
            raise github_problem("github_credentials_invalid", "GitHub 授权已过期，请重新授权", 401)
        return credential

    def disconnect(self, user_id: UUID) -> None:
        with self.lock:
            values = self._values.model_copy(deep=True)
            user = values.users.get(user_id)
            if user:
                user.credential = None
                self._save(values)
            self.devices.attempts = {
                key: attempt
                for key, attempt in self.devices.attempts.items()
                if attempt.user_id != user_id or attempt.intent != "repositories"
            }

    def binding(self, user_id: UUID, project_id: UUID) -> RepositoryBinding | None:
        with self.lock:
            user = self._values.users.get(user_id)
            binding = user.projects.get(project_id) if user else None
            return binding.model_copy(deep=True) if binding else None

    def unbind(self, user_id: UUID, project_id: UUID) -> None:
        with self.lock:
            values = self._values.model_copy(deep=True)
            user = values.users.get(user_id)
            if user:
                user.projects.pop(project_id, None)
                self._save(values)

    def _environment(self, token: str | None = None) -> dict[str, str]:
        # Git configuration and helpers inherited from a developer's machine must
        # not change which account, destination, transport or commands Cairn uses.
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.upper().startswith(("GIT_", "GCM_"))
        }
        environment.update(
            {
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_TERMINAL_PROMPT": "0",
                "GCM_INTERACTIVE": "Never",
                "GIT_LFS_SKIP_SMUDGE": "1",
                "GIT_NO_REPLACE_OBJECTS": "1",
            }
        )
        if token:
            encoded = base64.b64encode(("x-access-token:" + token).encode()).decode()
            environment.update(
                {
                    "GIT_CONFIG_COUNT": "1",
                    "GIT_CONFIG_KEY_0": "http.https://github.com/.extraHeader",
                    "GIT_CONFIG_VALUE_0": "Authorization: Basic " + encoded,
                }
            )
        return environment

    def run_git(
        self,
        arguments: list[str],
        *,
        token: str | None = None,
        timeout: int = 15,
        allow_one: bool = False,
        index: Path | None = None,
        input_data: bytes | None = None,
    ) -> str | None:
        if not self.git.is_file():
            raise github_problem(
                "git_unavailable", "Cairn 缺少随包 Git 运行组件，请修复或更新安装", 503
            )
        command = [
            str(self.git),
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.hooksPath=" + os.devnull,
            "-c",
            "credential.helper=",
            "-c",
            "protocol.allow=never",
            "-c",
            "protocol.https.allow=always",
            "-c",
            "http.followRedirects=false",
            "-c",
            "http.lowSpeedLimit=1000",
            "-c",
            "http.lowSpeedTime=30",
            *arguments,
        ]
        if os.name == "nt":
            command[1:1] = ["-c", "http.sslBackend=schannel"]
        environment = self._environment(token)
        if index is not None:
            environment['GIT_INDEX_FILE'] = str(index)
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE if input_data is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=environment,
                start_new_session=os.name != "nt",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            try:
                output, _ = process.communicate(input=input_data, timeout=timeout)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                        capture_output=True,
                        check=False,
                        timeout=10,
                    )
                else:
                    os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
                raise github_problem(
                    "git_timeout", "Git 操作超时；请检查网络、仓库权限和目标目录", 504
                ) from None
        except OSError:
            raise github_problem(
                "git_unavailable", "无法启动 Cairn 的 Git 运行组件，请修复或更新安装", 503
            ) from None
        if allow_one and process.returncode == 1:
            return None
        if process.returncode:
            # Raw stderr may contain credentials from an existing repository's URL.
            raise github_problem(
                "git_failed",
                f"Git 操作失败（退出码 {process.returncode}），请检查仓库目录、网络和访问权限",
                409,
            )
        return output.decode('utf-8', errors='replace').strip()

    def _path(self, value: str) -> Path:
        path = Path(value).expanduser()
        if not path.is_absolute():
            raise github_problem("workspace_path_invalid", "请选择绝对路径", 422)
        path = path.resolve()
        if path.is_relative_to(self.data) or self.data.is_relative_to(path):
            raise github_problem(
                "workspace_path_invalid",
                "代码目录不能包含 Cairn 数据目录，也不能位于数据目录内",
                422,
            )
        return path

    def inspect(self, value: str) -> tuple[Path, str | None]:
        path = self._path(value)
        if not path.is_dir():
            raise github_problem("workspace_path_missing", "关联的本地目录不存在，请重新选择", 404)
        root = self.run_git(["-C", str(path), "rev-parse", "--show-toplevel"])
        if root is None or Path(root).resolve() != path:
            raise github_problem("workspace_not_root", "请选择 Git 仓库的根目录", 422)
        branch = self.run_git(
            ["-C", str(path), "symbolic-ref", "--quiet", "--short", "HEAD"], allow_one=True
        )
        return path, branch

    def source_paths(self, root: Path) -> str:
        raw = self.read_git(
            root,
            ["ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            global_excludes=True,
        )
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            raise github_problem(
                "architecture_path_invalid", "仓库包含无法识别的文件名编码", 422
            ) from None

    def read_git(
        self,
        root: Path,
        arguments: list[str],
        *,
        limit: int = 2_000_000,
        global_excludes: bool = False,
    ) -> bytes:
        # Only this read-only inventory respects global excludes. Execution-related
        # settings remain overridden; clone and other commands keep isolated config.
        environment = self._environment()
        if global_excludes:
            environment.pop("GIT_CONFIG_GLOBAL", None)
            if "GIT_CONFIG_GLOBAL" in os.environ:
                environment["GIT_CONFIG_GLOBAL"] = os.environ["GIT_CONFIG_GLOBAL"]
        command = [
            str(self.git),
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.hooksPath=" + os.devnull,
            "--literal-pathspecs",
            "-C",
            str(root),
            *arguments,
        ]
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=environment,
                start_new_session=os.name != "nt",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except OSError:
            raise github_problem(
                "git_unavailable", "无法启动 Git 读取源码清单，请检查安装", 503
            ) from None

        def stop() -> None:
            if process.poll() is None:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                        capture_output=True,
                        check=False,
                        timeout=10,
                    )
                else:
                    os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=10)

        assert process.stdout is not None
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(process.stdout.read, limit + 1)
                try:
                    output = pending.result(timeout=15)
                    if len(output) > limit:
                        stop()
                        raise github_problem(
                            "architecture_repository_too_large", "Git 输出超出容量限制", 422
                        )
                    process.wait(timeout=15)
                except (TimeoutError, subprocess.TimeoutExpired):
                    stop()
                    raise github_problem(
                        "git_timeout", "读取仓库文件清单超时，请检查工作目录", 504
                    ) from None
            if process.returncode:
                raise github_problem("git_failed", "无法读取仓库文件清单，请检查 Git 仓库状态", 409)
            return output
        finally:
            process.stdout.close()

    def head(self, root: Path) -> str | None:
        return self.run_git(
            ["-C", str(root), "rev-parse", "--verify", "--quiet", "HEAD"], allow_one=True
        )

    def _record(
        self, user_id: UUID, project_id: UUID, binding: RepositoryBinding
    ) -> RepositoryBinding:
        values = self._values.model_copy(deep=True)
        values.users.setdefault(user_id, UserWorkspace()).projects[project_id] = binding
        self._save(values)
        return binding

    def bind_local(
        self,
        user_id: UUID,
        project_id: UUID,
        value: str,
        repository: GitHubRepository | None = None,
        account: GitHubAccount | None = None,
    ) -> RepositoryBinding:
        with self.lock:
            path, branch = self.inspect(value)
            if repository:
                self.verify_remote(path, repository)
            return self._record(
                user_id,
                project_id,
                RepositoryBinding(
                    local_path=str(path), branch=branch, repository=repository, account=account
                ),
            )

    def verify_remote(self, path: Path, repository: GitHubRepository) -> None:
        origin = self.run_git(
            ["-C", str(path), "config", "--get", "remote.origin.url"], allow_one=True
        )
        match = re.fullmatch(
            r"(?:https://github\.com/|git@github\.com:)([^/]+/[^/]+?)(?:\.git)?", origin or ""
        )
        if not match or match.group(1).lower() != repository.full_name.lower():
            raise github_problem(
                "workspace_remote_mismatch",
                "本地仓库的 origin 与关联的 GitHub 仓库不一致，请重新选择；原关联和文件已保留",
                409,
            )

    def clone(
        self,
        user_id: UUID,
        project_id: UUID,
        repository: GitHubRepository,
        destination: str,
        token: str,
        account: GitHubAccount | None = None,
    ) -> RepositoryBinding:
        with self.lock:
            path = self._path(destination)
            try:
                path.mkdir()  # Atomic ownership; never clone into an existing directory.
            except FileExistsError:
                raise github_problem(
                    "workspace_destination_exists",
                    "目标目录已存在，请选择新的目录名；已有文件未修改",
                    409,
                ) from None
            except OSError:
                raise github_problem(
                    "workspace_path_invalid", "无法创建目标目录，请检查父目录及写入权限", 422
                ) from None
            try:
                self.run_git(
                    [
                        "clone",
                        "--template=",
                        "--no-recurse-submodules",
                        "--",
                        repository.url + ".git",
                        str(path),
                    ],
                    token=token,
                    timeout=180,
                )
                return self.bind_local(user_id, project_id, str(path), repository, account)
            except ApiProblem as error:
                raise github_problem(
                    error.code,
                    error.message + f"。目标目录已保留：{path}；项目关联未更新",
                    error.status_code,
                ) from None
