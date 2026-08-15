import unicodedata
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass

from cairn_api.knowledge.schemas import KnowledgeLocator

from cairn_worker.errors import WorkerFailure
from cairn_worker.parsers import BlockKind, ParsedBlock

MAX_CHUNKS_PER_DOCUMENT = 50_000


def _required_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("invalid chunking profile")  # noqa: TRY004
    return value


@dataclass(frozen=True)
class ChunkingConfig:
    max_codepoints: int
    overlap_codepoints: int

    @classmethod
    def from_profile(cls, value: Mapping[str, object]) -> "ChunkingConfig":
        try:
            maximum = _required_int(value["maxCodepoints"])
            overlap = _required_int(value["overlapCodepoints"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("invalid chunking profile") from None
        if maximum <= 0 or overlap < 0 or overlap >= maximum:
            raise ValueError("invalid chunking profile")
        return cls(max_codepoints=maximum, overlap_codepoints=overlap)


@dataclass(frozen=True)
class ChunkDraft:
    ordinal: int
    kind: BlockKind
    text: str
    normalized_text: str
    locator: KnowledgeLocator


def normalize_chunk_text(text: str) -> str:
    compatible = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(compatible.split())


def _validate_config(config: ChunkingConfig) -> None:
    maximum = _required_int(config.max_codepoints)
    overlap = _required_int(config.overlap_codepoints)
    if maximum <= 0 or overlap < 0 or overlap >= maximum:
        raise ValueError("invalid chunking profile")


def _rightmost_boundary(text: str, start: int, hard_end: int, overlap: int) -> int:
    minimum_end = start + overlap
    newline = text.rfind("\n", start, hard_end)
    if newline > minimum_end:
        return newline
    for index in range(hard_end - 1, minimum_end, -1):
        if text[index].isspace():
            return index
    return hard_end


def _split_block_text(text: str, config: ChunkingConfig) -> Iterator[str]:
    if len(text) <= config.max_codepoints:
        yield text
        return

    start = 0
    while start < len(text):
        previous_start = start
        hard_end = min(start + config.max_codepoints, len(text))
        end = hard_end
        if hard_end < len(text):
            end = _rightmost_boundary(
                text,
                start,
                hard_end,
                config.overlap_codepoints,
            )
        chunk_text = text[start:end].strip()
        if chunk_text:
            yield chunk_text
        if end == len(text):
            return
        start = max(previous_start + 1, end - config.overlap_codepoints)


def build_chunks(
    blocks: Sequence[ParsedBlock], config: ChunkingConfig
) -> list[ChunkDraft]:
    _validate_config(config)
    drafts: list[ChunkDraft] = []
    for block in blocks:
        for chunk_text in _split_block_text(block.text, config):
            if len(drafts) >= MAX_CHUNKS_PER_DOCUMENT:
                raise WorkerFailure(
                    "parser_failed",
                    "chunk output exceeds safety limit",
                    retryable=False,
                )
            drafts.append(
                ChunkDraft(
                    ordinal=len(drafts),
                    kind=block.kind,
                    text=chunk_text,
                    normalized_text=normalize_chunk_text(chunk_text),
                    locator=block.locator,
                )
            )
    return drafts


__all__ = [
    "MAX_CHUNKS_PER_DOCUMENT",
    "ChunkDraft",
    "ChunkingConfig",
    "build_chunks",
    "normalize_chunk_text",
]
