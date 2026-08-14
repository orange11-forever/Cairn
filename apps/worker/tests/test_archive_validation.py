import struct
from collections.abc import Sequence
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

import pytest
from cairn_worker.archive import inspect_archive
from cairn_worker.errors import WorkerFailure


def _archive(
    entries: Sequence[tuple[str | ZipInfo, bytes]], *, compression: int = ZIP_STORED
) -> bytes:
    target = BytesIO()
    with ZipFile(target, "w", compression=compression) as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return target.getvalue()


def _patch_flags(payload: bytes, flag: int) -> bytes:
    changed = bytearray(payload)
    local = changed.index(b"PK\x03\x04")
    central = changed.index(b"PK\x01\x02")
    struct.pack_into("<H", changed, local + 6, flag)
    struct.pack_into("<H", changed, central + 8, flag)
    return bytes(changed)


def _patch_declared_size(payload: bytes, size: int) -> bytes:
    changed = bytearray(payload)
    central = changed.index(b"PK\x01\x02")
    struct.pack_into("<I", changed, central + 24, size)
    return bytes(changed)


def _patch_all_declared_sizes(payload: bytes, size: int) -> bytes:
    changed = bytearray(payload)
    offset = 0
    while True:
        try:
            central = changed.index(b"PK\x01\x02", offset)
        except ValueError:
            break
        struct.pack_into("<I", changed, central + 20, size)
        struct.pack_into("<I", changed, central + 24, size)
        offset = central + 4
    return bytes(changed)


def _patch_crc(payload: bytes, crc: int) -> bytes:
    changed = bytearray(payload)
    local = changed.index(b"PK\x03\x04")
    central = changed.index(b"PK\x01\x02")
    struct.pack_into("<I", changed, local + 14, crc)
    struct.pack_into("<I", changed, central + 16, crc)
    return bytes(changed)


def _nul_name_archive() -> bytes:
    changed = bytearray(_archive([("nulXname.txt", b"safe text")]))
    first = changed.index(b"nulXname.txt")
    second = changed.index(b"nulXname.txt", first + 1)
    changed[first + 3] = 0
    changed[second + 3] = 0
    return bytes(changed)


@pytest.mark.parametrize(
    "name",
    [
        "/absolute.txt",
        "C:/windows.txt",
        "C:\\windows.txt",
        "\\\\server\\share\\file.txt",
        "../escape.txt",
        "safe/../../escape.txt",
        "safe\\..\\escape.txt",
    ],
)
def test_rejects_unsafe_absolute_traversal_and_nul_paths(name: str) -> None:
    """Break caught: untrusted entry names must never escape the logical archive tree."""
    with pytest.raises(WorkerFailure) as raised:
        inspect_archive(BytesIO(_archive([(name, b"safe text")])))

    assert raised.value.code == "archive_path_unsafe"


def test_rejects_nul_in_the_raw_central_directory_name() -> None:
    """Break caught: stdlib display-name truncation must not hide a raw NUL path alias."""
    with pytest.raises(WorkerFailure) as raised:
        inspect_archive(BytesIO(_nul_name_archive()))

    assert raised.value.code == "archive_path_unsafe"


@pytest.mark.parametrize(
    "names",
    [
        ("Folder/Report.TXT", "folder/report.txt"),
        ("caf\N{LATIN SMALL LETTER E WITH ACUTE}.txt", "cafe\N{COMBINING ACUTE ACCENT}.txt"),
        ("folder\\report.txt", "folder/report.txt"),
    ],
)
def test_rejects_duplicate_file_paths_after_nfkc_separator_and_case_normalization(
    names: tuple[str, str],
) -> None:
    """Break caught: aliases must not create two children for one normalized logical path."""
    with pytest.raises(WorkerFailure) as raised:
        inspect_archive(BytesIO(_archive([(names[0], b"one"), (names[1], b"two")])))

    assert raised.value.code == "archive_duplicate_path"


def test_rejects_duplicate_directory_paths_without_counting_them_as_files() -> None:
    """Break caught: directory aliases must not bypass archive-wide duplicate detection."""
    payload = _archive([("Folder/", b""), ("folder/", b""), ("folder/file.txt", b"x")])

    with pytest.raises(WorkerFailure) as raised:
        inspect_archive(BytesIO(payload))

    assert raised.value.code == "archive_duplicate_path"


def test_rejects_unix_symlink_entries() -> None:
    """Break caught: ZIP symlink metadata must not be treated as an ordinary file."""
    link = ZipInfo("link.txt")
    link.create_system = 3
    link.external_attr = 0o120777 << 16

    with pytest.raises(WorkerFailure) as raised:
        inspect_archive(BytesIO(_archive([(link, b"target.txt")])))

    assert raised.value.code == "archive_path_unsafe"


