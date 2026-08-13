import stat
from io import BytesIO
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZipFile

# These package-only limits are intentionally separate from the public 50 MiB source limit.
# They bound central-directory work and decompression before an Office library sees the package.
OPC_MAX_ENTRIES = 2_000
OPC_MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
OPC_MAX_ENTRY_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
OPC_MAX_COMPRESSION_RATIO = 100

_CONTENT_TYPES_MEMBER = "[Content_Types].xml"
_MACRO_MEMBER_NAMES = ("vbaproject.bin", "vbadata.xml")
_MACRO_CONTENT_MARKERS = (b"macroenabled", b"vnd.ms-office.vbaproject")
_ENCRYPTED_PACKAGE_MEMBERS = frozenset({"encryptioninfo", "encryptedpackage"})
_XML_ENTITY_MARKERS = (b"<!doctype", b"<!entity")


def _is_unsafe_member_name(name: str) -> bool:
    if not name or name.startswith(("/", "\\")) or "\\" in name or "\x00" in name:
        return True
    path = PurePosixPath(name.rstrip("/"))
    return any(part in {"", ".", ".."} for part in path.parts) or (
        bool(path.parts) and path.parts[0].endswith(":")
    )


def validate_opc_package(content: bytes, *, required_member: str) -> None:
    try:
        with ZipFile(BytesIO(content), "r") as package:
            members = package.infolist()
            if not members or len(members) > OPC_MAX_ENTRIES:
                raise ValueError("invalid OPC entry count")

            seen: set[str] = set()
            aggregate_size = 0
            content_types: bytes | None = None
            for member in members:
                name = member.filename
                normalized_name = name.rstrip("/")
                if _is_unsafe_member_name(name) or normalized_name in seen:
                    raise ValueError("unsafe OPC entry")
                seen.add(normalized_name)

                mode = (member.external_attr >> 16) & 0xFFFF
                if member.flag_bits & 1 or (mode and stat.S_ISLNK(mode)):
                    raise ValueError("hazardous OPC entry")
                if member.file_size > OPC_MAX_ENTRY_UNCOMPRESSED_BYTES:
                    raise ValueError("OPC entry exceeds expansion limit")
                aggregate_size += member.file_size
                if aggregate_size > OPC_MAX_UNCOMPRESSED_BYTES:
                    raise ValueError("OPC package exceeds expansion limit")
                if member.file_size and (
                    member.compress_size == 0
                    or member.file_size / member.compress_size > OPC_MAX_COMPRESSION_RATIO
                ):
                    raise ValueError("OPC entry exceeds compression-ratio limit")

                lowered_name = normalized_name.lower()
                if lowered_name.endswith(_MACRO_MEMBER_NAMES):
                    raise ValueError("macro-bearing OPC package")
                if PurePosixPath(lowered_name).name in _ENCRYPTED_PACKAGE_MEMBERS:
                    raise ValueError("encrypted OPC package")
                if lowered_name.endswith((".xml", ".rels")):
                    xml_content = package.read(member).lower()
                    if any(marker in xml_content for marker in _XML_ENTITY_MARKERS):
                        raise ValueError("unsafe XML entity declaration")
                    if normalized_name == _CONTENT_TYPES_MEMBER:
                        content_types = xml_content

            if _CONTENT_TYPES_MEMBER not in seen or required_member not in seen:
                raise ValueError("OPC package is missing a required member")
            if content_types is None:
                raise ValueError("OPC package is missing content types")
            if any(marker in content_types for marker in _MACRO_CONTENT_MARKERS):
                raise ValueError("macro-bearing OPC package")
    except (BadZipFile, OSError, RuntimeError, ValueError):
        raise ValueError("unsafe or malformed OPC package") from None


__all__ = ["validate_opc_package"]
