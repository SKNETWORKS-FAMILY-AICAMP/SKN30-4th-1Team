"""평문·Markdown(.txt/.md) 변환기.

기존 업로드 경로가 하던 `data.decode(...)`를 대체한다. 평문에도 같은 Block 계약을
적용해야 DOCX/PDF와 청크 메타데이터 모양이 같아지고, 출처 표시 UI가 포맷별로
분기하지 않아도 된다.
"""
from __future__ import annotations

import re

from .base import ConversionWarning, WarningCode, assemble
from .cleaning import drop_duplicate_blocks, is_noise_line, normalize_text

SUFFIXES = (".txt", ".md", ".markdown")

_ATX_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_SETEXT_UNDERLINE = re.compile(r"^(=+|-+)\s*$")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+·]|\d{1,3}[.)])\s+(.+)$")
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_DIVIDER = re.compile(r"^\s*\|?[\s:|-]+\|[\s:|-]*$")

# 인코딩 폴백 순서. 국내 문서는 UTF-8 다음으로 CP949가 압도적으로 많다.
_ENCODINGS = ("utf-8", "cp949", "utf-16")


def _decode(data: bytes) -> tuple[str, list[ConversionWarning]]:
    for encoding in _ENCODINGS:
        try:
            text = data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
        if encoding == "utf-8":
            return text, []
        return text, [ConversionWarning(
            WarningCode.DECODE_FALLBACK,
            f"UTF-8 디코딩에 실패해 {encoding}으로 읽었습니다. 일부 글자가 깨질 수 있습니다.",
        )]
    # 모든 후보가 실패하면 손실을 감수하고 읽되 경고를 남긴다 — 업로드 자체를
    # 실패시키기보다, 사용자가 원본 인코딩 문제를 인지하게 하는 편이 낫다.
    return data.decode("utf-8", errors="replace"), [ConversionWarning(
        WarningCode.DECODE_FALLBACK,
        "알려진 인코딩으로 디코딩하지 못해 일부 문자를 대체했습니다.",
    )]


def _classify(line: str) -> tuple[str, str, int | None]:
    """한 줄을 (kind, text, level)로 분류한다."""
    heading = _ATX_HEADING.match(line)
    if heading:
        return "heading", heading.group(2).strip(), len(heading.group(1))
    if _TABLE_ROW.match(line):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        return "table_row", " | ".join(c for c in cells if c), None
    item = _LIST_ITEM.match(line)
    if item:
        return "list_item", item.group(1).strip(), None
    return "paragraph", line.strip(), None


def convert(filename: str, data: bytes):
    """평문/Markdown 바이트를 ConvertedDocument로 변환한다."""
    text, warnings = _decode(data)
    text = normalize_text(text)

    raw_blocks: list[dict] = []
    paragraph_buffer: list[str] = []

    def flush_paragraph() -> None:
        if paragraph_buffer:
            raw_blocks.append({"kind": "paragraph", "text": " ".join(paragraph_buffer)})
            paragraph_buffer.clear()

    lines = text.split("\n")
    for index, line in enumerate(lines):
        if is_noise_line(line):
            flush_paragraph()
            continue
        if _TABLE_DIVIDER.match(line) and _TABLE_ROW.match(line):
            continue  # Markdown 표의 정렬 구분행은 내용이 없다

        # Setext 제목(다음 줄이 === 또는 ---)은 앞 줄을 제목으로 승격한다.
        next_line = lines[index + 1] if index + 1 < len(lines) else ""
        if paragraph_buffer == [] and _SETEXT_UNDERLINE.match(next_line) and line.strip():
            raw_blocks.append({
                "kind": "heading",
                "text": line.strip(),
                "level": 1 if next_line.strip().startswith("=") else 2,
            })
            continue
        if _SETEXT_UNDERLINE.match(line) and raw_blocks and raw_blocks[-1]["kind"] == "heading":
            continue

        kind, content, level = _classify(line)
        if not content:
            continue
        if kind == "paragraph":
            paragraph_buffer.append(content)
            continue
        flush_paragraph()
        raw_blocks.append({"kind": kind, "text": content, "level": level})

    flush_paragraph()

    document = assemble(filename, "text", raw_blocks, warnings)
    document.blocks, dedupe_warnings = drop_duplicate_blocks(document.blocks)
    document.warnings.extend(dedupe_warnings)
    return document
