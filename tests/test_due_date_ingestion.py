"""Action 마감일 추출·적재·승인 경계 테스트."""

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from backend.api.memory import MemoryUpdate, update_memory
from backend.api.suggestion import (
    _KIND_TARGET_CATEGORY,
    _apply_accepted_effect,
    _resolve_suggestion,
)
from backend.llm.base import LLMResponse
from backend.pipeline.extractor import extract
from backend.pipeline.ingestor import _due_date_plan, ingest
from backend.pipeline.models import MemoryItem


def _make_conn(lastrowid: int = 10):
    cursor = MagicMock()
    cursor.lastrowid = lastrowid
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    conn.cursor.return_value.__exit__.return_value = False
    return conn, cursor


def _run_ingest(item: MemoryItem, raw_text: str, source_date: str = "2026-07-30"):
    conn, cursor = _make_conn()
    collection = MagicMock()
    with patch("backend.pipeline.ingestor.get_connection", return_value=conn), \
         patch("backend.pipeline.ingestor.upsert_memory_vectors") as upsert, \
         patch("backend.pipeline.ingestor.get_collection", return_value=collection):
        ingest(
            project_id=1,
            doc_id=5,
            items=[item],
            raw_text=raw_text,
            source="meeting.md",
            date=source_date,
            doc_type="meeting",
        )
    return cursor, upsert


def _memory_insert(cursor):
    return next(
        call for call in cursor.execute.call_args_list
        if "INSERT INTO memory\n" in call.args[0]
    )


def _suggestion_inserts(cursor):
    return [
        call for call in cursor.execute.call_args_list
        if "INSERT INTO memory_suggestions" in call.args[0]
    ]


def test_extractor_exposes_due_date_contract_and_reference_date(monkeypatch):
    class Client:
        system = ""
        schema = {}

        def chat(self, *, system, tool_schema, **kwargs):
            self.system = system
            self.schema = tool_schema
            return LLMResponse(content="", tool_input={"items": []})

    client = Client()
    monkeypatch.setattr(
        "backend.pipeline.extractor.get_llm_client", lambda provider=None: client
    )

    extract("다음 주 금요일까지 초안을 작성한다.", reference_date="2026-07-30")

    item_schema = client.schema["$defs"]["MemoryItem"]["properties"]
    assert {"due_date", "due_date_text", "due_date_requires_confirmation"} <= set(item_schema)
    assert "마감일 상대 표현 해석 기준일: 2026-07-30" in client.system
    assert "임의 날짜를 만들지 않습니다" in client.system


def test_explicit_full_due_date_is_stored_automatically():
    item = MemoryItem(
        category="action",
        content="API 명세 작성",
        due_date="2026-08-05",
        due_date_text="2026년 8월 5일까지",
        due_date_requires_confirmation=False,
    )

    cursor, upsert = _run_ingest(item, "API 명세는 2026년 8월 5일까지 작성한다.")

    insert = _memory_insert(cursor)
    assert "due_date" in insert.args[0]
    assert insert.args[1][9] == "2026-08-05"
    assert _suggestion_inserts(cursor) == []
    assert upsert.call_args.args[0][0]["due_date"] == "2026-08-05"


def test_relative_due_date_is_pending_suggestion_not_memory_value():
    item = MemoryItem(
        category="action",
        content="API 명세 작성",
        date="2026-07-30",
        due_date="2026-08-07",
        due_date_text="다음 주 금요일까지",
        due_date_requires_confirmation=True,
        source="meeting.md",
    )

    cursor, upsert = _run_ingest(item, "API 명세는 다음 주 금요일까지 작성한다.")

    assert _memory_insert(cursor).args[1][9] is None
    suggestions = _suggestion_inserts(cursor)
    assert len(suggestions) == 1
    evidence = json.loads(suggestions[0].args[1][2])
    assert evidence == {
        "type": "due_date",
        "suggested_due_date": "2026-08-07",
        "raw_text": "다음 주 금요일까지",
        "reference_date": "2026-07-30",
        "source": "meeting.md",
    }
    assert upsert.call_args.args[0][0]["due_date"] is None


