"""적재 시 supersede 판별기(계층2) 단위 테스트."""
from unittest.mock import MagicMock, patch

from backend.reconciler import supersede
from backend.reconciler.supersede import SupersedeMatch, SupersedeResult


class _StructuredLLM:
    def __init__(self):
        self.schema = None
        self.messages = None

    def with_structured_output(self, schema):
        self.schema = schema
        return self

    def invoke(self, messages):
        self.messages = messages
        return {
            "matches": [
                {
                    "memory_id": 10,
                    "superseding_memory_id": 99,
                    "rationale": "새 결정이 기존 배포 방침을 명시적으로 대체합니다.",
                    "confidence": "high",
                }
            ]
        }


def test_run_supersede_uses_structured_output(monkeypatch):
    """run_supersede() — Pydantic structured output으로 매칭 결과를 받는다."""
    llm = _StructuredLLM()
    monkeypatch.setattr(supersede, "get_chat_model", lambda: llm)

    result = supersede.run_supersede(
        1,
        [{"id": 99, "content": "이제 매주 금요일 배포한다"}],
        [{"id": 10, "content": "매주 수요일 배포한다"}],
    )

    assert llm.schema is SupersedeResult
    assert result.matches[0].memory_id == 10
    assert result.matches[0].superseding_memory_id == 99
    assert "번복(supersede)" in llm.messages[0].content


def _make_conn(fetchall=None, rowcount=1):
    cursor = MagicMock()
    cursor.fetchall.return_value = fetchall if fetchall is not None else []
    cursor.rowcount = rowcount
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    conn.cursor.return_value.__exit__.return_value = False
    return conn, cursor


def test_detect_supersede_inserts_pending_suggestion():
    """detect_supersede() — 후보 검색→LLM→pending 제안 INSERT까지 이어진다."""
    conn, cursor = _make_conn(fetchall=[{"id": 10, "content": "매주 수요일 배포", "topic": None, "reason": None, "date": None}])
    result = SupersedeResult(
        matches=[SupersedeMatch(memory_id=10, superseding_memory_id=99, rationale="대체", confidence="high")]
    )
    with patch("backend.reconciler.supersede.find_similar_memories", return_value=[10]), \
         patch("backend.reconciler.supersede.get_connection", return_value=conn), \
         patch("backend.reconciler.supersede.run_supersede", return_value=result):
        out = supersede.detect_supersede(1, [{"id": 99, "content": "이제 매주 금요일 배포한다", "topic": None, "reason": None}])

    assert out["created"] == 1
    sql_calls = [c.args[0] for c in cursor.execute.call_args_list]
    insert_sql = next(s for s in sql_calls if "INSERT INTO memory_suggestions" in s)
    assert "'supersede'" in insert_sql
    # evidence에 superseding_memory_id가 담긴다
    insert_params = next(c.args[1] for c in cursor.execute.call_args_list if "INSERT INTO memory_suggestions" in c.args[0])
    assert '"superseding_memory_id": 99' in insert_params[2]


def test_detect_supersede_skips_llm_without_new_decisions():
    """신규 decision(내용 있는)이 없으면 LLM/DB를 호출하지 않는다."""
    with patch("backend.reconciler.supersede.find_similar_memories") as fs, \
         patch("backend.reconciler.supersede.run_supersede") as rs:
        out = supersede.detect_supersede(1, [{"id": 1, "content": "   "}])
    assert out == {"new_decisions": 0, "candidates": 0, "matches": 0, "created": 0}
    fs.assert_not_called()
    rs.assert_not_called()


def test_detect_supersede_skips_llm_without_live_candidates():
    """후보 검색 결과가 비었거나 모두 이미 superseded면 LLM을 호출하지 않는다."""
    conn, _ = _make_conn(fetchall=[])  # _fetch_candidate_decisions가 빈 결과
    with patch("backend.reconciler.supersede.find_similar_memories", return_value=[]), \
         patch("backend.reconciler.supersede.get_connection", return_value=conn), \
         patch("backend.reconciler.supersede.run_supersede") as rs:
        out = supersede.detect_supersede(1, [{"id": 99, "content": "새 결정"}])
    assert out["candidates"] == 0
    assert out["created"] == 0
    rs.assert_not_called()


