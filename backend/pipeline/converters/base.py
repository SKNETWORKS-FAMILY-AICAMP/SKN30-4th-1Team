"""포맷 변환기 공통 출력 계약.

모든 변환기는 `(filename, data: bytes) -> ConvertedDocument` 하나의 형태를 지키고,
후속 단계(extractor·ingestor)는 원본이 DOCX였는지 PDF였는지 알 필요가 없다.

평문 텍스트가 아니라 Block 목록을 넘기는 이유는 출처 추적성 때문이다.
청킹 시점에 "이 청크가 몇 페이지 몇 번째 문단에서 왔는지"를 붙이려면
원본의 구조 정보가 그 시점까지 살아 있어야 한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional, Tuple

# heading = 제목, paragraph = 본문 문단, list_item = 목록 항목,
# table_row = 표의 한 행(셀은 " | "로 평탄화), caption = 표·그림 설명
BlockKind = Literal["heading", "paragraph", "list_item", "table_row", "caption"]


class ErrorCode:
    """변환 실패 코드. 사용자에게 "왜 실패했는지"를 명시적으로 알리기 위한 식별자."""
    UNSUPPORTED_FORMAT = "unsupported_format"
    MISSING_DEPENDENCY = "missing_dependency"
    CORRUPT_FILE = "corrupt_file"
    EMPTY_DOCUMENT = "empty_document"
    NO_TEXT_LAYER = "no_text_layer"
    # 구조는 정상이지만 안전 처리 한도를 넘은 경우. CORRUPT_FILE과 반드시 구분한다 —
    # "손상"이라고 알리면 사용자가 복구·재다운로드 같은 엉뚱한 조치를 하게 된다.
    FILE_TOO_LARGE = "file_too_large"


class WarningCode:
    """변환 경고 코드. 변환은 성공했지만 원본의 일부가 손실·변형됐음을 알린다."""
    PAGE_NO_TEXT = "page_no_text"                # 특정 페이지에서 텍스트를 못 뽑음
    PAGE_EXTRACT_FAILED = "page_extract_failed"  # 특정 페이지 파싱 자체가 실패
    TABLE_FLATTENED = "table_flattened"          # 표를 행 단위 텍스트로 평탄화
    UNSUPPORTED_ELEMENT = "unsupported_element"  # 이미지·차트·수식 등 텍스트 아닌 요소
    REPEATED_LINE_DROPPED = "repeated_line_dropped"  # 머리말/꼬리말로 판단해 제거
    DUPLICATE_BLOCK_DROPPED = "duplicate_block_dropped"
    DECODE_FALLBACK = "decode_fallback"          # UTF-8 실패로 다른 인코딩 사용


class ConversionError(Exception):
    """변환 실패. 호출자(업로드 API)가 사용자에게 그대로 사유를 전달할 수 있어야 한다."""

    def __init__(self, code: str, message: str, source: Optional[str] = None):
        self.code = code
        self.message = message
        self.source = source
        super().__init__(f"[{code}] {message}")

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "source": self.source}


@dataclass(frozen=True)
class ConversionWarning:
    """변환 중 발생한 비치명적 손실 1건.

    location은 사람이 원본에서 되짚을 수 있는 위치 문자열(예: "page 3", "table 2").
    """
    code: str
    message: str
    location: Optional[str] = None

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "location": self.location}


@dataclass(frozen=True)
class Block:
    """문서를 구성하는 최소 의미 단위.

    order는 문서 전체에서 0부터 매기는 문단 번호로, 포맷에 무관한 유일한 위치 좌표다.
    page는 PDF처럼 페이지 개념이 있는 포맷에서만 채워지고 나머지는 None이다.
    """
    order: int
    kind: BlockKind
    text: str
    page: Optional[int] = None
    level: Optional[int] = None                 # heading 전용 (1=최상위)
    heading_path: Tuple[str, ...] = ()          # 이 블록을 감싸는 상위 제목 경로

    @property
    def heading_trail(self) -> str:
        return " > ".join(self.heading_path)


@dataclass
class ConvertedDocument:
    """변환기의 유일한 출력. 이 계약을 벗어나는 포맷별 필드는 두지 않는다."""
    source: str                                  # 원본 파일명(프로젝트 내부 상대경로)
    format: str                                  # "docx" | "pdf" | "text"
    blocks: list[Block]
    warnings: list[ConversionWarning] = field(default_factory=list)
    page_count: Optional[int] = None

    @property
    def text(self) -> str:
        """extractor(LLM)에 넘길 평문. 블록 경계는 빈 줄로 보존한다."""
        return "\n\n".join(b.text for b in self.blocks)

    def warning_dicts(self) -> list[dict]:
        return [w.to_dict() for w in self.warnings]


def assemble(
    source: str,
    fmt: str,
    raw_blocks: list[dict],
    warnings: Optional[list[ConversionWarning]] = None,
    page_count: Optional[int] = None,
) -> ConvertedDocument:
    """포맷별 변환기가 만든 원시 블록 목록을 최종 ConvertedDocument로 확정한다.

    order 부여와 heading_path 계산을 여기 한 곳에 모아, 변환기마다 문단 번호
    규칙이 달라지는 일을 막는다. raw_blocks의 각 항목은 최소한 kind·text를 갖고
    page·level은 선택이다. 텍스트가 빈 블록은 여기서 제거된다.
    """
    blocks: list[Block] = []
    stack: list[tuple[int, str]] = []  # (level, 제목) — 현재 위치의 상위 제목 경로

    for raw in raw_blocks:
        text = (raw.get("text") or "").strip()
        if not text:
            continue
        kind: BlockKind = raw.get("kind") or "paragraph"
        level = raw.get("level")

        if kind == "heading":
            level = level if isinstance(level, int) and level > 0 else 1
            while stack and stack[-1][0] >= level:
                stack.pop()
            heading_path = tuple(title for _, title in stack)
            stack.append((level, text))
        else:
            heading_path = tuple(title for _, title in stack)

        blocks.append(Block(
            order=len(blocks),
            kind=kind,
            text=text,
            page=raw.get("page"),
            level=level if kind == "heading" else None,
            heading_path=heading_path,
        ))

    if not blocks:
        raise ConversionError(
            ErrorCode.EMPTY_DOCUMENT,
            "문서에서 추출된 텍스트가 없습니다.",
            source=source,
        )

    return ConvertedDocument(
        source=source,
        format=fmt,
        blocks=blocks,
        warnings=list(warnings or []),
        page_count=page_count,
    )
