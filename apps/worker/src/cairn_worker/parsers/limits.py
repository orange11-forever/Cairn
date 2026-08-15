from cairn_api.knowledge.media import NORMAL_FILE_MAX_BYTES

PARSER_SOURCE_MAX_BYTES = NORMAL_FILE_MAX_BYTES
PARSER_READ_CHUNK_BYTES = 1024 * 1024
MAX_PARSED_BLOCKS = 10_000
MAX_MARKDOWN_LINES = 100_000
MAX_HTML_TAG_OPENERS = 100_000
CSV_ROWS_PER_BLOCK = 100
MAX_CSV_LOGICAL_ROWS = MAX_PARSED_BLOCKS * CSV_ROWS_PER_BLOCK
MAX_CSV_FIELDS = 1_000_000
CSV_FIELD_MAX_BYTES = NORMAL_FILE_MAX_BYTES


class ParserLimitExceeded(ValueError):
    pass


def ensure_block_capacity(current_count: int) -> None:
    if current_count >= MAX_PARSED_BLOCKS:
        raise ParserLimitExceeded


__all__ = [
    "CSV_FIELD_MAX_BYTES",
    "CSV_ROWS_PER_BLOCK",
    "MAX_CSV_FIELDS",
    "MAX_CSV_LOGICAL_ROWS",
    "MAX_HTML_TAG_OPENERS",
    "MAX_MARKDOWN_LINES",
    "MAX_PARSED_BLOCKS",
    "PARSER_READ_CHUNK_BYTES",
    "PARSER_SOURCE_MAX_BYTES",
    "ParserLimitExceeded",
    "ensure_block_capacity",
]
