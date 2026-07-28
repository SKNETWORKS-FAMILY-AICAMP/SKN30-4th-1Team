"""R-004 통합: supersede accept → 계층1 search 제외까지 end-to-end 계약 검증.

accept 경로(api/suggestion.py)와 조회 경로(retriever/mysql_search.py)가 서로 다른 SQL을
쓰지만 같은 memory.superseded_by 컬럼을 통해 연결된다. 공유 인메모리 저장소를 두 경로에
물려, accept가 superseded_by를 채우면 계층1 기본 조회가 그 decision을 실제로 제외함을 확인한다.
"""
import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import app
from backend.retriever import mysql_search
from backend.retriever.index_scope import ProjectIndexScope

_client = TestClient(app, raise_server_exceptions=False)


class _FakeDB:
    """memory + memory_suggestions를 담는 최소 공유 저장소."""

    def __init__(self):
        self.memory = {
            10: {"id": 10, "project_id": 1, "category": "decision", "content": "매주 수요일 배포",
                 "superseded_by": None, "superseded_at": None, "completed_at": None,
                 "owner": None, "due_date": None, "sort_order": None, "created_at": "2026-07-01"},
            42: {"id": 42, "project_id": 1, "category": "decision", "content": "이제 매주 금요일 배포",
                 "superseded_by": None, "superseded_at": None, "completed_at": None,
                 "owner": None, "due_date": None, "sort_order": None, "created_at": "2026-07-02"},
        }
        self.suggestion = {
            8: {"id": 8, "project_id": 1, "memory_id": 10, "kind": "supersede",
                "evidence": '{"type":"supersede","superseding_memory_id":42}',
                "rationale": "새 결정이 기존 배포 방침을 대체합니다.", "confidence": "high",
                "status": "pending", "created_at": "2026-07-02 10:00:00",
                "resolved_at": None, "resolved_by": None},
        }

    def delete_memory(self, memory_id):
        """DELETE FROM memory 흉내 — migrate_v8 self-FK ON DELETE SET NULL 의미론 포함.

        대체(신) decision이 삭제되면 DB가 그 row를 가리키던 superseded_by를 NULL로
        되돌려 구 decision이 기본 조회에 복귀한다(F-001 불변식)."""
        self.memory.pop(memory_id, None)
        for m in self.memory.values():
            if m["superseded_by"] == memory_id:
                m["superseded_by"] = None


class _Cursor:
    def __init__(self, db):
        self.db = db
        self._one = None
        self._all = []
        self.rowcount = 0

    def execute(self, sql, params=None):
        params = params or []
        self.rowcount = 0
        if (
            "FROM memory_suggestions s" in sql
            and (
                "JOIN memory m" in sql
                or "JOIN active_memory m" in sql
            )
        ):
            sid = params[0]
            s = self.db.suggestion.get(sid)
            if not s:
                self._one = None
                return
            m = self.db.memory[s["memory_id"]]
            self._one = {**s,
                         "memory_category": m["category"],
                         "memory_completed_at": m["completed_at"],
                         "memory_superseded_by": m["superseded_by"]}
        elif (
            sql.strip().startswith("SELECT id FROM memory WHERE id")
            or sql.strip().startswith(
                "SELECT id FROM active_memory WHERE id"
            )
        ):
            # D-1/F-004: 대체(신) decision 검증 — 존재 + project + (SQL에 있으면)
            # category='decision' + superseded_by IS NULL(순환 가드)까지 해석한다.
            mid, pid = params
            m = self.db.memory.get(mid)
            ok = bool(m) and m["project_id"] == pid
            if ok and "category = 'decision'" in sql:
                ok = m["category"] == "decision"
            if ok and "superseded_by IS NULL" in sql:
                ok = m["superseded_by"] is None
            self._one = {"id": mid} if ok else None
        elif "UPDATE memory SET superseded_by" in sql:
            superseding_id, memory_id, _pid = params
            m = self.db.memory[memory_id]
            # WHERE ... superseded_by IS NULL 조건부 UPDATE를 반영
            if m["superseded_by"] is None:
                m["superseded_by"] = superseding_id
                m["superseded_at"] = "2026-07-02 11:00:00"
                self.rowcount = 1
        elif "SET status='rejected'" in sql:
            resolved_by, pid, current_sid, hidden_memory_id, _ = params
            for sid, suggestion in self.db.suggestion.items():
                if (
                    sid == current_sid
                    or suggestion["project_id"] != pid
                    or suggestion["kind"] != "supersede"
                    or suggestion["status"] != "pending"
                ):
                    continue
                superseding_id = json.loads(suggestion["evidence"])[
                    "superseding_memory_id"
                ]
                if (
                    suggestion["memory_id"] == hidden_memory_id
                    or superseding_id == hidden_memory_id
                ):
                    suggestion.update(
                        status="rejected",
                        resolved_by=resolved_by,
                        resolved_at="2026-07-02 11:00:00",
                    )
                    self.rowcount += 1
        elif "UPDATE memory_suggestions SET status" in sql:
            status, resolved_by, sid, _pid = params
            s = self.db.suggestion[sid]
            # H-003: WHERE ... status = 'pending' 조건부 UPDATE를 반영 —
            # 이미 해소된 제안은 덮어쓰지 못하고 rowcount 0으로 남는다.
            if "status = 'pending'" in sql and s["status"] != "pending":
                return
            s.update(status=status, resolved_by=resolved_by,
                     resolved_at="2026-07-02 11:00:00")
            self.rowcount = 1
        elif "SELECT * FROM memory_suggestions WHERE id" in sql:
            self._one = dict(self.db.suggestion[params[0]])
        elif "FROM memory m" in sql and "LEFT JOIN memory_sources" in sql:
            active_only = (
                "NOT EXISTS (SELECT 1 FROM memory visible_successor"
                in sql
            )
            want_category = params[1] if "m.category = %s" in sql else None
            rows = []
            for m in self.db.memory.values():
                if m["project_id"] != params[0]:
                    continue
                if (
                    active_only
                    and m["superseded_by"] in self.db.memory
                ):
                    continue
                if want_category is not None and m["category"] != want_category:
                    continue
                rows.append(dict(m))
            self._all = rows
        else:
            self._one, self._all = None, []

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._all

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Conn:
    def __init__(self, db):
        self.db = db

    def cursor(self):
        return _Cursor(self.db)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def _search_ids(project_id=1, **kwargs):
    return [
        r["id"]
        for r in mysql_search.search(
            project_id,
            category="decision",
            index_scope=ProjectIndexScope(project_id),
            **kwargs,
        )
    ]


