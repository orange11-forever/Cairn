from collections.abc import Collection
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePath

NORMAL_FILE_MAX_BYTES = 50 * 1024 * 1024
ARCHIVE_MAX_BYTES = 100 * 1024 * 1024
TOP_LEVEL_FILE_LIMIT = 20


class SupportedMediaType(StrEnum):
    PDF = "application/pdf"
    DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    CSV = "text/csv"
    HTML = "text/html"
    TEXT = "text/plain"
    MARKDOWN = "text/markdown"
    ZIP = "application/zip"


@dataclass(frozen=True)
class MediaDescriptor:
    extension: str
    media_type: str
    is_archive: bool
    max_bytes: int


class MediaValidationError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)

    def __str__(self) -> str:
        return "upload media validation failed"

    def __repr__(self) -> str:
        return f"MediaValidationError(code={self.code!r})"


@dataclass(frozen=True)
class _MediaPolicy:
    canonical_media_type: SupportedMediaType
    accepted_media_types: frozenset[str]
    is_archive: bool = False
    opc_core_member: str | None = None


_DOCX = SupportedMediaType.DOCX
_PPTX = SupportedMediaType.PPTX
_XLSX = SupportedMediaType.XLSX
_POLICIES = {
    ".pdf": _MediaPolicy(SupportedMediaType.PDF, frozenset({"application/pdf"})),
    ".docx": _MediaPolicy(
        _DOCX,
        frozenset({_DOCX}),
        opc_core_member="word/document.xml",
    ),
    ".pptx": _MediaPolicy(
        _PPTX,
        frozenset({_PPTX}),
        opc_core_member="ppt/presentation.xml",
    ),
    ".xlsx": _MediaPolicy(
        _XLSX,
        frozenset({_XLSX}),
        opc_core_member="xl/workbook.xml",
    ),
    ".csv": _MediaPolicy(
        SupportedMediaType.CSV,
        frozenset({"text/csv", "application/csv"}),
    ),
    ".html": _MediaPolicy(SupportedMediaType.HTML, frozenset({"text/html"})),
    ".htm": _MediaPolicy(SupportedMediaType.HTML, frozenset({"text/html"})),
    ".txt": _MediaPolicy(SupportedMediaType.TEXT, frozenset({"text/plain"})),
    ".md": _MediaPolicy(
        SupportedMediaType.MARKDOWN,
        frozenset({"text/markdown", "text/x-markdown"}),
    ),
    ".markdown": _MediaPolicy(
        SupportedMediaType.MARKDOWN,
        frozenset({"text/markdown", "text/x-markdown"}),
    ),
    ".zip": _MediaPolicy(
        SupportedMediaType.ZIP,
        frozenset({"application/zip", "application/x-zip-compressed"}),
        is_archive=True,
    ),
}


def _safe_extension(file_name: str) -> str:
    if (
        not file_name
        or file_name != file_name.strip()
        or file_name in {".", ".."}
        or "/" in file_name
        or "\\" in file_name
        or "\x00" in file_name
        or any(ord(character) < 32 for character in file_name)
    ):
        raise MediaValidationError("unsupported_media_type")
    extension = PurePath(file_name).suffix.lower()
    if extension not in _POLICIES:
        raise MediaValidationError("unsupported_media_type")
    return extension


def validate_upload_intent(
    *,
    file_name: str,
    declared_media_type: str,
    size_bytes: int,
) -> MediaDescriptor:
    extension = _safe_extension(file_name)
    policy = _POLICIES[extension]
    declared = declared_media_type.partition(";")[0].strip().lower()
    if declared not in policy.accepted_media_types:
        raise MediaValidationError("upload_media_type_mismatch")
    max_bytes = ARCHIVE_MAX_BYTES if policy.is_archive else NORMAL_FILE_MAX_BYTES
    if size_bytes <= 0 or size_bytes > max_bytes:
        raise MediaValidationError("file_too_large")
    return MediaDescriptor(
        extension=extension,
        media_type=policy.canonical_media_type,
        is_archive=policy.is_archive,
        max_bytes=max_bytes,
    )


def _looks_like_zip(prefix: bytes) -> bool:
    return prefix.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"))


def _verify_text(prefix: bytes, *, allow_gb18030: bool) -> None:
    if not prefix or b"\x00" in prefix:
        raise MediaValidationError("upload_media_type_mismatch")
    encodings = ("utf-8-sig", "gb18030") if allow_gb18030 else ("utf-8-sig",)
    decoded: str | None = None
    for encoding in encodings:
        try:
            decoded = prefix.decode(encoding, errors="strict")
            break
        except UnicodeDecodeError:
            continue
    if decoded is None:
        raise MediaValidationError("upload_media_type_mismatch")
    disallowed_controls = sum(
        character < " " and character not in "\t\r\n" for character in decoded
    )
    if disallowed_controls > max(1, len(decoded) // 100):
        raise MediaValidationError("upload_media_type_mismatch")


def verify_signature(
    *,
    descriptor: MediaDescriptor,
    prefix: bytes,
    opc_members: Collection[str] = (),
) -> None:
    policy = _POLICIES.get(descriptor.extension)
    if policy is None or policy.canonical_media_type != descriptor.media_type:
        raise MediaValidationError("upload_media_type_mismatch")
    if descriptor.media_type == SupportedMediaType.PDF:
        if not prefix.startswith(b"%PDF-"):
            raise MediaValidationError("upload_media_type_mismatch")
        return
    if descriptor.is_archive or policy.opc_core_member is not None:
        if not _looks_like_zip(prefix):
            raise MediaValidationError("upload_media_type_mismatch")
        if policy.opc_core_member is not None:
            members = set(opc_members)
            if (
                "[Content_Types].xml" not in members
                or policy.opc_core_member not in members
            ):
                raise MediaValidationError("upload_media_type_mismatch")
        return
    _verify_text(prefix, allow_gb18030=descriptor.media_type == SupportedMediaType.CSV)


__all__ = [
    "ARCHIVE_MAX_BYTES",
    "NORMAL_FILE_MAX_BYTES",
    "TOP_LEVEL_FILE_LIMIT",
    "MediaDescriptor",
    "MediaValidationError",
    "SupportedMediaType",
    "validate_upload_intent",
    "verify_signature",
]
