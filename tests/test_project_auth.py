"""DEV user seed, list_projects membership filter, ensure_dev_user 단위 테스트."""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from backend.main import app

_client = TestClient(app, raise_server_exceptions=False)


def _make_conn(fetchone=None, fetchall=None, lastrowid=1):
    """cursor와 conn을 함께 반환. conn.cursor().__enter__() → cursor."""
    cursor = MagicMock()
    cursor.fetchone.return_value = fetchone
    cursor.fetchall.return_value = fetchall if fetchall is not None else []
    cursor.lastrowid = lastrowid
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    conn.cursor.return_value.__exit__.return_value = False
    return conn, cursor


def _make_conn_sequence(fetchone=None, fetchall=None, lastrowid=1):
    """fetchone/fetchall 호출 순서를 지정하는 cursor와 conn을 반환한다."""
    cursor = MagicMock()
    cursor.fetchone.side_effect = fetchone or []
    cursor.fetchall.side_effect = fetchall or []
    cursor.lastrowid = lastrowid
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    conn.cursor.return_value.__exit__.return_value = False
    return conn, cursor


# ── list_projects ──────────────────────────────────────────────────

def test_list_projects_no_user_returns_all():
    """DEV_USER_ID 미설정 → SELECT * (JOIN 없이 전체) 쿼리 사용."""
    conn, cursor = _make_conn(fetchall=[{"id": 1, "name": "p1"}, {"id": 2, "name": "p2"}])
    with patch("backend.api.project.get_current_user_id", return_value=None), \
         patch("backend.api.project.get_connection", return_value=conn):
        resp = _client.get("/api/v1/projects")
    assert resp.status_code == 200
    assert len(resp.json()) == 2
    sql = cursor.execute.call_args[0][0]
    assert "JOIN" not in sql


def test_list_projects_with_user_filters_by_membership():
    """DEV_USER_ID 설정 → membership JOIN 쿼리 + user_id 바인딩 사용."""
    conn, cursor = _make_conn(fetchall=[{"id": 1, "name": "p1"}])
    with patch("backend.api.project.get_current_user_id", return_value=1), \
         patch("backend.api.project.get_connection", return_value=conn):
        resp = _client.get("/api/v1/projects")
    assert resp.status_code == 200
    sql, params = cursor.execute.call_args[0]
    assert "JOIN" in sql
    assert "pm.user_id" in sql
    assert params == (1,)


# ── create_project with dev user ───────────────────────────────────

def test_create_project_with_dev_user_adds_member():
    """ensure_dev_user() → user_id 있으면 project_members owner row INSERT."""
    conn, cursor = _make_conn(
        fetchone={"id": 42, "name": "test", "created_at": "2026-07-02"},
        lastrowid=42,
    )
    with patch("backend.api.project.ensure_dev_user", return_value=1), \
         patch("backend.api.project.get_connection", return_value=conn):
        resp = _client.post("/api/v1/projects", json={"name": "test"})
    assert resp.status_code == 201
    sql_calls = [c[0][0] for c in cursor.execute.call_args_list]
    assert any("project_members" in sql for sql in sql_calls)


def test_create_project_without_dev_user_skips_member():
    """ensure_dev_user() → None 이면 project_members INSERT 생략."""
    conn, cursor = _make_conn(
        fetchone={"id": 10, "name": "anon", "created_at": "2026-07-02"},
        lastrowid=10,
    )
    with patch("backend.api.project.ensure_dev_user", return_value=None), \
         patch("backend.api.project.get_connection", return_value=conn):
        resp = _client.post("/api/v1/projects", json={"name": "anon"})
    assert resp.status_code == 201
    sql_calls = [c[0][0] for c in cursor.execute.call_args_list]
    assert not any("project_members" in sql for sql in sql_calls)


# ── update/delete project ─────────────────────────────────────────

def test_update_project_persists_name():
    """PATCH /projects/{id} — name을 trim해서 projects row에 저장한다."""
    conn, cursor = _make_conn_sequence(
        fetchone=[
            {"id": 1},
            {"id": 1, "name": "renamed", "created_at": "2026-07-02"},
        ],
    )
    with patch("backend.api.project.require_project_access"), \
         patch("backend.api.project.get_connection", return_value=conn):
        resp = _client.patch("/api/v1/projects/1", json={"name": "  renamed  "})

    assert resp.status_code == 200
    assert resp.json()["name"] == "renamed"
    assert any(
        call.args[0] == "UPDATE projects SET name = %s WHERE id = %s"
        and call.args[1] == ("renamed", 1)
        for call in cursor.execute.call_args_list
    )


