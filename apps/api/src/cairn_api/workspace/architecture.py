"""Bounded, read-only repository evidence for the selected assistant."""

import hashlib
import json
import os
import re
import stat
from pathlib import Path, PurePosixPath
from uuid import NAMESPACE_URL, uuid5

from pydantic import Field

from cairn_api.knowledge.answer_provider import AnswerEvidence
from cairn_api.workspace.github import github_problem
from cairn_api.workspace.local import DesktopWorkspace
from cairn_api.workspace.schemas import WorkspaceModel

MAX_SOURCES = 24
MAX_CHARACTERS = 64000
MAX_EXCERPT = 4000
MANIFESTS = {
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "go.mod",
    "cargo.toml",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "settings.gradle",
    "composer.json",
    "gemfile",
    "dockerfile",
    "makefile",
    "cmakelists.txt",
    "pnpm-workspace.yaml",
}
EXTENSIONS = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".java",
    ".kt",
    ".go",
    ".rs",
    ".cs",
    ".cpp",
    ".c",
    ".h",
    ".php",
    ".rb",
    ".vue",
    ".svelte",
    ".sql",
    ".proto",
}
IGNORED_PARTS = {
    ".git",
    ".ssh",
    ".aws",
    ".venv",
    "venv",
    "node_modules",
    "vendor",
    "dist",
    "build",
    "target",
    "coverage",
    "__pycache__",
    ".next",
}
SECRET_ASSIGNMENT = re.compile(
    r"""(?im)(["']?[a-z0-9_-]*(?:api[_-]?key|access[_-]?key|token|password|passwd|secret|private[_-]?key|credential|authorization)[a-z0-9_-]*["']?\s*[:=]\s*)(["'])([^\r\n]*?)\2"""
)
URI_CREDENTIAL = re.compile(r"(?i)([a-z][a-z0-9+.-]*://)[^\s/@\"']+:[^\s/@\"']+@")
SECRET_UNQUOTED = re.compile(
    r"""(?im)^(\s*(?:export\s+)?[a-z0-9_-]*(?:api[_-]?key|access[_-]?key|token|password|passwd|secret|private[_-]?key|credential|authorization)[a-z0-9_-]*\s*(?::=|\?=|\+=|=|:)\s*)(?!["'])([^\r\n]+)"""
)
SECRET_XML = re.compile(
    r"(?is)(<(?:password|secret|token|apiKey)>).*?(</(?:password|secret|token|apiKey)>)"
)
KNOWN_TOKEN = re.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9_]{12,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{16,})\b"
)


class ArchitectureSource(WorkspaceModel):
    id: str
    path: str
    start_line: int = 1
    end_line: int
    content: str
    truncated: bool
    redacted: bool


class RepositorySnapshot(WorkspaceModel):
    branch: str | None
    head: str | None
    digest: str
    eligible_files: int
    sources: list[ArchitectureSource]
    truncated: bool
    excluded_files: int
    paths: list[str] = Field(max_length=300)

    def evidence(self) -> list[AnswerEvidence]:
        return [
            AnswerEvidence(
                id=source.id,
                chunk_id=uuid5(NAMESPACE_URL, source.path),
                title=source.path,
                locator={
                    "type": "code",
                    "path": source.path,
                    "startLine": source.start_line,
                    "endLine": source.end_line,
                },
                text=source.content,
            )
            for source in self.sources
        ]


def _eligible(value: str) -> bool:
    path = PurePosixPath(value)
    lower = path.name.lower()
    return (
        not path.is_absolute()
        and ".." not in path.parts
        and "\\" not in value
        and not any(ord(char) < 32 for char in value)
        and not any(part.lower() in IGNORED_PARTS or part.startswith(".env") for part in path.parts)
        and not lower.startswith(
            ("secret.", "secrets.", "credential.", "credentials.", "id_rsa", "id_ed25519")
        )
        and (
            lower in MANIFESTS
            or lower.startswith(("readme", "architecture.", "design."))
            or path.suffix.lower() in EXTENSIONS
            or path.suffix.lower() == ".csproj"
        )
    )


def _priority(value: str) -> tuple[int, int, str]:
    path = PurePosixPath(value)
    name = path.name.lower()
    if name.startswith(("readme", "architecture.")):
        score = 0
    elif name in MANIFESTS or name.endswith(".csproj"):
        score = 1
    elif path.stem.lower() in {
        "main",
        "app",
        "server",
        "index",
        "program",
        "application",
        "manage",
        "__main__",
    } or name.endswith("application.java"):
        score = 2
    elif any(
        part.lower()
        in {"controller", "controllers", "routes", "router", "services", "models", "entities"}
        for part in path.parts
    ):
        score = 3
    else:
        score = 4
    return score, len(path.parts), value