def test_insert_skips_invalid_and_self_matches():
    """입력에 없는 id·자기참조 매칭은 저장하지 않는다."""
    conn, cursor = _make_conn(rowcount=1)
    matches = [
        SupersedeMatch(memory_id=10, superseding_memory_id=99, rationale="ok", confidence="high"),   # 유효
        SupersedeMatch(memory_id=555, superseding_memory_id=99, rationale="bad old", confidence="high"),  # candidate 아님
        SupersedeMatch(memory_id=10, superseding_memory_id=888, rationale="bad new", confidence="high"),  # new 아님
        SupersedeMatch(memory_id=10, superseding_memory_id=10, rationale="self", confidence="high"),      # 자기참조 아님(new_ids에 10 없음) → 어차피 제외
    ]
    with patch("backend.reconciler.supersede.get_connection", return_value=conn):
        created = supersede._insert_supersede_suggestions(1, matches, new_ids={99}, candidate_ids={10})
    inserts = [c for c in cursor.execute.call_args_list if "INSERT INTO memory_suggestions" in c.args[0]]
    assert len(inserts) == 1  # 유효 1건만
    assert created == 1


def test_insert_skips_date_inverted_matches():
    """J-002: 신규(대체) decision 날짜가 기존 후보보다 과거인 매칭은 LLM이 반환해도
    저장하지 않는다 — 과거 문서 뒤늦은 적재가 최신 결정을 숨기지 못하도록
    시간순서 규칙을 프롬프트가 아니라 코드에서 강제한다."""
    conn, cursor = _make_conn(rowcount=1)
    matches = [
        SupersedeMatch(memory_id=10, superseding_memory_id=99, rationale="역전", confidence="high"),
        SupersedeMatch(memory_id=11, superseding_memory_id=99, rationale="정순", confidence="high"),
        SupersedeMatch(memory_id=12, superseding_memory_id=99, rationale="같은 날", confidence="high"),
        SupersedeMatch(memory_id=13, superseding_memory_id=99, rationale="날짜 없음", confidence="high"),
    ]
    with patch("backend.reconciler.supersede.get_connection", return_value=conn):
        created = supersede._insert_supersede_suggestions(
            1, matches, new_ids={99}, candidate_ids={10, 11, 12, 13},
            new_dates={99: "2024-01-05"},
            candidate_dates={10: "2025-03-01", 11: "2023-12-31", 12: "2024-01-05", 13: None},
        )
    inserted_targets = [
        c.args[1][1] for c in cursor.execute.call_args_list
        if "INSERT INTO memory_suggestions" in c.args[0]
    ]
    # 역전(10)만 제외 — 정순(11)·같은 날(12)·날짜 결측(13)은 저장
    assert inserted_targets == [11, 12, 13]
    assert created == 3


def test_detect_supersede_passes_dates_to_insert_validation():
    """J-002: detect_supersede가 신규·후보의 date를 저장 검증에 전달한다."""
    matches = [SupersedeMatch(memory_id=10, superseding_memory_id=99, rationale="역전", confidence="high")]
    with patch.object(supersede, "find_similar_memories", return_value=[10]), \
         patch.object(supersede, "_fetch_candidate_decisions",
                      return_value=[{"id": 10, "content": "기존 결정", "date": "2025-03-01"}]), \
         patch.object(supersede, "run_supersede",
                      return_value=supersede.SupersedeResult(matches=matches)), \
         patch.object(supersede, "_insert_supersede_suggestions", return_value=0) as mock_insert:
        supersede.detect_supersede(
            1, [{"id": 99, "content": "과거 결정", "topic": None, "reason": None, "date": "2024-01-05"}]
        )

    kwargs = mock_insert.call_args.kwargs
    assert kwargs["new_dates"] == {99: "2024-01-05"}
    assert kwargs["candidate_dates"] == {10: "2025-03-01"}


def test_insert_dedup_uses_not_exists_on_superseding_id():
    """중복 방지: (memory_id, superseding_memory_id) pending 존재 시 NOT EXISTS로 재생성 안 함."""
    conn, cursor = _make_conn(rowcount=0)  # NOT EXISTS로 아무 행도 안 들어감
    matches = [SupersedeMatch(memory_id=10, superseding_memory_id=99, rationale="ok", confidence="high")]
    with patch("backend.reconciler.supersede.get_connection", return_value=conn):
        created = supersede._insert_supersede_suggestions(1, matches, new_ids={99}, candidate_ids={10})
    insert_sql = next(c.args[0] for c in cursor.execute.call_args_list if "INSERT INTO memory_suggestions" in c.args[0])
    assert "NOT EXISTS" in insert_sql
    assert "$.superseding_memory_id" in insert_sql
    assert created == 0
