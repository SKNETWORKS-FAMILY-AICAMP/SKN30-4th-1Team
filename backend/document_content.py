"""업로드와 질의 첨부가 공유하는 문서 내용 검증/추출 경계."""

import io
import logging
import unicodedata
from pathlib import Path

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


ALLOWED_SUFFIXES = {".md", ".txt", ".pdf"}
MAX_FILE_BYTES = 10 * 1024 * 1024
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


def extract_document_text(filename: str, data: bytes) -> str:
    """확장자에 맞는 실제 내용인지 확인한 뒤 텍스트를 반환한다."""
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
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
    if suffix in {".md", ".txt"}:
        return _decode_text(data)
    raise DocumentContentError("지원하지 않는 문서 형식입니다.")