def test_rejects_encrypted_entry_flags_before_reading_content() -> None:
    """Break caught: encrypted members must be rejected even when their bytes look benign."""
    payload = _patch_flags(_archive([("secret.txt", b"not actually encrypted")]), 1)

    with pytest.raises(WorkerFailure) as raised:
        inspect_archive(BytesIO(payload))

    assert raised.value.code == "archive_encrypted"


@pytest.mark.parametrize(
    ("name", "content"),
    [("nested.zip", b"plain"), ("renamed.bin", b"PK\x03\x04nested archive")],
)
def test_rejects_nested_archives_by_extension_or_signature(name: str, content: bytes) -> None:
    """Break caught: renaming a nested ZIP must not bypass recursive archive rejection."""
    with pytest.raises(WorkerFailure) as raised:
        inspect_archive(BytesIO(_archive([(name, content)])))

    assert raised.value.code == "archive_nested"


def test_directories_do_not_count_toward_the_two_hundred_file_limit() -> None:
    """Break caught: harmless directory records must not consume the bounded file allowance."""
    entries = [(f"tree/{index}/", b"") for index in range(205)]
    entries.extend((f"tree/{index}/file.txt", b"x") for index in range(200))

    plans = inspect_archive(BytesIO(_archive(entries)))

    assert len(plans) == 200


def test_rejects_more_than_two_hundred_file_entries() -> None:
    """Break caught: file-count bombs must be stopped from creating unbounded child facts."""
    entries = [(f"entry-{index}.txt", b"x") for index in range(201)]

    with pytest.raises(WorkerFailure) as raised:
        inspect_archive(BytesIO(_archive(entries)))

    assert raised.value.code == "archive_limit_exceeded"


@pytest.mark.parametrize(
    ("declared_size", "entry_count"),
    [
        (50 * 1024 * 1024 + 1, 1),
        (50 * 1024 * 1024, 11),
    ],
    ids=["entry", "aggregate"],
)
def test_rejects_declared_entry_and_aggregate_expansion_limits(
    declared_size: int, entry_count: int
) -> None:
    """Break caught: trusted work bounds must use central-directory sizes before extraction."""
    entries = [(f"entry-{index}.txt", b"x") for index in range(entry_count)]
    payload = _archive(entries)
    payload = (
        _patch_declared_size(payload, declared_size)
        if entry_count == 1
        else _patch_all_declared_sizes(payload, declared_size)
    )

    with pytest.raises(WorkerFailure) as raised:
        inspect_archive(BytesIO(payload))

    assert raised.value.code == "archive_limit_exceeded"


def test_rejects_per_entry_and_archive_compression_ratios_over_one_hundred() -> None:
    """Break caught: highly compressible data must not turn small ZIPs into expansion bombs."""
    payload = _archive([("bomb.txt", b"0" * 100_000)], compression=ZIP_DEFLATED)

    with pytest.raises(WorkerFailure) as raised:
        inspect_archive(BytesIO(payload))

    assert raised.value.code == "archive_limit_exceeded"


def test_rejects_crc_mismatch_instead_of_returning_valid_looking_siblings() -> None:
    """Break caught: corrupt content must invalidate the archive-wide plan."""
    payload = _archive([("valid.txt", b"valid"), ("corrupt.txt", b"corrupt")])
    payload = _patch_crc(payload, 0)

    with pytest.raises(WorkerFailure) as raised:
        inspect_archive(BytesIO(payload))

    assert raised.value.code == "parser_failed"
    assert raised.value.retryable is False


def test_rejects_read_size_mismatch() -> None:
    """Break caught: a member yielding fewer bytes than declared must invalidate the archive."""
    payload = _patch_declared_size(_archive([("short.txt", b"short")]), 6)

    with pytest.raises(WorkerFailure) as raised:
        inspect_archive(BytesIO(payload))

    assert raised.value.code == "parser_failed"
    assert raised.value.retryable is False


def test_rejects_a_corrupt_central_directory_with_a_bounded_failure() -> None:
    """Break caught: malformed ZIP metadata must not leak parser details or publish children."""
    payload = _archive([("valid.txt", b"valid")])[:-12]

    with pytest.raises(WorkerFailure) as raised:
        inspect_archive(BytesIO(payload))

    assert (raised.value.code, raised.value.safe_detail) == (
        "parser_failed",
        "worker handler or parser failed",
    )
    assert raised.value.retryable is False


def test_accepts_and_nfkc_normalizes_a_unicode_directory_tree() -> None:
    """Break caught: safe Unicode directory trees must remain ingestible and deterministic."""
    payload = _archive(
        [
            ("资料/", b""),
            ("资料/Ｒｅｐｏｒｔ.txt", b"hello"),
            ("资料/notes.exe", b"binary"),
        ]
    )

    plans = inspect_archive(BytesIO(payload))

    assert [(plan.normalized_path, plan.error_code) for plan in plans] == [
        ("资料/Report.txt", None),
        ("资料/notes.exe", "unsupported_media_type"),
    ]
    assert plans[0].media is not None and plans[0].media.media_type == "text/plain"
    assert plans[1].media is None
