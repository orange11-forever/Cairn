from collections.abc import Sequence
from dataclasses import dataclass
from io import BytesIO
from threading import RLock
from typing import BinaryIO

from cairn_api.knowledge.schemas import PdfLocator
from pypdf import PdfReader, filters
from pypdf.generic import (
    ArrayObject,
    DictionaryObject,
    IndirectObject,
    NameObject,
    NumberObject,
    StreamObject,
)

from cairn_worker.errors import WorkerFailure
from cairn_worker.parsers import BlockKind, DocumentParser, ParsedBlock, read_parser_source
from cairn_worker.parsers.limits import MAX_PARSED_BLOCKS, PARSER_SOURCE_MAX_BYTES

PDF_MAX_PAGES = MAX_PARSED_BLOCKS
PDF_MAX_PAGE_TREE_DEPTH = 128
PDF_MAX_PAGE_TREE_NODES = MAX_PARSED_BLOCKS * 4
PDF_MAX_DECOMPRESSED_STREAM_BYTES = PARSER_SOURCE_MAX_BYTES
PDF_MAX_EXTRACTED_CHARACTERS = PARSER_SOURCE_MAX_BYTES
PDF_MAX_AGGREGATE_DECODED_BYTES = PARSER_SOURCE_MAX_BYTES
PDF_MAX_CONTENT_TOKENS = 5_000_000
PDF_MAX_CONTENT_STREAMS = PDF_MAX_PAGE_TREE_NODES
PDF_MAX_FORM_DEPTH = 64

# pypdf exposes its Flate output ceiling as a module setting. Serialize the temporary stricter
# value so concurrent PDF jobs cannot observe a partially restored limit.
_PDF_PARSE_LOCK = RLock()
_PAGE = NameObject("/Page")
_PAGES = NameObject("/Pages")

type _PageTreeKey = tuple[int, int]


@dataclass(slots=True)
class _PagesFrame:
    key: _PageTreeKey
    kids: ArrayObject
    declared_count: int
    depth: int
    next_child_index: int = 0
    actual_count: int = 0


def _reference_key(reference: IndirectObject, reader: PdfReader) -> _PageTreeKey:
    if reference.pdf is not reader:
        raise ValueError("page-tree reference belongs to another PDF")
    return reference.idnum, reference.generation


def _required_raw_value(node: DictionaryObject, key: str) -> object:
    try:
        return node.raw_get(key)
    except KeyError:
        raise ValueError("page-tree node is missing a required field") from None


def _validate_parent_reference(
    node: DictionaryObject,
    reader: PdfReader,
    expected_parent: _PageTreeKey | None,
) -> None:
    if expected_parent is None:
        if "/Parent" in node:
            raise ValueError("root page-tree node has a parent")
        return
    parent = _required_raw_value(node, "/Parent")
    if not isinstance(parent, IndirectObject):
        raise TypeError("page-tree parent must be an indirect reference")
    if _reference_key(parent, reader) != expected_parent:
        raise ValueError("page-tree parent reference is inconsistent")


