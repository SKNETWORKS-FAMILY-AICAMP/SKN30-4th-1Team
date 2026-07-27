"""Supported document formats, parsers, and upload limits.

This module is the single source of truth for formats accepted by both document
uploads and query attachments.  Client-provided Content-Type values are ignored.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Callable

PROJECT_DOCUMENT_MAX_FILE_BYTES = 10 * 1024 * 1024

# Query attachments are embedded in JSON as base64.  An 8 MiB decoded payload
# expands to about 10.67 MiB, leaving headroom below Caddy's 12 MB request limit
# for JSON syntax, the question, history, and headers.
QUERY_ATTACHMENT_MAX_FILE_BYTES = 8 * 1024 * 1024
QUERY_ATTACHMENT_MAX_TOTAL_BYTES = 8 * 1024 * 1024

DocumentParser = Callable[[bytes], str]


class DocumentParseError(ValueError):
    """The selected parser could not extract usable text from a document."""


def read_text(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def read_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:
        raise DocumentParseError("PDF 파일을 읽을 수 없습니다.") from exc


_DOCX_MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
_DOCX_MAX_ENTRY_BYTES = 100 * 1024 * 1024
_DOCX_MAX_COMPRESSION_RATIO = 120


def _guard_docx_archive(data: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
    except (zipfile.BadZipFile, zipfile.LargeZipFile, NotImplementedError, UnicodeError, ValueError, OSError) as exc:
        raise DocumentParseError("DOCX 파일을 열 수 없습니다.") from exc

    total = 0
    for entry in entries:
        if entry.file_size > _DOCX_MAX_ENTRY_BYTES:
            raise DocumentParseError("DOCX 내부 항목이 안전한 처리 한도를 초과했습니다.")
        total += entry.file_size
    if total > _DOCX_MAX_UNCOMPRESSED_BYTES or (
        data and total / len(data) > _DOCX_MAX_COMPRESSION_RATIO
    ):
        raise DocumentParseError("DOCX 압축 해제 크기가 안전한 처리 한도를 초과했습니다.")


def read_docx(data: bytes) -> str:
    """Extract paragraphs and table rows in their original body order."""
    _guard_docx_archive(data)
    try:
        import docx
        from docx.oxml.ns import qn
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        document = docx.Document(io.BytesIO(data))
        parts: list[str] = []
        for child in document.element.body.iterchildren():
            if child.tag == qn("w:p"):
                text = Paragraph(child, document).text.strip()
                if text:
                    parts.append(text)
            elif child.tag == qn("w:tbl"):
                table = Table(child, document)
                for row in table.rows:
                    cells: list[str] = []
                    previous_cell = None
                    for cell in row.cells:
                        if cell._tc is previous_cell:
                            continue
                        previous_cell = cell._tc
                        text = " ".join(line.strip() for line in cell.text.splitlines() if line.strip())
                        if text:
                            cells.append(text)
                    if cells:
                        parts.append(" | ".join(cells))
        return "\n".join(parts)
    except DocumentParseError:
        raise
    except Exception as exc:
        raise DocumentParseError("DOCX 파일을 읽을 수 없습니다.") from exc


DOCUMENT_PARSERS: dict[str, DocumentParser] = {
    ".md": read_text,
    ".txt": read_text,
    ".pdf": read_pdf,
    ".docx": read_docx,
}


def supported_extensions() -> list[str]:
    return sorted(suffix.removeprefix(".") for suffix in DOCUMENT_PARSERS)


def supported_suffixes() -> set[str]:
    return set(DOCUMENT_PARSERS)


def supported_formats_label() -> str:
    return " / ".join(f".{extension}" for extension in supported_extensions())


def parse_document(filename: str, data: bytes) -> str:
    parser = DOCUMENT_PARSERS.get(Path(filename).suffix.lower())
    if parser is None:
        raise DocumentParseError(
            f"지원하지 않는 파일 형식입니다. ({supported_formats_label()})"
        )
    return parser(data)
