"""구조를 아는 청킹.

기존 `ingestor._split_text()`는 평문만 받아서, 청크가 만들어지는 순간 "이게 몇
페이지 몇 번째 문단이었는지"가 사라진다. 여기서는 Block 경계를 우선 존중하며
청크를 만들고, 각 청크에 원본 좌표(페이지·문단 범위·제목)를 붙여 돌려준다.

불변식: 반환되는 모든 청크의 길이는 chunk_size 이하다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .base import Block, ConvertedDocument

# ingestor의 기존 값과 동일하게 유지한다. 청크 크기를 바꾸면 기존 색인과
# 새 색인의 검색 특성이 달라지므로 변경은 재색인과 함께 해야 한다.
DEFAULT_CHUNK_SIZE = 600
DEFAULT_CHUNK_OVERLAP = 150

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?。\n])\s*")


@dataclass(frozen=True)
class Chunk:
    """벡터 저장소에 들어갈 텍스트 1건과 그 출처 좌표."""
    index: int
    text: str
    block_start: int
    block_end: int
    page_start: Optional[int]
    page_end: Optional[int]
    heading: str

    def to_metadata(self) -> dict:
        """ChromaDB metadata로 쓸 수 있는 스칼라 dict.

        ChromaDB는 str/int/float/bool만 허용하므로 None은 -1 또는 ""로 바꾼다.
        """
        return {
            "chunk_index": self.index,
            "block_start": self.block_start,
            "block_end": self.block_end,
            "page_start": self.page_start if self.page_start is not None else -1,
            "page_end": self.page_end if self.page_end is not None else -1,
            "heading": self.heading,
        }


def _split_oversized(text: str, chunk_size: int) -> list[str]:
    """chunk_size를 넘는 단일 블록을 문장 경계로, 안 되면 강제로 자른다.
    반환되는 조각은 모두 chunk_size 이하임이 보장된다.
    """
    pieces: list[str] = []
    buffer = ""
    for sentence in _SENTENCE_BOUNDARY.split(text):
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) > chunk_size:
            if buffer:
                pieces.append(buffer)
                buffer = ""
            for start in range(0, len(sentence), chunk_size):
                piece = sentence[start:start + chunk_size].strip()
                if piece:
                    pieces.append(piece)
            continue
        candidate = f"{buffer} {sentence}".strip() if buffer else sentence
        if len(candidate) <= chunk_size:
            buffer = candidate
        else:
            pieces.append(buffer)
            buffer = sentence
    if buffer:
        pieces.append(buffer)
    return pieces


def _overlap_tail(text: str, overlap: int) -> str:
    """직전 청크 꼬리를 다음 청크 앞에 붙일 형태로 잘라낸다(단어 중간 절단 방지)."""
    if overlap <= 0 or len(text) <= overlap:
        return text if overlap > 0 else ""
    tail = text[-overlap:]
    space = tail.find(" ")
    return tail[space + 1:] if space != -1 else tail


def chunk_document(
    document: ConvertedDocument,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[Chunk]:
    """ConvertedDocument를 출처 좌표가 붙은 청크 목록으로 만든다."""
    chunks: list[Chunk] = []
    # buffer 원소: (조각 텍스트, 그 조각이 나온 Block)
    buffer: list[tuple[str, Block]] = []
    buffer_len = 0

    def flush() -> None:
        """현재 buffer를 청크로 확정하고, 다음 청크의 오버랩 씨앗을 남긴다."""
        nonlocal buffer, buffer_len
        if not buffer:
            return
        text = " ".join(piece for piece, _ in buffer).strip()
        if not text:
            buffer, buffer_len = [], 0
            return
        blocks = [block for _, block in buffer]
        pages = [b.page for b in blocks if b.page is not None]
        # 제목은 청크의 첫 블록 기준 — 청크 대부분의 맥락을 지배하는 제목이다.
        heading = blocks[0].heading_trail or (
            blocks[0].text if blocks[0].kind == "heading" else ""
        )
        chunks.append(Chunk(
            index=len(chunks),
            text=text,
            block_start=blocks[0].order,
            block_end=blocks[-1].order,
            page_start=min(pages) if pages else None,
            page_end=max(pages) if pages else None,
            heading=heading,
        ))
        tail = _overlap_tail(text, overlap)
        if tail:
            # 오버랩 텍스트의 출처는 직전 청크의 마지막 블록이다.
            buffer = [(tail, blocks[-1])]
            buffer_len = len(tail)
        else:
            buffer, buffer_len = [], 0

    for block in document.blocks:
        pieces = (
            _split_oversized(block.text, chunk_size)
            if len(block.text) > chunk_size
            else [block.text]
        )
        for piece in pieces:
            if buffer and buffer_len + len(piece) + 1 > chunk_size:
                flush()
                # 오버랩 씨앗을 붙이면 다시 초과하는 경우는 씨앗을 버린다.
                # (그러지 않으면 chunk_size 불변식이 깨진다.)
                if buffer and buffer_len + len(piece) + 1 > chunk_size:
                    buffer, buffer_len = [], 0
            buffer.append((piece, block))
            buffer_len += len(piece) + (1 if buffer_len else 0)

    flush()
    # 마지막 flush가 남긴 오버랩 씨앗은 이미 직전 청크에 포함된 내용이라 버린다.
    return chunks