def _preflight_page_tree(reader: PdfReader) -> int:
    root_reference = _required_raw_value(reader.root_object, "/Pages")
    if not isinstance(root_reference, IndirectObject):
        raise TypeError("catalog /Pages must be an indirect reference")

    # Keep only one unvisited child and one frame per active ancestor. Unlike a DFS that queues
    # every sibling, this makes pending traversal state O(depth) even for nested wide trees.
    current: tuple[IndirectObject, int, _PageTreeKey | None] | None = (
        root_reference,
        1,
        None,
    )
    frames: list[_PagesFrame] = []
    seen: set[_PageTreeKey] = set()
    node_count = 0
    page_count = 0
    completed_pages: int | None = None

    while current is not None or frames:
        if current is None:
            if completed_pages is None:
                raise ValueError("page-tree traversal lost its completed subtree")
            frame = frames[-1]
            frame.actual_count += completed_pages
            if frame.actual_count > frame.declared_count:
                raise ValueError("page-tree /Count does not match its leaf pages")
            if frame.next_child_index < len(frame.kids):
                # The sole unvisited enter slot shares the global node budget with visited
                # nodes. Reject before even fetching or storing another child reference.
                if node_count >= PDF_MAX_PAGE_TREE_NODES:
                    raise ValueError("PDF page tree exceeds node limit")
                child = frame.kids[frame.next_child_index]
                frame.next_child_index += 1
                if not isinstance(child, IndirectObject):
                    raise TypeError("page-tree child must be an indirect reference")
                current = (child, frame.depth + 1, frame.key)
                completed_pages = None
                continue
            if frame.actual_count != frame.declared_count:
                raise ValueError("page-tree /Count does not match its leaf pages")
            completed_pages = frame.actual_count
            frames.pop()
            continue

        reference, depth, expected_parent = current
        current = None
        completed_pages = None
        if depth > PDF_MAX_PAGE_TREE_DEPTH:
            raise ValueError("PDF page tree exceeds depth limit")
        # Reject before deriving or resolving another node identity. This keeps both visited
        # nodes and the sole pending enter reference within the same global work ceiling.
        if node_count >= PDF_MAX_PAGE_TREE_NODES:
            raise ValueError("PDF page tree exceeds node limit")
        key = _reference_key(reference, reader)
        if key in seen:
            raise ValueError("PDF page tree contains a cycle or repeated node")
        seen.add(key)
        node_count += 1

        resolved = reference.get_object()
        if not isinstance(resolved, DictionaryObject):
            raise TypeError("page-tree reference does not resolve to a dictionary")
        node_type = _required_raw_value(resolved, "/Type")
        if not isinstance(node_type, NameObject) or node_type not in {_PAGE, _PAGES}:
            raise ValueError("page-tree node has an invalid /Type")
        _validate_parent_reference(resolved, reader, expected_parent)

        if node_type == _PAGE:
            if "/Kids" in resolved or "/Count" in resolved:
                raise ValueError("page leaf contains page-tree fields")
            page_count += 1
            if page_count > PDF_MAX_PAGES:
                raise ValueError("PDF page count exceeds parser work limit")
            completed_pages = 1
            continue

        declared_count = _required_raw_value(resolved, "/Count")
        if not isinstance(declared_count, NumberObject) or declared_count < 0:
            raise ValueError("page-tree /Count must be a nonnegative integer")
        if declared_count > PDF_MAX_PAGES:
            raise ValueError("PDF page count exceeds parser work limit")
        kids = _required_raw_value(resolved, "/Kids")
        if not isinstance(kids, ArrayObject):
            raise TypeError("page-tree /Kids must be an array")
        remaining_nodes = PDF_MAX_PAGE_TREE_NODES - node_count
        if len(kids) > remaining_nodes:
            raise ValueError("page-tree /Kids exceeds the remaining node budget")
        if (declared_count == 0) != (len(kids) == 0):
            raise ValueError("page-tree /Kids is inconsistent with an empty /Count")
        if expected_parent is not None and declared_count == 0:
            raise ValueError("non-root page-tree node cannot be empty")
        if len(kids) > declared_count:
            raise ValueError("page-tree /Kids is implausible for its /Count")
        if not kids:
            completed_pages = 0
            continue
        first_child = kids[0]
        if not isinstance(first_child, IndirectObject):
            raise TypeError("page-tree child must be an indirect reference")
        frames.append(
            _PagesFrame(
                key=key,
                kids=kids,
                declared_count=int(declared_count),
                depth=depth,
                next_child_index=1,
            )
        )
        current = (first_child, depth + 1, key)

    if completed_pages != page_count:
        raise ValueError("page-tree traversal produced an inconsistent page total")
    return page_count


type _ContentKey = tuple[str, int, int] | tuple[str, int]


def _content_key(value: object, reader: PdfReader) -> tuple[_ContentKey, StreamObject]:
    if isinstance(value, IndirectObject):
        identity = _reference_key(value, reader)
        resolved = value.get_object()
        if not isinstance(resolved, StreamObject):
            raise TypeError("PDF content reference is not a stream")
        return ("indirect", *identity), resolved
    if not isinstance(value, StreamObject):
        raise TypeError("PDF content must be a stream")
    return ("direct", id(value)), value


def _token_count(data: bytes, remaining: int) -> int:
    count = 0
    inside = False
    for value in data:
        whitespace = value in b"\x00\x09\x0a\x0c\x0d\x20"
        if whitespace:
            inside = False
        elif not inside:
            count += 1
            if count > remaining:
                raise ValueError("PDF content exceeds operator work limit")
            inside = True
    return count


