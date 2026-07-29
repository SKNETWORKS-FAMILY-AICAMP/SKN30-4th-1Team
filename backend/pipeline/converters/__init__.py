"""문서 포맷 변환 계층.

업로드된 파일을 포맷별 변환기에 넘겨 하나의 `ConvertedDocument`로 만든다.
새 포맷을 추가하는 방법은 모듈 하나를 만들고 `_REGISTRY`에 확장자를 등록하는
것뿐이며, 호출자(업로드 API·ingestor)는 수정하지 않는다.

우선순위(팀 계획 기준): DOCX·텍스트 PDF는 필수, HWPX는 조건부, PPTX·STT는
스트레치다. 조건부·스트레치 포맷은 게이트 통과 후 여기에 등록만 하면 된다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from . import docx_converter, pdf_converter, text_converter
from .base import (
    Block,
    ConversionError,
    ConversionWarning,
    ConvertedDocument,
    ErrorCode,
    WarningCode,
)
from .chunker import Chunk, chunk_document

__all__ = [
    "Block",
    "Chunk",
    "ConversionError",
    "ConversionWarning",
    "ConvertedDocument",
    "ErrorCode",
    "WarningCode",
    "chunk_document",
    "convert",
    "is_supported",
    "supported_suffixes",
]

# 확장자 → 변환 함수. 각 변환기 모듈이 자기 SUFFIXES를 선언한다.
_REGISTRY: dict[str, Callable[[str, bytes], ConvertedDocument]] = {
    suffix: module.convert
    for module in (text_converter, docx_converter, pdf_converter)
    for suffix in module.SUFFIXES
}


def supported_suffixes() -> frozenset[str]:
    """현재 변환 가능한 확장자 집합(소문자, 점 포함)."""
    return frozenset(_REGISTRY)


def is_supported(filename: str) -> bool:
    return Path(filename).suffix.lower() in _REGISTRY


def convert(filename: str, data: bytes) -> ConvertedDocument:
    """업로드 파일을 ConvertedDocument로 변환한다.

    실패는 전부 ConversionError로 통일해 호출자가 사유(code)를 그대로
    사용자에게 전달할 수 있게 한다.
    """
    suffix = Path(filename).suffix.lower()
    converter = _REGISTRY.get(suffix)
    if converter is None:
        raise ConversionError(
            ErrorCode.UNSUPPORTED_FORMAT,
            "지원하지 않는 파일 형식입니다. ("
            + " / ".join(sorted(supported_suffixes()))
            + ")",
            source=filename,
        )
    return converter(filename, data)
