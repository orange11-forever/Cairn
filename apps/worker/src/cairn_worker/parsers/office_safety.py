import re
import stat
import unicodedata
from io import BytesIO
from pathlib import PurePosixPath
from urllib.parse import unquote_to_bytes
from xml.parsers import expat
from zipfile import BadZipFile, ZipFile, ZipInfo

# These package-only limits are intentionally separate from the public 50 MiB source limit.
# They bound central-directory work and decompression before an Office library sees the package.
OPC_MAX_ENTRIES = 2_000
OPC_MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
OPC_MAX_ENTRY_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
OPC_MAX_COMPRESSION_RATIO = 100
OPC_MAX_XML_DECODED_CHARACTERS = 100 * 1024 * 1024
OPC_MAX_XML_ELEMENTS = 2_000_000
OPC_MAX_XML_TEXT_CHARACTERS = 50 * 1024 * 1024
_OPC_READ_CHUNK_BYTES = 64 * 1024

_CONTENT_TYPES_MEMBER = "[Content_Types].xml"
_MACRO_MEMBER_NAMES = ("vbaproject.bin", "vbadata.xml")
_MACRO_CONTENT_MARKERS = ("macroenabled", "vnd.ms-office.vbaproject")
_ENCRYPTED_PACKAGE_MEMBERS = frozenset({"encryptioninfo", "encryptedpackage"})
_XML_ENTITY_MARKERS = ("<!doctype", "<!entity")
_ENCODING_DECLARATION = re.compile(r"<\?xml\s[^>]*encoding\s*=\s*['\"]([^'\"]+)", re.IGNORECASE)
_PERCENT_ESCAPE = re.compile(r"%[0-9a-fA-F]{2}")


def _canonical_opc_path(name: str) -> str:
    if any(character == "%" for character in name):
        escapes = _PERCENT_ESCAPE.findall(name)
        if len(escapes) != name.count("%"):
            raise ValueError("invalid percent escape in OPC path")
        if re.search(r"%(?:2e|2f|5c)", name, re.IGNORECASE):
            raise ValueError("encoded separator or dot in OPC path")
    raw_path = name.removesuffix("/")
    if "//" in raw_path or any(
        part in {"", ".", ".."} for part in raw_path.split("/")
    ):
        raise ValueError("ambiguous OPC path")
    decoded = unquote_to_bytes(name).decode("utf-8", errors="strict")
    normalized = unicodedata.normalize("NFC", decoded).rstrip("/")
    if (
        not normalized
        or normalized.startswith(("/", "\\"))
        or "\\" in normalized
        or "\x00" in normalized
    ):
        raise ValueError("unsafe OPC path")
    path = PurePosixPath(normalized)
    if any(part in {"", ".", ".."} for part in path.parts) or (
        bool(path.parts) and path.parts[0].endswith(":")
    ):
        raise ValueError("unsafe OPC path")
    return normalized.casefold()


def _decode_xml(content: bytes) -> str:
    if content.startswith(b"\xef\xbb\xbf"):
        codec = "utf-8-sig"
        family = "utf-8"
    elif content.startswith(b"\xff\xfe"):
        codec = "utf-16"
        family = "utf-16-le"
    elif content.startswith(b"\xfe\xff"):
        codec = "utf-16"
        family = "utf-16-be"
    elif content.startswith(b"\x00<\x00?"):
        codec = "utf-16-be"
        family = "utf-16-be"
    elif content.startswith(b"<\x00?\x00"):
        codec = "utf-16-le"
        family = "utf-16-le"
    else:
        codec = "utf-8"
        family = "utf-8"
    decoded = content.decode(codec, errors="strict")
    declaration = _ENCODING_DECLARATION.search(decoded[:512])
    if declaration is not None:
        declared = declaration.group(1).casefold().replace("_", "-")
        allowed = {family}
        if family.startswith("utf-16"):
            allowed.add("utf-16")
        if declared not in allowed:
            raise ValueError("ambiguous or unsupported XML encoding")
    return decoded


def _relationship_source(member_name: str) -> PurePosixPath:
    path = PurePosixPath(member_name)
    if path.name == ".rels" and str(path.parent) == "_rels":
        return PurePosixPath("")
    if path.parent.name != "_rels" or not path.name.endswith(".rels"):
        raise ValueError("invalid relationship part name")
    return path.parent.parent / path.name.removesuffix(".rels")


def _validate_relationship_target(member_name: str, target: str) -> None:
    if re.search(r"%(?:2e|2f|5c)", target, re.IGNORECASE):
        raise ValueError("encoded separator or dot in relationship target")
    target_path = target.removeprefix("/")
    if "//" in target_path or any(part == "." for part in target_path.split("/")):
        raise ValueError("ambiguous relationship target")
    decoded = unicodedata.normalize(
        "NFC", unquote_to_bytes(target).decode("utf-8", errors="strict")
    )
    if "\\" in decoded or "\x00" in decoded:
        raise ValueError("unsafe relationship target")
    if decoded.startswith("/"):
        _canonical_opc_path(decoded.removeprefix("/"))
        return
    source = _relationship_source(member_name)
    parts = list(source.parent.parts)
    for part in PurePosixPath(decoded).parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if not parts:
                raise ValueError("relationship target escapes package")
            parts.pop()
        else:
            parts.append(part)
    _canonical_opc_path("/".join(parts))


