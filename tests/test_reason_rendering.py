"""`reason` 이 모든 렌더링 경로에서 정확히 한 번 나오는지 고정한다.

두 결함이 한 축에 있다.

- **누락**: `_row_line_body()`(공통 꼬리)에 `reason` 이 없어, 일반 SQL/RAG 컨텍스트에서
  결정·액션의 사유가 LLM 입력에 아예 들어가지 않았다.
- **중복**: `_format_history_row()` 와 `qa_tools._row_evidence()` 가 각자 `reason` 을
  덧붙이고 있었다. 공통 꼬리에 넣기만 하고 이 둘을 정리하지 않으면 해당 경로에
  `이유: X 이유: X` 가 들어간다.

세 경로가 모두 `_row_line_body()` 를 거치므로 **한 곳에서만 붙이는 것**이 목표 상태다.
"""
from backend.retriever import qa_engine, qa_tools

_ROW = {
    "id": 1,
    "category": "decision",
    "content": "결제 모듈은 외부 SDK 를 쓴다",
    "reason": "직접 구현 시 PCI 인증 부담이 크다",
    "topic": "결제",
    "owner": None,
    "date": "2026-04-13",
    "due_date": None,
    "source": "회의록.md",
}


def _reason_count(line: str) -> int:
    return line.count("이유:")


def test_general_row_renders_reason_once():
    """일반 구조화 기록 행 — 누락도 중복도 아니어야 한다."""
    line = qa_engine._format_mysql_row(_ROW)
    assert _reason_count(line) == 1, line
    assert "직접 구현 시 PCI 인증 부담이 크다" in line


def test_history_row_renders_reason_once():
    """supersede 이력 행 — 주석 접두가 붙어도 reason 은 한 번."""
    line = qa_engine._format_history_row(_ROW, "[번복됨]")
    assert _reason_count(line) == 1, line
    assert line.startswith("[번복됨] ")


def test_structured_tool_row_renders_reason_once():
    """query_structured_memory 출력 — 이 경로만 중복되던 사각지대였다."""
    line = qa_tools._row_evidence(_ROW)
    assert _reason_count(line) == 1, line


def test_row_without_reason_has_no_reason_label():
    """reason 이 없으면 라벨 자체가 나오지 않는다."""
    row = {**_ROW}
    row.pop("reason")
    for line in (
        qa_engine._format_mysql_row(row),
        qa_engine._format_history_row(row, "[번복됨]"),
        qa_tools._row_evidence(row),
    ):
        assert _reason_count(line) == 0, line
