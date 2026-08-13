from io import BytesIO
from threading import RLock
from typing import BinaryIO

from cairn_api.knowledge.schemas import PdfLocator
from pypdf import PdfReader, filters

from cairn_worker.errors import WorkerFailure
from cairn_worker.parsers import BlockKind, DocumentParser, ParsedBlock, read_parser_source
from cairn_worker.parsers.limits import MAX_PARSED_BLOCKS, PARSER_SOURCE_MAX_BYTES

PDF_MAX_PAGES = MAX_PARSED_BLOCKS
PDF_MAX_DECOMPRESSED_STREAM_BYTES = PARSER_SOURCE_MAX_BYTES
PDF_MAX_EXTRACTED_CHARACTERS = PARSER_SOURCE_MAX_BYTES

# pypdf exposes its Flate output ceiling as a module setting. Serialize the temporary stricter
# value so concurrent PDF jobs cannot observe a partially restored limit.
_PDF_PARSE_LOCK = RLock()


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
        if len(reader.pages) > PDF_MAX_PAGES:
            raise ValueError("PDF page count exceeds parser work limit")

        blocks: list[ParsedBlock] = []
        extracted_characters = 0
        for page_number, page in enumerate(reader.pages, start=1):
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