@pytest.mark.parametrize(
    "item,raw_text",
    [
        (
            MemoryItem(
                category="action",
                content="작업",
                due_date="2026-02-30",
                due_date_text="2026년 2월 30일까지",
            ),
            "작업은 2026년 2월 30일까지",
        ),
        (
            MemoryItem(
                category="action",
                content="작업",
                due_date="2026-08-05",
                due_date_text="원문에 없는 날짜",
            ),
            "작업 마감은 아직 미정",
        ),
        (
            MemoryItem(
                category="decision",
                content="결정",
                due_date="2026-08-05",
                due_date_text="2026년 8월 5일까지",
            ),
            "2026년 8월 5일까지 결정",
        ),
        (
            MemoryItem(
                category="action",
                content="작업",
                due_date="2026-08-07",
                due_date_text="다음 주 금요일까지",
                due_date_requires_confirmation=True,
            ),
            "작업은 다음 주 금요일까지",
        ),
    ],
)
def test_invalid_unanchored_or_non_action_due_date_is_ignored(item, raw_text):
    source_date = "" if item.due_date_text == "다음 주 금요일까지" else "2026-07-30"
    assert _due_date_plan(item, raw_text, source_date) == (None, None)


def _due_suggestion_row(candidate="2026-08-07", current=None):
    return {
        "id": 9,
        "project_id": 1,
        "memory_id": 10,
        "kind": "set_due_date",
        "evidence": json.dumps({"type": "due_date", "suggested_due_date": candidate}),
        "rationale": "상대 날짜 후보",
        "confidence": "medium",
        "status": "pending",
        "created_at": "2026-07-30 10:00:00",
        "resolved_at": None,
        "resolved_by": None,
        "memory_category": "action",
        "memory_completed_at": None,
        "memory_due_date": current,
        "memory_superseded_by": None,
    }


def test_due_date_suggestion_kind_targets_action():
    assert _KIND_TARGET_CATEGORY["set_due_date"] == "action"


def test_accept_due_date_suggestion_updates_only_empty_action_due_date():
    cursor = MagicMock()
    cursor.rowcount = 1

    _apply_accepted_effect(cursor, 1, _due_suggestion_row())

    update = cursor.execute.call_args
    assert "category = 'action'" in update.args[0]
    assert "due_date IS NULL" in update.args[0]
    assert update.args[1] == ("2026-08-07", 10, 1)


def test_accept_due_date_suggestion_rejects_stale_user_value():
    cursor = MagicMock()
    with pytest.raises(HTTPException) as exc_info:
        _apply_accepted_effect(
            cursor,
            1,
            _due_suggestion_row(current="2026-08-08"),
        )
    assert exc_info.value.status_code == 409
    cursor.execute.assert_not_called()


@pytest.mark.parametrize("candidate", [None, "2026-02-30", "2026-8-7", "next Friday"])
def test_accept_due_date_suggestion_rejects_invalid_candidate(candidate):
    with pytest.raises(HTTPException) as exc_info:
        _apply_accepted_effect(MagicMock(), 1, _due_suggestion_row(candidate=candidate))
    assert exc_info.value.status_code == 400


def test_resolve_due_date_suggestion_refreshes_memory_vector_after_commit():
    pending = _due_suggestion_row()
    accepted = {**pending, "status": "accepted", "resolved_at": "2026-07-30 11:00:00"}
    primary_conn, primary_cursor = _make_conn()
    primary_cursor.fetchone.side_effect = [pending, accepted]
    primary_cursor.rowcount = 1
    refresh_conn, refresh_cursor = _make_conn()
    memory_row = {"id": 10, "project_id": 1, "category": "action", "due_date": "2026-08-07"}
    refresh_cursor.fetchone.return_value = memory_row

    with patch("backend.api.suggestion.require_project_access"), \
         patch("backend.api.suggestion.get_current_user_id", return_value=3), \
         patch(
             "backend.api.suggestion.get_connection",
             side_effect=[primary_conn, refresh_conn],
         ), \
         patch("backend.retriever.memory_vector.upsert_memory_vector") as upsert:
        result = _resolve_suggestion(1, 9, "accepted")

    assert result["status"] == "accepted"
    assert primary_conn.commit.called
    upsert.assert_called_once_with(memory_row)


def test_manual_due_date_edit_rejects_pending_due_date_suggestions():
    conn, cursor = _make_conn()
    cursor.rowcount = 1
    row = {
        "id": 10,
        "project_id": 1,
        "category": "action",
        "due_date": "2026-08-09",
    }
    cursor.fetchone.return_value = row

    with patch("backend.api.memory.require_project_access"), \
         patch("backend.api.memory.get_current_user_id", return_value=3), \
         patch("backend.api.memory.get_connection", return_value=conn), \
         patch("backend.api.memory._upsert_memory_vector_best_effort"):
        result = update_memory(1, 10, MemoryUpdate(due_date="2026-08-09"))

    assert result == row
    stale_updates = [
        call for call in cursor.execute.call_args_list
        if "kind = 'set_due_date'" in call.args[0]
    ]
    assert len(stale_updates) == 1
    assert stale_updates[0].args[1] == (3, 1, 10)
