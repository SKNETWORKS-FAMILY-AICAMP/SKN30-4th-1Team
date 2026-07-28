"""업로드와 질의 첨부가 공유하는 문서 내용 검증/추출 경계."""

import io
import logging
import unicodedata
import zipfile
from pathlib import Path
from typing import Callable

from pypdf import PdfReader


# pypdf는 strict=False 복구 과정에서 손상된 CMap token 등 문서 유래 bytes를
# warning/error 인자로 그대로 기록할 수 있다. 요청마다 logger를 바꾸면 동시 요청과
# 경합하므로 모듈 초기화 때 namespace 전체를 닫는다. 애플리케이션은 아래의 고정된
# DocumentContentError만 외부로 내보낸다.
_pypdf_logger = logging.getLogger("pypdf")
_pypdf_logger.handlers.clear()
_pypdf_logger.addHandler(logging.NullHandler())
_pypdf_logger.setLevel(logging.CRITICAL + 1)
_pypdf_logger.propagate = False


PROJECT_DOCUMENT_MAX_FILE_BYTES = 10 * 1024 * 1024
QUERY_ATTACHMENT_MAX_FILE_BYTES = 8 * 1024 * 1024
QUERY_ATTACHMENT_MAX_TOTAL_BYTES = 8 * 1024 * 1024
# 기존 호출부와 테스트가 사용하는 이름을 유지한다.
MAX_FILE_BYTES = PROJECT_DOCUMENT_MAX_FILE_BYTES
INVALID_DOCUMENT_CODE = "INVALID_DOCUMENT_CONTENT"


class DocumentContentError(ValueError):
    def __init__(self, message: str):
        super().__init__(message)
        self.code = INVALID_DOCUMENT_CODE
        self.message = message


def _validate_text_shape(text: str) -> str:
    if "\x00" in text:
        raise DocumentContentError("문서에 허용되지 않는 바이너리 내용이 있습니다.")
    controls = sum(
        1
        for char in text
        if char not in "\t\r\n" and unicodedata.category(char) == "Cc"
    )
    if text and controls / len(text) > 0.02:
        raise DocumentContentError("문서에 허용되지 않는 제어 문자가 너무 많습니다.")
    return text


def _decode_text(data: bytes) -> str:
    if b"\x00" in data:
        raise DocumentContentError("문서에 허용되지 않는 바이너리 내용이 있습니다.")
    for encoding in ("utf-8-sig", "cp949"):
        try:
            return _validate_text_shape(data.decode(encoding))
        except UnicodeDecodeError:
            continue
    raise DocumentContentError("지원하는 문자 인코딩(UTF-8/CP949)이 아닙니다.")


def _read_pdf(data: bytes) -> str:
    if not data.startswith(b"%PDF-"):
        raise DocumentContentError("PDF 확장자와 실제 파일 형식이 일치하지 않습니다.")
    try:
        reader = PdfReader(io.BytesIO(data))
        return _validate_text_shape(
            "\n".join(page.extract_text() or "" for page in reader.pages)
        )
    except DocumentContentError:
        raise
    except Exception as exc:
        raise DocumentContentError("올바른 PDF 문서가 아닙니다.") from exc


_DOCX_MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
_DOCX_MAX_ENTRY_BYTES = 100 * 1024 * 1024
_DOCX_MAX_COMPRESSION_RATIO = 120


def _guard_docx_archive(data: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
    except (
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
        NotImplementedError,
        UnicodeError,
        ValueError,
        OSError,
    ) as exc:
        raise DocumentContentError("올바른 DOCX 문서가 아닙니다.") from exc

    total = 0
    for entry in entries:
        if entry.file_size > _DOCX_MAX_ENTRY_BYTES:
            raise DocumentContentError("DOCX 내부 항목이 안전한 처리 한도를 초과했습니다.")
        total += entry.file_size
    if total > _DOCX_MAX_UNCOMPRESSED_BYTES or (
        data and total / len(data) > _DOCX_MAX_COMPRESSION_RATIO
    ):
        raise DocumentContentError("DOCX 압축 해제 크기가 안전한 처리 한도를 초과했습니다.")


def _read_docx(data: bytes) -> str:
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
                        text = " ".join(
                            line.strip() for line in cell.text.splitlines() if line.strip()
                        )
                        if text:
                            cells.append(text)
                    if cells:
                        parts.append(" | ".join(cells))
        return _validate_text_shape("\n".join(parts))
    except DocumentContentError:
        raise
    except Exception as exc:
        raise DocumentContentError("올바른 DOCX 문서가 아닙니다.") from exc


DocumentParser = Callable[[bytes], str]
DOCUMENT_PARSERS: dict[str, DocumentParser] = {
    ".md": _decode_text,
    ".txt": _decode_text,
    ".pdf": _read_pdf,
    ".docx": _read_docx,
}
ALLOWED_SUFFIXES = set(DOCUMENT_PARSERS)


def supported_extensions() -> list[str]:
    return sorted(suffix.removeprefix(".") for suffix in DOCUMENT_PARSERS)


def supported_formats_label() -> str:
    return " / ".join(f".{extension}" for extension in supported_extensions())


def extract_document_text(filename: str, data: bytes) -> str:
    """확장자에 맞는 실제 내용인지 확인한 뒤 텍스트를 반환한다."""
    parser = DOCUMENT_PARSERS.get(Path(filename).suffix.lower())
    if parser is None:
        raise DocumentContentError(
            f"지원하지 않는 문서 형식입니다. ({supported_formats_label()})"
        )
    return parser(data)
