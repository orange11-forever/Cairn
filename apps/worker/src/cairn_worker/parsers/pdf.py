from io import BytesIO
from threading import RLock
from typing import BinaryIO

from cairn_api.knowledge.schemas import PdfLocator
from pypdf import PdfReader, filters
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject, NameObject, NumberObject

from cairn_worker.errors import WorkerFailure
from cairn_worker.parsers import BlockKind, DocumentParser, ParsedBlock, read_parser_source
from cairn_worker.parsers.limits import MAX_PARSED_BLOCKS, PARSER_SOURCE_MAX_BYTES

PDF_MAX_PAGES = MAX_PARSED_BLOCKS
PDF_MAX_PAGE_TREE_DEPTH = 128
PDF_MAX_PAGE_TREE_NODES = MAX_PARSED_BLOCKS * 4
PDF_MAX_DECOMPRESSED_STREAM_BYTES = PARSER_SOURCE_MAX_BYTES
PDF_MAX_EXTRACTED_CHARACTERS = PARSER_SOURCE_MAX_BYTES

# pypdf exposes its Flate output ceiling as a module setting. Serialize the temporary stricter
# value so concurrent PDF jobs cannot observe a partially restored limit.
_PDF_PARSE_LOCK = RLock()
_PAGE = NameObject("/Page")
_PAGES = NameObject("/Pages")

type _PageTreeKey = tuple[int, int]


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

    # The exit frame makes subtree /Count verification post-order without recursion.
    stack: list[tuple[bool, IndirectObject, int, _PageTreeKey | None]] = [
        (False, root_reference, 1, None)
    ]
    seen: set[_PageTreeKey] = set()
    subtree_pages: dict[_PageTreeKey, int] = {}
    child_keys: dict[_PageTreeKey, tuple[_PageTreeKey, ...]] = {}
    declared_counts: dict[_PageTreeKey, int] = {}
    node_count = 0
    page_count = 0

    while stack:
        exiting, reference, depth, expected_parent = stack.pop()
        key = _reference_key(reference, reader)
        if exiting:
            actual_count = sum(subtree_pages[child] for child in child_keys[key])
            if actual_count != declared_counts[key]:
                raise ValueError("page-tree /Count does not match its leaf pages")
            subtree_pages[key] = actual_count
            continue

        if depth > PDF_MAX_PAGE_TREE_DEPTH:
            raise ValueError("PDF page tree exceeds depth limit")
        if key in seen:
            raise ValueError("PDF page tree contains a cycle or repeated node")
        seen.add(key)
        node_count += 1
        if node_count > PDF_MAX_PAGE_TREE_NODES:
            raise ValueError("PDF page tree exceeds node limit")

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
            subtree_pages[key] = 1
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
        references: list[IndirectObject] = []
        keys: list[_PageTreeKey] = []
        for child in kids:
            if not isinstance(child, IndirectObject):
                raise TypeError("page-tree child must be an indirect reference")
            references.append(child)
            keys.append(_reference_key(child, reader))
        child_keys[key] = tuple(keys)
        declared_counts[key] = int(declared_count)
        stack.append((True, reference, depth, expected_parent))
        stack.extend(
            (False, child, depth + 1, key)
            for child in reversed(references)
        )

    root_key = _reference_key(root_reference, reader)
    if subtree_pages.get(root_key) != page_count:
        raise ValueError("page-tree traversal produced an inconsistent page total")
    return page_count


class PdfParser(DocumentParser):
    def _parse(self, source: BinaryIO) -> list[ParsedBlock]:
        content = read_parser_source(source)
        with _PDF_PARSE_LOCK:
            previous_limit = filters.ZLIB_MAX_OUTPUT_LENGTH
            filters.ZLIB_MAX_OUTPUT_LENGTH = min(
                previous_limit,
                PDF_MAX_DECOMPRESSED_STREAM_BYTES,
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
        pages = reader.pages
        if len(pages) != page_count:
            raise ValueError("flattened PDF page count changed after preflight")

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
