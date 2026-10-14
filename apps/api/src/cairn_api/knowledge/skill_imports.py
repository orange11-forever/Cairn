import base64
import hashlib
import json
import re
import stat
import time
import zlib
from importlib import import_module
from io import BytesIO
from pathlib import PurePosixPath
from typing import Any, cast
from urllib.parse import quote, urlsplit
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile

import httpx

from cairn_api.errors import ApiProblem
from cairn_api.knowledge.assistant_schemas import (
    KnowledgeSkillPreview,
    SkillImportSource,
    SkillResource,
)

MAX_FILE_BYTES = 65536
MAX_PACKAGE_BYTES = 262144
TEXT_EXTENSIONS = {".md", ".txt", ".csv", ".json", ".yaml", ".yml", ".rst", ".toml"}
SCRIPT_EXTENSIONS = {".py", ".sh", ".js", ".ts", ".exe", ".bat", ".cmd", ".ps1", ".rb"}
ARCHIVE_EXTENSIONS = {".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar"}


def _invalid() -> ApiProblem:
    return ApiProblem(
        status_code=422, code="invalid_skill", message="技能格式或依赖不符合当前只读导入要求"
    )


def _safe_path(value: str) -> str:
    if not value or len(value) > 500 or "\\" in value or "\x00" in value or value.startswith("/"):
        raise _invalid()
    parts = value.rstrip("/").split("/")
    if any(part in {"", ".", ".."} for part in parts) or len(parts) > 12:
        raise _invalid()
    return "/".join(parts)


def _decode(data: bytes) -> str:
    if len(data) > MAX_FILE_BYTES:
        raise _invalid()
    try:
        value = data.decode("utf-8-sig")
        if "\x00" in value:
            raise _invalid()
        return value
    except UnicodeError:
        raise _invalid() from None


def _frontmatter(text: str) -> tuple[str, str, str, list[str]]:
    text = text.replace("\r\n", "\n")
    if not text.startswith("---\n"):
        raise _invalid()
    end = text.find("\n---\n", 4)
    if end < 0 or len(text[:end].encode("utf-8")) > 8192:
        raise _invalid()
    header, body = text[4:end], text[end + 5 :].strip()
    yaml = cast(Any, import_module("yaml"))
    try:
        depth = 0
        for count, event in enumerate(yaml.parse(header, Loader=yaml.SafeLoader), 1):
            if (
                count > 1024
                or getattr(event, "anchor", None) is not None
                or isinstance(event, yaml.AliasEvent)
            ):
                raise ValueError()
            tag = getattr(event, "tag", None)
            if tag is not None and not tag.startswith("tag:yaml.org,2002:"):
                raise ValueError()
            if isinstance(event, (yaml.MappingStartEvent, yaml.SequenceStartEvent)):
                depth += 1
                if depth > 12:
                    raise ValueError()
            elif isinstance(event, (yaml.MappingEndEvent, yaml.SequenceEndEvent)):
                depth -= 1
        node = yaml.compose(header, Loader=yaml.SafeLoader)

        def validate(node: Any) -> None:
            if isinstance(node, yaml.MappingNode):
                names: set[str] = set()
                for key, value in node.value:
                    if (
                        not isinstance(key, yaml.ScalarNode)
                        or key.tag != "tag:yaml.org,2002:str"
                        or key.value in names
                    ):
                        raise ValueError()
                    names.add(key.value)
                    validate(value)
            elif isinstance(node, yaml.SequenceNode):
                for value in node.value:
                    validate(value)

        validate(node)
        metadata: object = yaml.safe_load(header)
        if not isinstance(metadata, dict):
            raise TypeError()
        typed = cast(dict[str, object], metadata)
        name, description = typed.get("name"), typed.get("description")
        if not isinstance(name, str) or not isinstance(description, str):
            raise TypeError()
        name, description = name.strip(), description.strip()
        if not 1 <= len(name) <= 60 or not 1 <= len(description) <= 2000 or not body:
            raise ValueError()
        warnings = (
            ["声明了工具或外部依赖，当前只读助手不能运行。"]
            if any(typed.get(key) for key in ("allowed-tools", "tools", "dependencies", "requires"))
            else []
        )
        return name, description, body, warnings
    except Exception:  # noqa: BLE001
        raise _invalid() from None


