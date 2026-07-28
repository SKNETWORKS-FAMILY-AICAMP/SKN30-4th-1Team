"""변환 공통 정제 규칙.

포맷별 변환기가 각자 다른 기준으로 텍스트를 다듬으면 청크 품질이 포맷마다
달라진다. 정제·중복 제거·불필요 정보 제거 기준은 전부 이 모듈에 모은다.
각 규칙의 근거와 알려진 한계는 docs/DOCUMENT_INGESTION_POLICY.md에 기록한다.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from typing import Iterable, Optional

from .base import Block, ConversionError, ConversionWarning, ErrorCode, WarningCode

# 제로폭 문자·BOM: 눈에 보이지 않지만 토크나이저와 중복 비교를 망가뜨린다.
_ZERO_WIDTH = re.compile("[​-‏⁠﻿]")
# 개행/탭을 제외한 제어문자. PDF 추출물에 자주 섞인다.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# 페이지 번호만 있는 줄: "3", "- 3 -", "3/12", "Page 3 of 12"
_PAGE_NUMBER_LINE = re.compile(
    r"^\s*[-–—\[\(]?\s*(?:page|p\.?)?\s*\d{1,4}"
    r"(?:\s*(?:/|of)\s*\d{1,4})?\s*[-–—\]\)]?\s*$",
    re.IGNORECASE,
)
# 구분선만 있는 줄: "-----", "=====", "＿＿＿", "···", 박스 그리기 문자
_SEPARATOR_LINE = re.compile(
    "^\\s*[-=_~*·.–—─-╿＿]{3,}\\s*$"
)

# 머리말/꼬리말 판정 파라미터
_REPEAT_MIN_PAGES = 3      # 최소 3페이지 이상인 문서에서만 적용
_REPEAT_RATIO = 0.6        # 전체 페이지의 60% 이상에 등장해야 반복으로 인정
_REPEAT_EDGE_LINES = 2     # 페이지 상·하단 각 2줄만 후보로 본다
_REPEAT_MAX_LEN = 80       # 긴 문장은 본문일 가능성이 높아 제외

# 전역 중복 제거를 적용할 최소 길이. 짧은 문구("해당 없음", "N/A")는
# 표 안에서 정당하게 반복되므로 연속 중복일 때만 제거한다.
_GLOBAL_DEDUPE_MIN_LEN = 40


def normalize_text(text: str) -> str:
    """공백·개행·비가시문자를 통일한다. 의미 있는 줄바꿈(문단 경계)은 보존한다."""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\xa0", " ").replace("　", " ").replace("\t", " ")
    text = _ZERO_WIDTH.sub("", text)
    text = _CONTROL.sub("", text)
    text = re.sub(r"[ ]{2,}", " ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def is_noise_line(line: str) -> bool:
    """본문 의미를 담지 않는 줄인지 판정한다(페이지 번호·구분선·빈 줄)."""
    stripped = line.strip()
    if not stripped:
        return True
    return bool(_PAGE_NUMBER_LINE.match(stripped) or _SEPARATOR_LINE.match(stripped))


def find_repeated_edge_lines(pages: list[list[str]]) -> set[str]:
    """여러 페이지 상·하단에 반복 등장하는 줄(머리말·꼬리말)을 찾는다.

    위치를 페이지 가장자리로 제한하는 이유는, 본문에 정당하게 반복되는 문구를
    머리말로 오인해 지우는 사고를 막기 위해서다.
    """
    if len(pages) < _REPEAT_MIN_PAGES:
        return set()

    counter: Counter[str] = Counter()
    for lines in pages:
        edge = lines[:_REPEAT_EDGE_LINES] + lines[-_REPEAT_EDGE_LINES:]
        candidates = {
            line.strip() for line in edge
            if line.strip() and len(line.strip()) <= _REPEAT_MAX_LEN
        }
        counter.update(candidates)

    # ceil을 쓴다. int()로 내리면 6페이지 중 3페이지(50%)처럼 _REPEAT_RATIO에
    # 못 미치는 문구까지 머리말로 판정해 정상 본문을 지운다.
    threshold = max(_REPEAT_MIN_PAGES, math.ceil(len(pages) * _REPEAT_RATIO))
    return {line for line, count in counter.items() if count >= threshold}


def drop_duplicate_blocks(
    blocks: Iterable[Block],
) -> tuple[list[Block], list[ConversionWarning]]:
    """중복 블록을 제거한다.

    - 연속 중복: 길이와 무관하게 제거 (변환 과정에서 생긴 잔여물)
    - 전역 중복: 충분히 긴 블록만 제거 (반복 고지문·표지 문구)

    order를 다시 매기지 않고 원본 order를 유지한다 — 출처 추적성의 기준점이므로
    제거 때문에 번호가 밀리면 안 된다.
    """
    kept: list[Block] = []
    seen: set[str] = set()
    previous: Optional[str] = None
    dropped = 0

    for block in blocks:
        key = re.sub(r"\s+", " ", block.text).strip().lower()
        duplicate = key == previous or (
            len(key) >= _GLOBAL_DEDUPE_MIN_LEN and key in seen
        )
        if duplicate:
            dropped += 1
            continue
        seen.add(key)
        previous = key
        kept.append(block)

    # 블록마다 경고를 만들면 반복 고지문이 있는 평범한 문서에서도 수십~수백 건이
    # 쌓여 업로드 응답이 부풀고 정작 다른 경고가 묻힌다. "몇 번째 블록이 중복이었나"는
    # 사용자가 취할 조치가 없는 정보이므로, 개수만 요약한 경고 1건으로 낸다
    # (머리말·꼬리말 제거 경고와 동일한 형식).
    warnings: list[ConversionWarning] = []
    if dropped:
        warnings.append(ConversionWarning(
            WarningCode.DUPLICATE_BLOCK_DROPPED,
            f"중복된 문단 {dropped}개를 제거했습니다.",
        ))

    return kept, warnings


def split_paragraphs(text: str) -> list[str]:
    """평문 덩어리를 문단 목록으로 나눈다.

    빈 줄이 있으면 빈 줄을 문단 경계로 쓰고, 없으면(PDF 추출물에서 흔하다)
    줄 단위로 끊되 문장이 끝나지 않은 줄은 다음 줄과 이어 붙인다.
    """
    normalized = normalize_text(text)
    if not normalized:
        return []

    if "\n\n" in normalized:
        return [
            " ".join(part.strip() for part in para.split("\n") if part.strip())
            for para in normalized.split("\n\n")
            if para.strip()
        ]

    paragraphs: list[str] = []
    buffer = ""
    for line in normalized.split("\n"):
        line = line.strip()
        if not line:
            continue
        buffer = f"{buffer} {line}".strip() if buffer else line
        # 문장 종결부호나 목록/제목 형태로 끝나면 문단을 닫는다.
        if re.search(r"[.!?。:：]$", line) or len(buffer) > 400:
            paragraphs.append(buffer)
            buffer = ""
    if buffer:
        paragraphs.append(buffer)
    return paragraphs


# 입력 경계 검증 파라미터. backend/document_content.py의 _validate_text_shape와
# 동일한 기준을 쓴다 — 같은 파일이 업로드 경로와 질의 경로에서 다르게 판정되면
# 안 되기 때문이다.
_MAX_CONTROL_RATIO = 0.02


def guard_extracted_text(text: str) -> str:
    """추출 직후 텍스트의 입력 경계를 검증한다.

    **반드시 normalize_text() 이전에 호출해야 한다.** normalize_text()가 제어문자를
    먼저 제거하므로 그 뒤에 검사하면 이미 사라진 뒤이고, 검증이 조용히 무력화된다.
    (U+007F를 넣은 DOCX가 검사 없이는 "AB"로 정상 변환되는 것이 확인됐다.)

    변환 실패가 아니라 입력 검증 실패이므로 API 계층은 이 코드를 415로 매핑한다.
    """
    if "\x00" in text:
        raise ConversionError(
            ErrorCode.INVALID_CONTENT,
            "문서에 허용되지 않는 바이너리 내용이 있습니다.",
        )
    controls = sum(
        1 for char in text
        if char not in "\t\r\n" and unicodedata.category(char) == "Cc"
    )
    if text and controls / len(text) > _MAX_CONTROL_RATIO:
        raise ConversionError(
            ErrorCode.INVALID_CONTENT,
            "문서에 허용되지 않는 제어 문자가 너무 많습니다.",
        )
    return text