def _accept(db, suggestion_id):
    with patch("backend.api.suggestion.require_project_access"), \
         patch("backend.api.suggestion.get_current_user_id", return_value=99), \
         patch("backend.retriever.memory_vector.delete_memory_vector"), \
         patch("backend.graph.refresh_project_memory_after_delete"), \
         patch("backend.api.suggestion.get_connection", return_value=_Conn(db)):
        return _client.post(f"/api/v1/projects/1/suggestions/{suggestion_id}/accept")


def test_accept_supersede_then_layer1_search_excludes_old_decision():
    """accept가 superseded_by를 채우면 계층1 기본 조회에서 구 decision이 빠지고,
    include_superseded=True면 다시 포함된다."""
    db = _FakeDB()

    with patch("backend.retriever.mysql_search.get_connection", return_value=_Conn(db)):
        # accept 전: 두 decision 모두 조회됨
        assert sorted(_search_ids()) == [10, 42]

    with patch("backend.api.suggestion.require_project_access"), \
         patch("backend.api.suggestion.get_current_user_id", return_value=99), \
         patch("backend.retriever.memory_vector.delete_memory_vector"), \
         patch("backend.graph.refresh_project_memory_after_delete"), \
         patch("backend.api.suggestion.get_connection", return_value=_Conn(db)):
        resp = _client.post("/api/v1/projects/1/suggestions/8/accept")
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"
    assert db.memory[10]["superseded_by"] == 42  # accept가 계층1 컬럼을 채움

    with patch("backend.retriever.mysql_search.get_connection", return_value=_Conn(db)):
        # accept 후: 구 decision(10)은 기본 조회에서 제외
        assert _search_ids() == [42]
        # 이력 조회(include_superseded=True)에서는 다시 포함
        assert sorted(_search_ids(include_superseded=True)) == [10, 42]


def test_superseding_decision_delete_restores_old_decision():
    """F-001: accept 후 대체(신) decision이 삭제(repo 재동기화 등)되면
    self-FK ON DELETE SET NULL이 포인터를 해제해 구 decision이 기본 조회에 복귀한다.
    dangling id를 가리킨 채 영구 은닉되지 않는다."""
    db = _FakeDB()
    assert _accept(db, 8).status_code == 200
    assert db.memory[10]["superseded_by"] == 42

    with patch("backend.retriever.mysql_search.get_connection", return_value=_Conn(db)):
        assert _search_ids() == [42]

    db.delete_memory(42)  # 대체 decision 삭제 → FK가 10의 포인터를 NULL로 되돌림

    assert db.memory[10]["superseded_by"] is None
    with patch("backend.retriever.mysql_search.get_connection", return_value=_Conn(db)):
        assert _search_ids() == [10]  # 구 decision 복귀 — 주제의 결정이 전멸하지 않는다


def test_accept_rejected_when_superseding_row_is_no_longer_decision():
    """F-004: 제안 생성 후 대체 row의 category가 decision이 아니게 바뀌었으면 409.
    action 등으로 정상 decision을 숨길 수 없다."""
    db = _FakeDB()
    db.memory[42]["category"] = "action"  # 사용자가 제안 생성 후 수정

    resp = _accept(db, 8)

    assert resp.status_code == 409
    assert db.memory[10]["superseded_by"] is None  # 구 decision은 숨겨지지 않았다


def test_accept_reverse_supersede_of_superseded_decision_is_rejected():
    """순환 가드: A→B accept 후 B→A(역방향) 제안을 accept하면 둘 다 숨어
    해당 주제의 결정이 기본 조회에서 전멸한다. 이미 번복된 decision(A)은
    대체자가 될 수 없으므로 409로 거부한다."""
    db = _FakeDB()
    assert _accept(db, 8).status_code == 200  # 10 → 42

    db.suggestion[9] = {**db.suggestion[8], "id": 9, "memory_id": 42,
                        "evidence": '{"type":"supersede","superseding_memory_id":10}',
                        "status": "pending"}
    resp = _accept(db, 9)

    assert resp.status_code == 409
    assert db.memory[42]["superseded_by"] is None  # 42는 여전히 살아있는 결정
    with patch("backend.retriever.mysql_search.get_connection", return_value=_Conn(db)):
        assert _search_ids() == [42]  # 기본 조회가 비지 않는다