def _github(source: SkillImportSource, client: httpx.Client | None) -> tuple[bytes, dict[str, str]]:
    assert source.type == "github"
    parsed = urlsplit(source.url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "github.com"
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise _invalid()
    parts = parsed.path.strip("/").split("/")
    if len(parts) < 2 or any(
        not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", item) or item in {".", ".."}
        for item in parts[:2]
    ):
        raise _invalid()
    owner, repo = parts[:2]
    inferred_path, inferred_ref = "SKILL.md", None
    if len(parts) > 2:
        if len(parts) < 4 or parts[2] not in {"blob", "tree"}:
            raise _invalid()
        inferred_ref = parts[3]
        inferred_path = "/".join(parts[4:])
        if parts[2] == "tree":
            inferred_path = inferred_path.rstrip("/") + "/SKILL.md" if inferred_path else "SKILL.md"
    path, ref = _safe_path(source.path or inferred_path), source.ref or inferred_ref
    if ref is not None and (len(ref) > 128 or any(character in ref for character in "\x00\r\n")):
        raise _invalid()
    endpoint = f"https://api.github.com/repos/{quote(owner, safe='')}/{quote(repo, safe='')}/contents/{quote(path, safe='/')}"
    owned = client is None
    transport = client or httpx.Client(timeout=10, follow_redirects=False, trust_env=False)
    started = time.monotonic()
    try:
        with transport.stream(
            "GET",
            endpoint,
            params={} if ref is None else {"ref": ref},
            headers={"Accept": "application/vnd.github+json"},
            timeout=10,
            follow_redirects=False,
        ) as response:
            if response.status_code != 200:
                raise ValueError()
            content = bytearray()
            for chunk in response.iter_bytes():
                if time.monotonic() - started > 10 or len(content) + len(chunk) > 131072:
                    raise ValueError()
                content.extend(chunk)
        payload: object = json.loads(content)
        if not isinstance(payload, dict):
            raise TypeError()
        data = cast(dict[str, object], payload)
        encoded = data.get("content")
        if (
            data.get("type") != "file"
            or data.get("encoding") != "base64"
            or not isinstance(encoded, str)
        ):
            raise ValueError()
        decoded = base64.b64decode(encoded.replace("\n", ""), validate=True)
        metadata = {
            "url": source.url,
            "path": path,
            "ref": ref or "default",
            "sha": str(data.get("sha", ""))[:128],
        }
        return decoded, metadata
    except Exception:  # noqa: BLE001
        raise ApiProblem(
            status_code=503, code="skill_import_unavailable", message="公开 GitHub 技能暂时无法读取"
        ) from None
    finally:
        if owned:
            transport.close()


def preview_skill(
    source: SkillImportSource, *, client: httpx.Client | None = None
) -> KnowledgeSkillPreview:
    try:
        references: list[SkillResource] = []
        warnings: list[str] = []
        if source.type == "github":
            raw, metadata = _github(source, client)
            text = _decode(raw)
        elif source.type == "markdown":
            _safe_path(source.file_name)
            raw = source.content.encode("utf-8")
            text = _decode(raw)
            metadata = {"fileName": source.file_name, "rawDigest": hashlib.sha256(raw).hexdigest()}
        else:
            _safe_path(source.file_name)
            raw = base64.b64decode(source.content_base64, validate=True)
            if len(raw) > MAX_PACKAGE_BYTES:
                raise _invalid()
            with ZipFile(BytesIO(raw)) as archive:
                entries = archive.infolist()
                if len(entries) > 32:
                    raise _invalid()
                names: set[str] = set()
                files: dict[str, bytes] = {}
                total = 0
                for entry in entries:
                    path = _safe_path(entry.filename)
                    if (
                        path in names
                        or entry.flag_bits & 1
                        or stat.S_ISLNK(entry.external_attr >> 16)
                    ):
                        raise _invalid()
                    names.add(path)
                    if entry.is_dir():
                        continue
                    if entry.compress_type not in {ZIP_STORED, ZIP_DEFLATED}:
                        raise _invalid()
                    total += entry.file_size
                    if (
                        entry.file_size > MAX_FILE_BYTES
                        or total > MAX_PACKAGE_BYTES
                        or (
                            entry.file_size > 4096
                            and entry.file_size > 100 * max(entry.compress_size, 1)
                        )
                        or PurePosixPath(path).suffix.lower() in ARCHIVE_EXTENSIONS
                    ):
                        raise _invalid()
                    with archive.open(entry) as stream:
                        data = stream.read(MAX_FILE_BYTES + 1)
                    if len(data) != entry.file_size:
                        raise _invalid()
                    if entry.external_attr >> 16 & 0o111:
                        warnings.append("包含可执行文件，当前助手不会运行此技能包。")
                    files[path] = data
                skill_paths = [path for path in files if PurePosixPath(path).name == "SKILL.md"]
                if len(skill_paths) != 1 or len(skill_paths[0].split("/")) > 2:
                    raise _invalid()
                skill_path = skill_paths[0]
                root = str(PurePosixPath(skill_path).parent)
                if root != "." and any(not path.startswith(root + "/") for path in files):
                    raise _invalid()
                text = _decode(files[skill_path])
                for path, data in files.items():
                    if path == skill_path:
                        continue
                    extension = PurePosixPath(path).suffix.lower()
                    if extension in SCRIPT_EXTENSIONS:
                        warnings.append("包含可执行脚本，当前助手不会运行此技能包。")
                    elif extension not in TEXT_EXTENSIONS:
                        warnings.append("包含不支持的二进制或文件依赖，当前助手不能运行。")
                    else:
                        references.append(SkillResource(path=path, content=_decode(data)))
                metadata = {
                    "fileName": source.file_name,
                    "rawDigest": hashlib.sha256(raw).hexdigest(),
                }
        name, description, body, declared = _frontmatter(text)
        warnings = list(dict.fromkeys(warnings + declared))
        if len(body) + sum(len(item.content) for item in references) > 16000:
            raise _invalid()
        preview = KnowledgeSkillPreview(
            name=name,
            description=description,
            defaultQuestion=f"请使用“{name}”分析当前项目资料并给出引用。",
            capabilities=["knowledge.read"],
            sourceType=source.type,
            sourceMetadata=metadata,
            runnable=not warnings,
            warnings=warnings,
            body=body,
            resources=references,
            digest="",
        )
        preview.digest = hashlib.sha256(
            json.dumps(
                preview.model_dump(mode="json", exclude={"digest"}),
                sort_keys=True,
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        return preview
    except ApiProblem:
        raise
    except (ValueError, UnicodeError, BadZipFile, OSError, NotImplementedError, zlib.error):
        raise _invalid() from None
