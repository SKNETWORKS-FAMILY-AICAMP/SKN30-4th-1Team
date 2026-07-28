"""업로드와 질의 첨부가 공유하는 문서 내용 검증/추출 경계."""

import logging
import unicodedata
from pathlib import Path
from typing import Callable

from .pipeline.converters import ConversionError, ErrorCode, convert


# pypdf는 strict=False 복구 과정에서 손상된 CMap token 등 문서 유래 bytes를
# warning/error 인자로 그대로 기록할 수 있다. 요청마다 logger를 바꾸면 동시 요청과
# 경합하므로 모듈 초기화 때 namespace 전체를 닫는다. 애플리케이션은 아래의 고정된
# DocumentContentError만 외부로 내보낸다.
#
# 파싱을 converters에 위임한 뒤에도 이 설정은 반드시 남겨야 한다. logging namespace
# 전역 설정이라 converter 내부에서 import한 pypdf에도 그대로 적용되며,
# pipeline/converters 쪽에는 동등한 차단 장치가 없다.
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


# 빈 결과로 되돌려야 하는 코드. DOCX는 EMPTY_DOCUMENT, PDF는 텍스트 레이어가 아예
# 없으면 NO_TEXT_LAYER, 텍스트는 있었으나 페이지 번호·구분선 제거 후 블록이 비면
# assemble()이 EMPTY_DOCUMENT를 던진다. 세 경우 모두 이 모듈의 계약상 ""다.
_EMPTY_RESULT_CODES = (ErrorCode.EMPTY_DOCUMENT, ErrorCode.NO_TEXT_LAYER)


def _delegate(filename: str, data: bytes) -> str:
    """구조 보존 변환기에 위임하고 이 모듈의 문자열 계약으로 되돌린다.

    DOCX·PDF 파싱을 pipeline/converters 한 벌로 수렴시킨다. 예전에는 여기에 별도
    구현이 있었는데, 중첩 표를 최상위만 읽어 셀 안의 표 내용을 통째로 잃었다
    (실측 샘플에서 고유 토큰 43개 유실). 두 구현이 공존하면 호출 경로에 따라 같은
    파일이 다르게 처리되므로 한쪽으로 모은다.

    converter의 message를 그대로 전달한다. 고정 문구로 관리되어 원시 예외를 포함하지
    않으며, 일반 문구로 덮으면 FILE_TOO_LARGE의 조치 안내("문서를 나누거나 내용을
    줄여서…")와 INVALID_CONTENT의 구체적 사유가 사라진다.
    """
    try:
        return convert(filename, data).text
    except ConversionError as exc:
        if exc.code in _EMPTY_RESULT_CODES:
            return ""
        raise DocumentContentError(exc.message) from exc


def _read_pdf(data: bytes) -> str:
    return _delegate("document.pdf", data)


def _read_docx(data: bytes) -> str:
    return _delegate("document.docx", data)


DocumentParser = Callable[[bytes], str]
DOCUMENT_PARSERS: dict[str, DocumentParser] = {
    ".md": _decode_text,
    # .markdown은 변환기 레지스트리(pipeline/converters)가 이미 지원한다. 여기서
    # 빠지면 업로드·질의가 400으로 거절해 기존 지원 포맷이 회귀한다.
    ".markdown": _decode_text,
    ".txt": _decode_text,
    ".pdf": _read_pdf,
    ".docx": _read_docx,
}
ALLOWED_SUFFIXES = set(DOCUMENT_PARSERS)


def supported_extensions() -> list[str]:
    return sorted(suffix.removeprefix(".") for suffix in DOCUMENT_PARSERS)


def supported_formats_label() -> str:
    return " / ".join(f".{extension}" for extension in supported_extensions())


# 확장자별 매직 바이트. 확장자와 실제 내용이 다른 파일을 파서에 넘기기 전에 거른다.
_MAGIC_PREFIXES: dict[str, bytes] = {
    ".pdf": b"%PDF-",
    ".docx": b"PK\x03\x04",   # ZIP 컨테이너. 임의 ZIP도 통과하므로 1차 가드일 뿐이다.
}


def validate_document_bytes(filename: str, data: bytes) -> None:
    """파서에 넘기기 전 입력 경계를 검증한다. 텍스트를 반환하지 않는다.

    구조 보존 변환(pipeline/converters)과 안전성 검증을 분리하기 위한 진입점이다.
    업로드·질의는 이 함수로 415 판정을 먼저 내리고, 통과한 입력만 변환기에 넘긴다.
    변환기 내부 실패는 성격이 다르므로 400(업로드)·placeholder(질의)로 처리된다.

    텍스트 계열은 여기서 디코딩까지 시도한다 — 인코딩 위반은 파싱이 아니라 입력
    경계의 문제이기 때문이다. 바이너리 계열은 매직만 보고, 내용의 제어문자 검사는
    추출 직후(정규화 전) 변환기 안에서 수행한다.
    """
    suffix = Path(filename).suffix.lower()
    if suffix not in DOCUMENT_PARSERS:
        raise DocumentContentError(
            f"지원하지 않는 문서 형식입니다. ({supported_formats_label()})"
        )

    magic = _MAGIC_PREFIXES.get(suffix)
    if magic is not None:
        if not data.startswith(magic):
            raise DocumentContentError(
                f"{suffix[1:].upper()} 확장자와 실제 파일 형식이 일치하지 않습니다."
            )
        return

    _decode_text(data)


def extract_document_text(filename: str, data: bytes) -> str:
    """확장자에 맞는 실제 내용인지 확인한 뒤 텍스트를 반환한다."""
    parser = DOCUMENT_PARSERS.get(Path(filename).suffix.lower())
    if parser is None:
        raise DocumentContentError(
            f"지원하지 않는 문서 형식입니다. ({supported_formats_label()})"
        )
    return parser(data)