def test_delete_project_cleans_children_and_external_assets():
    """DELETE /projects/{id} — FK 자식 row와 suggestion, Chroma, 원본 파일을 정리한다."""
    conn, cursor = _make_conn_sequence(
        fetchone=[{"id": 1}, None, None],
        fetchall=[
            [{"id": 3, "file_path": "data/uploads/1/spec.md", "uploaded_by": None, "status": "indexed"}],
            [],
            [{"id": 4}],
            [{"id": 5}],
        ],
    )
    with patch("backend.api.project.require_project_access"), \
         patch("backend.api.project._project_upload_users", return_value=set()), \
         patch("backend.api.project.get_connection", return_value=conn), \
         patch("backend.db.chroma.delete_from_existing_collection") as chroma_delete, \
         patch("backend.api.project.delete_managed_file") as delete_file:
        resp = _client.delete("/api/v1/projects/1")

    assert resp.status_code == 204
    # 삭제는 metadata 조건만 쓰므로 임베딩 클라이언트를 만드는 get_collection() 이 아니라
    # delete_from_existing_collection 을 타야 한다 — 전자는 OPENAI_API_KEY 가 없으면
    # 프로젝트 삭제 전체를 500으로 실패시킨다. 단언 내용(project_id 조건 삭제)은 동일하다.
    chroma_delete.assert_called_once_with(where={"project_id": 1})
    delete_file.assert_called_once_with("data/uploads/1/spec.md", 1)

    sql_calls = [call.args[0] for call in cursor.execute.call_args_list]

    def sql_index(fragment: str) -> int:
        return next(i for i, sql in enumerate(sql_calls) if fragment in sql)

    processing_probe = next(
        sql for sql in sql_calls if "status='processing'" in sql and "SELECT 1" in sql
    )
    assert "FOR UPDATE" not in processing_probe
    assert any("DELETE FROM memory_suggestions" in sql for sql in sql_calls)
    assert any("DELETE ms FROM memory_sources" in sql for sql in sql_calls)
    assert any("DELETE FROM chat_messages" in sql for sql in sql_calls)
    assert any("DELETE FROM chat_summaries" in sql for sql in sql_calls)
    assert sql_index("DELETE FROM memory_suggestions") < sql_index("DELETE FROM memory WHERE")
    assert sql_index("DELETE FROM memory WHERE") < sql_index("DELETE FROM documents")
    assert sql_index("DELETE FROM chat_messages") < sql_index("DELETE FROM chat_sessions")
    assert sql_index("DELETE FROM project_members") < sql_index("DELETE FROM projects")
    conn.commit.assert_called_once()


def test_delete_project_missing_returns_404():
    """DELETE /projects/{id} — 없는 프로젝트는 404를 반환한다."""
    conn, _ = _make_conn(fetchone=None)
    with patch("backend.api.project.require_project_access"), \
         patch("backend.api.project.get_connection", return_value=conn):
        resp = _client.delete("/api/v1/projects/404")

    assert resp.status_code == 404


def test_get_project_missing_returns_404():
    """GET /projects/{id} — 삭제된 프로젝트 조회는 404로 수렴한다."""
    conn, _ = _make_conn(fetchone=None)
    with patch("backend.api.project.require_project_access"), \
         patch("backend.api.project.get_connection", return_value=conn):
        resp = _client.get("/api/v1/projects/404")

    assert resp.status_code == 404


# ── ensure_dev_user ────────────────────────────────────────────────

def test_ensure_dev_user_creates_user_if_missing():
    """users row 없으면 INSERT 실행 후 user_id 반환."""
    conn, cursor = _make_conn(fetchone=None)  # SELECT → None: row 없음
    with patch("backend.api.auth.get_current_user_id", return_value=1), \
         patch("backend.api.auth.get_connection", return_value=conn), \
         patch.dict("os.environ", {"DEV_USER_EMAIL": "dev@local", "DEV_USER_NAME": "Dev"}):
        from backend.api.auth import ensure_dev_user
        result = ensure_dev_user()
    assert result == 1
    sql_calls = [c[0][0] for c in cursor.execute.call_args_list]
    assert any("INSERT" in sql for sql in sql_calls)


def test_ensure_dev_user_skips_insert_when_row_exists():
    """users row 있으면 INSERT 건너뜀, user_id 반환."""
    conn, cursor = _make_conn(fetchone={"id": 1})  # SELECT → row 존재
    with patch("backend.api.auth.get_current_user_id", return_value=1), \
         patch("backend.api.auth.get_connection", return_value=conn):
        from backend.api.auth import ensure_dev_user
        result = ensure_dev_user()
    assert result == 1
    sql_calls = [c[0][0] for c in cursor.execute.call_args_list]
    assert not any("INSERT" in sql for sql in sql_calls)


def test_ensure_dev_user_noop_when_no_dev_user_id():
    """DEV_USER_ID 미설정 → None 반환, DB 접근 없음."""
    with patch("backend.api.auth.get_current_user_id", return_value=None):
        from backend.api.auth import ensure_dev_user
        result = ensure_dev_user()
    assert result is None


@pytest.mark.parametrize("dev_user_id", ["0", "-1", "invalid"])
def test_invalid_dev_user_id_is_unset_and_never_upserted(monkeypatch, dev_user_id):
    monkeypatch.setenv("PAIM_AUTH_MODE", "dev")
    monkeypatch.setenv("DEV_USER_ID", dev_user_id)
    from backend.api.auth import ensure_dev_user, get_current_user_id

    with patch("backend.api.auth.get_connection") as get_connection:
        assert get_current_user_id() is None
        assert ensure_dev_user() is None
    get_connection.assert_not_called()
