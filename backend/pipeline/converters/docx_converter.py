"""DOCX 변환기 (필수 포맷).

python-docx는 문단과 표를 별도 컬렉션으로 노출해서 `document.paragraphs`만 읽으면
표가 통째로 사라지고, 본문 순서도 깨진다. 그래서 body XML을 직접 순회해
문단·표가 원본에 나타난 순서 그대로 Block이 되게 한다.

DOCX에는 페이지 개념이 없다(페이지는 렌더링 시점에 결정된다). 따라서 page는
항상 None이고, 출처 추적은 문단 번호(Block.order)와 제목 경로로 한다.
"""
from __future__ import annotations

import io
import re

from .base import (
    ConversionError,
    ConversionWarning,
    ErrorCode,
    WarningCode,
    assemble,
)
from .cleaning import drop_duplicate_blocks, is_noise_line, normalize_text

SUFFIXES = (".docx",)

# "Heading 1", "제목 1", "개요 1" 등 스타일 이름에서 레벨 숫자를 뽑는다.
_HEADING_STYLE = re.compile(r"^(?:heading|title|제목|개요)\s*(\d+)?$", re.IGNORECASE)
_LIST_STYLE = re.compile(r"(list|목록|bullet|번호)", re.IGNORECASE)


def _require_python_docx():
    try:
        import docx  # noqa: F401
        from docx.oxml.ns import qn
        from docx.table import Table
        from docx.text.paragraph import Paragraph
    except ImportError as exc:
        raise ConversionError(
            ErrorCode.MISSING_DEPENDENCY,
            "DOCX 변환에 필요한 python-docx가 설치되어 있지 않습니다.",
        ) from exc
    return docx, qn, Table, Paragraph


def _iter_body(document, qn, Table, Paragraph):
    """body의 자식 엘리먼트를 원본 순서대로 문단/표 객체로 넘겨준다."""
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, document)
        elif child.tag == qn("w:tbl"):
            yield Table(child, document)


def _paragraph_kind(paragraph) -> tuple[str, int | None]:
    """문단 스타일에서 (kind, level)을 판정한다."""
    style_name = ""
    try:
        style_name = (paragraph.style.name or "").strip()
    except Exception:
        # 스타일이 삭제된 문서에서 python-docx가 예외를 던지는 경우가 있다.
        style_name = ""

    heading = _HEADING_STYLE.match(style_name)
    if heading:
        level = int(heading.group(1)) if heading.group(1) else 1
        return "heading", level

    # numPr(번호매기기 속성)이 있으면 스타일 이름과 무관하게 목록으로 본다.
    try:
        if paragraph._p.pPr is not None and paragraph._p.pPr.numPr is not None:
            return "list_item", None
    except AttributeError:
        pass
    if _LIST_STYLE.search(style_name):
        return "list_item", None
    return "paragraph", None


def _table_blocks(table, table_index: int) -> tuple[list[dict], ConversionWarning]:
    """표를 행 단위 Block으로 평탄화한다.

    표 구조(행/열)를 그대로 담을 자리가 Block 계약에 없으므로 셀을 " | "로 잇는다.
    열 의미가 유실될 수 있어 항상 경고를 남긴다.
    """
    blocks: list[dict] = []
    for row_index, row in enumerate(table.rows):
        cells = [normalize_text(cell.text).replace("\n", " ").strip() for cell in row.cells]
        # 병합 셀은 python-docx가 같은 텍스트를 반복 반환하므로 연속 중복을 접는다.
        collapsed: list[str] = []
        for cell in cells:
            if not collapsed or collapsed[-1] != cell:
                collapsed.append(cell)
        text = " | ".join(c for c in collapsed if c)
        if text:
            blocks.append({"kind": "table_row", "text": f"[표{table_index + 1}] {text}"})
    warning = ConversionWarning(
        WarningCode.TABLE_FLATTENED,
        "표를 행 단위 텍스트로 변환했습니다. 열 구조는 보존되지 않습니다.",
        location=f"table {table_index + 1}",
    )
    return blocks, warning


def convert(filename: str, data: bytes):
    """DOCX 바이트를 ConvertedDocument로 변환한다."""
    docx, qn, Table, Paragraph = _require_python_docx()

    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:
        raise ConversionError(
            ErrorCode.CORRUPT_FILE,
            f"DOCX 파일을 열 수 없습니다: {exc}",
            source=filename,
        ) from exc

    raw_blocks: list[dict] = []
    warnings: list[ConversionWarning] = []
    table_index = 0

    for item in _iter_body(document, qn, Table, Paragraph):
        if isinstance(item, Table):
            table_blocks, warning = _table_blocks(item, table_index)
            if table_blocks:
                raw_blocks.extend(table_blocks)
                warnings.append(warning)
            table_index += 1
            continue

        text = normalize_text(item.text).replace("\n", " ").strip()
        if not text or is_noise_line(text):
            continue
        kind, level = _paragraph_kind(item)
        raw_blocks.append({"kind": kind, "text": text, "level": level})

    # 이미지·차트·도형은 텍스트가 없어 그대로 유실된다. 조용히 버리지 않고 알린다.
    try:
        shape_count = len(document.inline_shapes)
    except Exception:
        shape_count = 0
    if shape_count:
        warnings.append(ConversionWarning(
            WarningCode.UNSUPPORTED_ELEMENT,
            f"이미지·도형 {shape_count}개는 텍스트로 변환되지 않았습니다.",
        ))

    document_out = assemble(filename, "docx", raw_blocks, warnings)
    document_out.blocks, dedupe_warnings = drop_duplicate_blocks(document_out.blocks)
    document_out.warnings.extend(dedupe_warnings)
    return document_out