def _raw_resources(owner: DictionaryObject) -> DictionaryObject | None:
    resources = owner.get("/Resources")
    if resources is None:
        return None
    if not isinstance(resources, DictionaryObject):
        raise TypeError("PDF resources must be a dictionary")
    return resources


def _form_references(owner: DictionaryObject) -> list[object]:
    resources = _raw_resources(owner)
    if resources is None:
        return []
    xobjects = resources.get("/XObject")
    if xobjects is None:
        return []
    if not isinstance(xobjects, DictionaryObject):
        raise TypeError("PDF XObject resources must be a dictionary")
    forms: list[object] = []
    for name in xobjects:
        candidate = xobjects.raw_get(name)
        resolved = candidate.get_object() if isinstance(candidate, IndirectObject) else candidate
        if isinstance(resolved, StreamObject) and resolved.get("/Subtype") == "/Form":
            forms.append(candidate)
    return forms


def _preflight_page_content(reader: PdfReader, pages: Sequence[object]) -> None:
    seen: set[_ContentKey] = set()
    decoded_bytes = 0
    tokens = 0

    def inspect(candidate: object, depth: int) -> None:
        nonlocal decoded_bytes, tokens
        if depth > PDF_MAX_FORM_DEPTH:
            raise ValueError("PDF Form XObject exceeds recursion limit")
        if len(seen) >= PDF_MAX_CONTENT_STREAMS:
            raise ValueError("PDF content exceeds stream limit")
        key, stream = _content_key(candidate, reader)
        if key in seen:
            raise ValueError("PDF content contains a cyclic or repeated stream")
        seen.add(key)
        data = stream.get_data()
        decoded_bytes += len(data)
        if decoded_bytes > PDF_MAX_AGGREGATE_DECODED_BYTES:
            raise ValueError("PDF content exceeds aggregate decoded-byte limit")
        tokens += _token_count(data, PDF_MAX_CONTENT_TOKENS - tokens)
        for form in _form_references(stream):
            inspect(form, depth + 1)

    for page_object in pages:
        if not isinstance(page_object, DictionaryObject):
            raise TypeError("flattened PDF page must be a dictionary")
        contents = page_object.get("/Contents")
        if isinstance(contents, ArrayObject):
            for candidate in contents:
                inspect(candidate, 0)
        elif contents is not None:
            inspect(contents, 0)
        for form in _form_references(page_object):
            inspect(form, 1)


class PdfParser(DocumentParser):
    def _parse(self, source: BinaryIO) -> list[ParsedBlock]:
        content = read_parser_source(source)
        with _PDF_PARSE_LOCK:
            previous_limit = filters.ZLIB_MAX_OUTPUT_LENGTH
            filters.ZLIB_MAX_OUTPUT_LENGTH = (
                PDF_MAX_DECOMPRESSED_STREAM_BYTES
                if previous_limit <= 0
                else min(previous_limit, PDF_MAX_DECOMPRESSED_STREAM_BYTES)
            )
            try:
                return self._parse_bounded_pdf(content)
            finally:
                filters.ZLIB_MAX_OUTPUT_LENGTH = previous_limit

    def _parse_bounded_pdf(self, content: bytes) -> list[ParsedBlock]:
        reader = PdfReader(BytesIO(content), strict=True)
        if reader.is_encrypted:
            raise WorkerFailure.for_code("encrypted_pdf_unsupported", "")
        page_count = _preflight_page_tree(reader)
        pages = list(reader.pages)
        if len(pages) != page_count:
            raise ValueError("flattened PDF page count changed after preflight")
        _preflight_page_content(reader, pages)

        blocks: list[ParsedBlock] = []
        extracted_characters = 0
        for page_number, page in enumerate(pages, start=1):
            text = page.extract_text() or ""
            extracted_characters += len(text)
            if extracted_characters > PDF_MAX_EXTRACTED_CHARACTERS:
                raise ValueError("PDF text exceeds parser output limit")
            if text.strip():
                blocks.append(
                    ParsedBlock(
                        kind=BlockKind.TEXT,
                        text=text,
                        locator=PdfLocator(page=page_number),
                    )
                )
        return blocks


__all__ = ["PdfParser"]