def _opened_path(descriptor: int) -> Path:
    if os.name != "nt":
        return Path(f"/proc/self/fd/{descriptor}").resolve(strict=True)
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    operation = kernel.GetFinalPathNameByHandleW
    operation.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    operation.restype = wintypes.DWORD
    buffer = ctypes.create_unicode_buffer(32768)
    size = operation(msvcrt.get_osfhandle(descriptor), buffer, len(buffer), 0)
    if not size or size >= len(buffer):
        raise OSError("Cannot resolve opened source path")
    name = buffer.value
    if name.startswith("\\\\?\\UNC\\"):
        name = "\\\\" + name[8:]
    elif name.startswith("\\\\?\\"):
        name = name[4:]
    return Path(name).resolve(strict=True)


def _read(root: Path, relative: str) -> tuple[str, bool, bool] | None:
    path = root
    try:
        for part in PurePosixPath(relative).parts:
            path = path / part
            if path.is_symlink() or path.is_junction():
                return None
        if not stat.S_ISREG(path.stat(follow_symlinks=False).st_mode):
            return None
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_BINARY", 0),
        )
        with os.fdopen(descriptor, "rb") as source:
            opened = _opened_path(source.fileno())
            metadata = os.fstat(source.fileno())
            if not opened.is_relative_to(root) or not stat.S_ISREG(metadata.st_mode):
                return None
            if metadata.st_size > 128000:
                return None
            raw = source.read(128001)
        if len(raw) > 128000 or b"\x00" in raw:
            return None
        text = raw.decode("utf-8-sig")
    except (UnicodeDecodeError, FileNotFoundError):
        return None
    except OSError:
        raise github_problem(
            "architecture_read_failed", f"无法读取仓库文件：{relative}", 409
        ) from None
    if re.search(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----", text):
        return None
    sanitized = SECRET_ASSIGNMENT.sub(lambda item: item[1] + item[2] + "[REDACTED]" + item[2], text)
    sanitized = SECRET_XML.sub(r"\1[REDACTED]\2", sanitized)
    sanitized = KNOWN_TOKEN.sub("[REDACTED]", sanitized)
    sanitized = URI_CREDENTIAL.sub(r"\1[REDACTED]@", sanitized)
    sanitized = re.sub(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b", "[REDACTED]", sanitized)
    sanitized = SECRET_UNQUOTED.sub(r"\1[REDACTED]", sanitized)
    return sanitized[:MAX_EXCERPT], len(sanitized) > MAX_EXCERPT, sanitized != text


def read_snapshot(workspace: DesktopWorkspace, directory: str) -> RepositorySnapshot:
    root, branch = workspace.inspect(directory)
    names = workspace.source_paths(root)
    if len(names) > 2_000_000:
        raise github_problem(
            "architecture_repository_too_large",
            "仓库文件清单超出本次分析容量，请选择较小的项目工作目录",
            422,
        )
    all_paths = set(names.split("\0")) - {""}
    eligible = sorted((name for name in all_paths if _eligible(name)), key=_priority)
    sources: list[ArchitectureSource] = []
    size = 0
    excluded = len(all_paths) - len(eligible)
    for name in eligible:
        if len(sources) >= MAX_SOURCES or size >= MAX_CHARACTERS:
            break
        loaded = _read(root, name)
        if loaded is None:
            excluded += 1
            continue
        content, truncated, redacted = loaded
        limit = min(MAX_EXCERPT, MAX_CHARACTERS - size)
        truncated = truncated or len(content) > limit
        content = content[:limit]
        if not content.strip():
            excluded += 1
            continue
        sources.append(
            ArchitectureSource(
                id=f"S{len(sources) + 1}",
                path=name,
                content=content,
                end_line=len(content.splitlines()),
                truncated=truncated,
                redacted=redacted,
            )
        )
        size += len(content)
    if not sources:
        raise github_problem(
            "architecture_no_sources", "未找到可读取的源码或项目清单，请检查仓库内容", 422
        )
    head = workspace.head(root)
    digest = hashlib.sha256(
        json.dumps(
            {
                "paths": sorted(eligible),
                "head": head,
                "branch": branch,
                "sources": [source.model_dump() for source in sources],
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return RepositorySnapshot(
        branch=branch,
        head=head,
        digest=digest,
        eligible_files=len(eligible),
        sources=sources,
        paths=sorted(eligible)[:300],
        excluded_files=excluded,
        truncated=len(sources) < len(eligible) or any(source.truncated for source in sources),
    )
