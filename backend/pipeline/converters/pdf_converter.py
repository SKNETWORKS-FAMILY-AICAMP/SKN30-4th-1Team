"""텍스트 기반 PDF 변환기 (필수 포맷).

스캔 PDF(OCR)는 이번 범위 밖이다. 텍스트 레이어가 전혀 없는 파일은 조용히 빈
문서로 넘기지 않고 `no_text_layer` 오류로 되돌려, 사용자가 "업로드는 됐는데
아무것도 안 나온다"는 상태에 빠지지 않게 한다.

PDF는 문단 구조를 보존하지 않으므로 제목 판별은 하지 않는다. 대신 페이지 번호를
Block마다 붙여서, 청크 출처를 "3페이지"까지 되짚을 수 있게 한다.
"""
from __future__ import annotations

import io

from .base import (
    ConversionError,
    ConversionWarning,
    ErrorCode,
    WarningCode,
    assemble,
)
from .cleaning import (
    drop_duplicate_blocks,
    find_repeated_edge_lines,
    is_noise_line,
    normalize_text,
    split_paragraphs,
)

SUFFIXES = (".pdf",)


def _require_pypdf():
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ConversionError(
            ErrorCode.MISSING_DEPENDENCY,
            "PDF 변환에 필요한 pypdf가 설치되어 있지 않습니다.",
        ) from exc
    return PdfReader


def _page_texts(reader, filename: str) -> tuple[list[str], list[ConversionWarning]]:
    """페이지별 원문 텍스트를 뽑는다. 한 페이지 실패가 문서 전체를 막지 않는다."""
    texts: list[str] = []
    warnings: list[ConversionWarning] = []
    for index, page in enumerate(reader.pages):
        try:
            text = page.extract_text() or ""
        except Exception as exc:
            texts.append("")
            warnings.append(ConversionWarning(
                WarningCode.PAGE_EXTRACT_FAILED,
                f"페이지 텍스트 추출에 실패했습니다: {exc}",
                location=f"page {index + 1}",
            ))
            continue
        if not text.strip():
            warnings.append(ConversionWarning(
                WarningCode.PAGE_NO_TEXT,
                "텍스트 레이어가 없는 페이지입니다(이미지·스캔 가능성). 내용이 누락됩니다.",
                location=f"page {index + 1}",
            ))
        texts.append(text)
    return texts, warnings


def convert(filename: str, data: bytes):
    """텍스트 기반 PDF 바이트를 ConvertedDocument로 변환한다."""
    PdfReader = _require_pypdf()

    try:
        reader = PdfReader(io.BytesIO(data))
        page_count = len(reader.pages)
    except Exception as exc:
        raise ConversionError(
            ErrorCode.CORRUPT_FILE,
            f"PDF 파일을 열 수 없습니다: {exc}",
            source=filename,
        ) from exc

    if reader.is_encrypted:
        # 빈 암호로 열리는 PDF가 흔하므로 한 번 시도하고, 그래도 막히면 명시적으로 실패한다.
        try:
            unlocked = bool(reader.decrypt(""))
        except Exception:
            unlocked = False
        if not unlocked:
            raise ConversionError(
                ErrorCode.CORRUPT_FILE,
                "암호로 보호된 PDF는 지원하지 않습니다. 암호를 해제한 파일을 올려주세요.",
                source=filename,
            )

    page_texts, warnings = _page_texts(reader, filename)

    if not any(text.strip() for text in page_texts):
        raise ConversionError(
            ErrorCode.NO_TEXT_LAYER,
            "PDF에서 텍스트를 추출하지 못했습니다. 스캔 이미지 PDF는 지원하지 않습니다.",
            source=filename,
        )

    # 머리말·꼬리말 제거는 페이지 경계가 남아 있는 지금만 가능하다.
    page_lines = [normalize_text(text).split("\n") for text in page_texts]
    repeated = find_repeated_edge_lines(page_lines)
    if repeated:
        warnings.append(ConversionWarning(
            WarningCode.REPEATED_LINE_DROPPED,
            f"모든 페이지에 반복되는 머리말·꼬리말 {len(repeated)}종을 제거했습니다.",
        ))

    raw_blocks: list[dict] = []
    for page_index, lines in enumerate(page_lines):
        # 제거 대상은 빈 줄로 바꿔 둔다 — 통째로 빼면 원본의 문단 경계(빈 줄)까지
        # 사라져 서로 다른 문단이 한 덩어리로 붙는다.
        kept = [
            "" if (line.strip() in repeated or is_noise_line(line)) else line
            for line in lines
        ]
        for paragraph in split_paragraphs("\n".join(kept)):
            raw_blocks.append({
                "kind": "paragraph",
                "text": paragraph,
                "page": page_index + 1,
            })

    document = assemble(filename, "pdf", raw_blocks, warnings, page_count=page_count)
    document.blocks, dedupe_warnings = drop_duplicate_blocks(document.blocks)
    document.warnings.extend(dedupe_warnings)
    return document