def _scan_xml(content: bytes, *, member_name: str, totals: list[int]) -> str:
    decoded = _decode_xml(content)
    totals[0] += len(decoded)
    if totals[0] > OPC_MAX_XML_DECODED_CHARACTERS:
        raise ValueError("OPC XML exceeds decoded-character limit")
    lowered = decoded.casefold()
    if any(marker in lowered for marker in _XML_ENTITY_MARKERS):
        raise ValueError("unsafe XML entity declaration")

    parser = expat.ParserCreate()

    def start(name: str, attributes: dict[str, str]) -> None:
        totals[1] += 1
        if totals[1] > OPC_MAX_XML_ELEMENTS:
            raise ValueError("OPC XML exceeds element limit")
        if member_name.endswith(".rels") and name.rsplit(":", 1)[-1] == "Relationship":
            mode = attributes.get("TargetMode", "")
            target = attributes.get("Target")
            if target is not None and mode.casefold() != "external":
                _validate_relationship_target(member_name, target)

    def text(data: str) -> None:
        totals[2] += len(data)
        if totals[2] > OPC_MAX_XML_TEXT_CHARACTERS:
            raise ValueError("OPC XML exceeds text limit")

    def reject_declaration(*args: object) -> None:
        del args
        raise ValueError("unsafe XML declaration")

    parser.StartElementHandler = start
    parser.CharacterDataHandler = text
    parser.StartDoctypeDeclHandler = reject_declaration
    parser.EntityDeclHandler = reject_declaration
    def reject_external_entity(
        context: str,
        base: str | None,
        system_id: str | None,
        public_id: str | None,
    ) -> int:
        del context, base, system_id, public_id
        return 0

    parser.ExternalEntityRefHandler = reject_external_entity
    parser.Parse(content, True)
    return lowered


def _read_member_checked(
    package: ZipFile,
    member: ZipInfo,
    actual_aggregate: list[int],
    *,
    retain: bool,
) -> bytes:
    retained = bytearray()
    actual_entry = 0
    with package.open(member, "r") as source:
        while chunk := source.read(_OPC_READ_CHUNK_BYTES):
            actual_entry += len(chunk)
            actual_aggregate[0] += len(chunk)
            if actual_entry > OPC_MAX_ENTRY_UNCOMPRESSED_BYTES:
                raise ValueError("OPC entry exceeds actual expansion limit")
            if actual_aggregate[0] > OPC_MAX_UNCOMPRESSED_BYTES:
                raise ValueError("OPC package exceeds actual expansion limit")
            if retain:
                retained.extend(chunk)
    return bytes(retained)


def validate_opc_package(content: bytes, *, required_member: str) -> None:
    try:
        with ZipFile(BytesIO(content), "r") as package:
            members = package.infolist()
            if not members or len(members) > OPC_MAX_ENTRIES:
                raise ValueError("invalid OPC entry count")

            seen: set[str] = set()
            exact_names: set[str] = set()
            aggregate_size = 0
            actual_aggregate = [0]
            xml_totals = [0, 0, 0]
            content_types: str | None = None
            for member in members:
                name = member.filename
                normalized_name = name.rstrip("/")
                canonical_name = _canonical_opc_path(name)
                if canonical_name in seen:
                    raise ValueError("unsafe OPC entry")
                seen.add(canonical_name)
                exact_names.add(normalized_name)

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

                lowered_name = canonical_name
                if lowered_name.endswith(_MACRO_MEMBER_NAMES):
                    raise ValueError("macro-bearing OPC package")
                if PurePosixPath(lowered_name).name in _ENCRYPTED_PACKAGE_MEMBERS:
                    raise ValueError("encrypted OPC package")
                is_xml = lowered_name.endswith((".xml", ".rels"))
                # Incrementally reading every member validates local headers, overlap boundaries,
                # actual expansion and CRC before any Office library receives the package.
                member_content = _read_member_checked(
                    package,
                    member,
                    actual_aggregate,
                    retain=is_xml,
                )
                if is_xml:
                    xml_content = _scan_xml(
                        member_content, member_name=lowered_name, totals=xml_totals
                    )
                    if normalized_name == _CONTENT_TYPES_MEMBER:
                        content_types = xml_content

            if _CONTENT_TYPES_MEMBER not in exact_names or required_member not in exact_names:
                raise ValueError("OPC package is missing a required member")
            if content_types is None:
                raise ValueError("OPC package is missing content types")
            if any(marker in content_types for marker in _MACRO_CONTENT_MARKERS):
                raise ValueError("macro-bearing OPC package")
    except (BadZipFile, EOFError, OSError, RuntimeError, ValueError):
        raise ValueError("unsafe or malformed OPC package") from None


__all__ = ["validate_opc_package"]
