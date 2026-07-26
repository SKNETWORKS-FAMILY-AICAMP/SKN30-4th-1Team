"""memory_suggestions API 계약 테스트."""
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.main import app

_client = TestClient(app, raise_server_exceptions=False)


def _make_conn(fetchone=None, fetchall=None):
    cursor = MagicMock()
    cursor.fetchone.side_effect = fetchone if isinstance(fetchone, list) else None
    if not isinstance(fetchone, list):
        cursor.fetchone.return_value = fetchone
    cursor.fetchall.return_value = fetchall if fetchall is not None else []
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    conn.cursor.return_value.__exit__.return_value = False
    return conn, cursor


def _suggestion_row(status="pending", completed_at=None):
    return {
        "id": 7,
        "project_id": 1,
        "memory_id": 10,
        "kind": "complete_action",
        "evidence": '{"type":"pr","number":20,"title":"backend bridge","url":"https://github.com/o/r/pull/20","merged_at":"2026-07-01T10:00:00Z"}',
        "rationale": "PR #20이 FastAPI 연동 작업을 구현했습니다.",
        "confidence": "high",
        "status": status,
        "created_at": "2026-07-02 10:00:00",
        "resolved_at": None,
        "memory_category": "action",
        "memory_completed_at": completed_at,
    }


def _split_action_row(status="pending"):
    evidence = (
        '{"type":"document","doc_id":5,"source":"2026-04-13.md","date":"2026-04-13",'
        '"quote":"인원관리는 완료, 알림은 진행중","done_part":"인원 관리 로직 완료",'
        '"remaining_part":"알림 로직 구현","original_content":"인원 관리 및 알림 로직 구현"}'
    )
    return {
        "id": 9,
        "project_id": 1,
        "memory_id": 10,
        "kind": "split_action",
        "evidence": evidence,
        "rationale": "'2026-04-13.md' 문서가 일부만 완료로 보고",
        "confidence": "high",
        "status": status,
        "created_at": "2026-07-02 10:00:00",
        "resolved_at": None,
        "memory_category": "action",
        "memory_completed_at": None,
    }


def _supersede_row(status="pending", superseded_by=None, memory_category="decision"):
    return {
        "id": 8,
        "project_id": 1,
        "memory_id": 10,
        "kind": "supersede",
        "evidence": '{"type":"supersede","superseding_memory_id":42}',
        "rationale": "새 결정이 기존 배포 방침을 대체합니다.",
        "confidence": "high",
        "status": status,
        "created_at": "2026-07-02 10:00:00",
        "resolved_at": None,
        "memory_category": memory_category,
        "memory_completed_at": None,
        "memory_superseded_by": superseded_by,
    }


# D-1: supersede accept는 _suggestion_or_404 뒤에 대체 decision 존재 확인 fetchone을 1회 더 한다.
_EXISTS = {"id": 42}  # 대체(신) decision이 존재함을 나타내는 행


def test_accept_supersede_sets_superseded_by_from_evidence():
    """POST accept(supersede) — 대상 decision에 superseded_by/superseded_at 설정 + 벡터 동기화."""
    row = _supersede_row(superseded_by=None)
    updated = {**row, "status": "accepted", "resolved_at": "2026-07-02 11:00:00"}
    conn, cur = _make_conn(fetchone=[row, _EXISTS, updated])
    with patch("backend.api.suggestion.require_project_access"), \
         patch("backend.retriever.memory_vector.delete_memory_vector") as mock_del, \
         patch("backend.graph.refresh_project_memory_after_delete") as mock_refresh, \
         patch("backend.api.suggestion.get_connection", return_value=conn):
        resp = _client.post("/api/v1/projects/1/suggestions/8/accept")

    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"
    supersede_updates = [
        call for call in cur.execute.call_args_list
        if "UPDATE memory SET superseded_by = %s" in call.args[0]
    ]
    assert len(supersede_updates) == 1
    # 첫 파라미터가 evidence의 superseding_memory_id(42)
    assert supersede_updates[0].args[1][0] == 42
    # D-4: 번복된 decision(10) 벡터를 제거해 후보 슬롯 소모 방지
    mock_del.assert_called_once_with(10)
    # G-001: 조망형 답변이 읽는 프로젝트 요약 캐시를 재생성해 숨긴 결정이 남지 않게 함
    mock_refresh.assert_called_once_with(1)


def test_accept_supersede_already_superseded_is_noop_on_memory():
    """이미 superseded된 decision이면 memory는 다시 건드리지 않는다."""
    row = _supersede_row(superseded_by=42)
    updated = {**row, "status": "accepted", "resolved_at": "2026-07-02 11:00:00"}
    conn, cur = _make_conn(fetchone=[row, _EXISTS, updated])
    with patch("backend.api.suggestion.require_project_access"), \
         patch("backend.retriever.memory_vector.delete_memory_vector"), \
         patch("backend.graph.refresh_project_memory_after_delete"), \
         patch("backend.api.suggestion.get_connection", return_value=conn):
        resp = _client.post("/api/v1/projects/1/suggestions/8/accept")

    assert resp.status_code == 200
    sql_calls = [call.args[0] for call in cur.execute.call_args_list]
    assert not any("UPDATE memory SET superseded_by" in sql for sql in sql_calls)


def test_accept_supersede_missing_superseding_decision_is_409():
    """D-1: 대체(신) decision이 이미 삭제됐으면 409 — 존재하지 않는 id로 숨기지 않는다."""
    row = _supersede_row(superseded_by=None)
    conn, cur = _make_conn(fetchone=[row, None])  # 존재 확인이 None
    with patch("backend.api.suggestion.require_project_access"), \
         patch("backend.api.suggestion.get_connection", return_value=conn):
        resp = _client.post("/api/v1/projects/1/suggestions/8/accept")

    assert resp.status_code == 409
    sql_calls = [call.args[0] for call in cur.execute.call_args_list]
    assert not any("UPDATE memory SET superseded_by" in sql for sql in sql_calls)


def test_accept_supersede_existence_check_requires_live_decision():
    """F-004+순환 가드: 대체(신) 항목 검증 SELECT는 category='decision'과
    superseded_by IS NULL 조건을 포함해야 한다 — 제안 생성 후 category가 바뀐 row나
    이미 번복된 decision(A→B 후 B→A 순환)으로 정상 결정을 숨기지 못하도록."""
    row = _supersede_row(superseded_by=None)
    updated = {**row, "status": "accepted", "resolved_at": "2026-07-02 11:00:00"}
    conn, cur = _make_conn(fetchone=[row, _EXISTS, updated])
    with patch("backend.api.suggestion.require_project_access"), \
         patch("backend.retriever.memory_vector.delete_memory_vector"), \
         patch("backend.graph.refresh_project_memory_after_delete"), \
         patch("backend.api.suggestion.get_connection", return_value=conn):
        resp = _client.post("/api/v1/projects/1/suggestions/8/accept")

    assert resp.status_code == 200
    existence_checks = [
        call.args[0] for call in cur.execute.call_args_list
        if call.args[0].strip().startswith("SELECT id FROM memory WHERE id")
    ]
    assert len(existence_checks) == 1
    assert "category = 'decision'" in existence_checks[0]
    assert "superseded_by IS NULL" in existence_checks[0]


def test_accept_supersede_conflict_when_superseded_by_other():
    """C-2: 대상 decision이 이미 다른 decision으로 번복돼 있으면 409로 거부(이력 불일치 방지)."""
    row = _supersede_row(superseded_by=7)  # evidence는 42를 가리키지만 이미 7로 번복됨
    conn, cur = _make_conn(fetchone=[row, _EXISTS])
    with patch("backend.api.suggestion.require_project_access"), \
         patch("backend.api.suggestion.get_connection", return_value=conn):
        resp = _client.post("/api/v1/projects/1/suggestions/8/accept")

    assert resp.status_code == 409
    sql_calls = [call.args[0] for call in cur.execute.call_args_list]
    assert not any("UPDATE memory SET superseded_by" in sql for sql in sql_calls)


def test_accept_supersede_conflict_on_lost_race():
    """C-2: 조건부 UPDATE가 0행이면(경합으로 먼저 설정됨) 409로 거부한다."""
    row = _supersede_row(superseded_by=None)
    conn, cur = _make_conn(fetchone=[row, _EXISTS])
    cur.rowcount = 0  # WHERE superseded_by IS NULL 이 아무 행도 못 맞춤
    with patch("backend.api.suggestion.require_project_access"), \
         patch("backend.api.suggestion.get_connection", return_value=conn):
        resp = _client.post("/api/v1/projects/1/suggestions/8/accept")

    assert resp.status_code == 409


def test_accept_supersede_validation_locks_superseding_row():
    """L-002: 대체(신) decision 검증 SELECT는 FOR UPDATE로 행을 잠근다 —
    상호(A→B·B→A) 제안 동시 승인 시 두 검증이 모두 상대를 활성으로 읽고
    순환(두 결정 전멸)이 완성되는 TOCTOU를 차단한다."""
    row = _supersede_row(superseded_by=None)
    updated = {**row, "status": "accepted", "resolved_at": "2026-07-02 11:00:00"}
    conn, cur = _make_conn(fetchone=[row, _EXISTS, updated])
    with patch("backend.api.suggestion.require_project_access"), \
         patch("backend.retriever.memory_vector.delete_memory_vector"), \
         patch("backend.graph.refresh_project_memory_after_delete"), \
         patch("backend.api.suggestion.get_connection", return_value=conn):
        resp = _client.post("/api/v1/projects/1/suggestions/8/accept")

    assert resp.status_code == 200
    check_sql = next(
        c.args[0] for c in cur.execute.call_args_list
        if c.args[0].strip().startswith("SELECT id FROM memory WHERE id")
    )
    assert "FOR UPDATE" in check_sql


def test_resolve_deadlock_maps_to_409():
    """L-002: 교차 잠금 데드락(1213)으로 InnoDB가 트랜잭션을 중단시키면
    500이 아니라 409(경합 충돌)로 응답하고 롤백한다."""
    import pymysql
    row = _supersede_row(superseded_by=None)
    conn, cur = _make_conn(fetchone=[row])
    cur.execute.side_effect = [
        None,  # _suggestion_or_404 SELECT
        pymysql.err.OperationalError(1213, "Deadlock found when trying to get lock"),
    ]
    with patch("backend.api.suggestion.require_project_access"), \
         patch("backend.api.suggestion.get_connection", return_value=conn):
        resp = _client.post("/api/v1/projects/1/suggestions/8/accept")

    assert resp.status_code == 409
    assert conn.rollback.called
    assert not conn.commit.called


def test_accept_unknown_kind_is_rejected():
    """C-3: 지원하지 않는 kind는 400으로 거부 — 기본 분기로 흘러 completed_at을 설정하지 않는다."""
    row = {**_supersede_row(), "kind": "frobnicate"}
    conn, cur = _make_conn(fetchone=[row])
    with patch("backend.api.suggestion.require_project_access"), \
         patch("backend.api.suggestion.get_connection", return_value=conn):
        resp = _client.post("/api/v1/projects/1/suggestions/8/accept")

    assert resp.status_code == 400
    sql_calls = [call.args[0] for call in cur.execute.call_args_list]
    assert not any("UPDATE memory SET" in sql for sql in sql_calls)


def test_supersede_suggestion_targeting_wrong_category_is_404():
    """supersede 대상 memory가 decision이 아니면 404(잘못된 대상 방지)."""
    row = _supersede_row(memory_category="action")
    conn, _ = _make_conn(fetchone=[row])
    with patch("backend.api.suggestion.require_project_access"), \
         patch("backend.api.suggestion.get_connection", return_value=conn):
        resp = _client.post("/api/v1/projects/1/suggestions/8/accept")

    assert resp.status_code == 404


def test_list_pending_suggestions_returns_evidence_and_rationale():
    """GET suggestions — pending 목록에 evidence/rationale 포함."""
    conn, _ = _make_conn(fetchone=[{"id": 1}], fetchall=[_suggestion_row()])
    with patch("backend.api.suggestion.require_project_access"), \
         patch("backend.api.suggestion.get_connection", return_value=conn):
        resp = _client.get("/api/v1/projects/1/suggestions")

    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["evidence"]["number"] == 20
    assert body[0]["rationale"] == "PR #20이 FastAPI 연동 작업을 구현했습니다."


def test_list_suggestions_defaults_to_complete_action_kind():
    """H-001: kind 파라미터 없는 기존 클라이언트에는 complete_action만 반환한다.
    supersede evidence에는 title이 없어 구 데스크톱이 evidence.title.trim()에서
    죽으므로, 새 kind는 기본 목록에 섞이지 않아야 한다."""
    conn, cur = _make_conn(fetchone=[{"id": 1}], fetchall=[_suggestion_row()])
    with patch("backend.api.suggestion.require_project_access"), \
         patch("backend.api.suggestion.get_connection", return_value=conn):
        resp = _client.get("/api/v1/projects/1/suggestions")

    assert resp.status_code == 200
    sql, params = cur.execute.call_args.args  # 마지막 execute = 목록 SELECT
    assert "AND kind = %s" in sql
    assert params[-1] == "complete_action"


def test_list_suggestions_kind_supersede_opt_in():
    """H-001: supersede를 아는 클라이언트는 ?kind=supersede로 opt-in 조회한다."""
    conn, cur = _make_conn(fetchone=[{"id": 1}], fetchall=[])
    with patch("backend.api.suggestion.require_project_access"), \
         patch("backend.api.suggestion.get_connection", return_value=conn):
        resp = _client.get("/api/v1/projects/1/suggestions?kind=supersede")

    assert resp.status_code == 200
    sql, params = cur.execute.call_args.args
    assert "AND kind = %s" in sql
    assert params[-1] == "supersede"


def test_list_suggestions_kind_all_returns_every_kind():
    """H-001: ?kind=all은 kind 필터 없이 전체를 반환한다."""
    conn, cur = _make_conn(fetchone=[{"id": 1}], fetchall=[])
    with patch("backend.api.suggestion.require_project_access"), \
         patch("backend.api.suggestion.get_connection", return_value=conn):
        resp = _client.get("/api/v1/projects/1/suggestions?kind=all")

    assert resp.status_code == 200
    sql = cur.execute.call_args.args[0]
    assert "AND kind = %s" not in sql


def test_list_suggestions_unknown_kind_is_400():
    """H-001: 알 수 없는 kind는 400 — 오타가 빈 목록으로 위장하지 않는다."""
    with patch("backend.api.suggestion.require_project_access"):
        resp = _client.get("/api/v1/projects/1/suggestions?kind=frobnicate")

    assert resp.status_code == 400


def test_resolve_suggestion_update_is_conditional_on_pending():
    """H-003: 해소 UPDATE는 status='pending' 조건부다 — 동시 accept/reject 경쟁에서
    나중 요청이 확정된 상태를 덮어쓰지(효과·기록 불일치) 못하도록."""
    row = _suggestion_row(completed_at=None)
    updated = {**row, "status": "rejected", "resolved_at": "2026-07-02 11:00:00"}
    conn, cur = _make_conn(fetchone=[row, updated])
    with patch("backend.api.suggestion.require_project_access"), \
         patch("backend.api.suggestion.get_connection", return_value=conn):
        resp = _client.post("/api/v1/projects/1/suggestions/7/reject")

    assert resp.status_code == 200
    update_sqls = [
        c.args[0] for c in cur.execute.call_args_list
        if "UPDATE memory_suggestions SET status" in c.args[0]
    ]
    assert len(update_sqls) == 1
    assert "AND status = 'pending'" in update_sqls[0]


def test_resolve_suggestion_lost_race_is_409():
    """H-003: 조건부 UPDATE가 0행이면(다른 요청이 먼저 해소) 409로 거부하고 롤백한다."""
    row = _suggestion_row(completed_at=None)
    conn, cur = _make_conn(fetchone=[row])
    cur.rowcount = 0  # 초기 검사 후 다른 요청이 먼저 해소한 경합 상황
    with patch("backend.api.suggestion.require_project_access"), \
         patch("backend.api.suggestion.get_connection", return_value=conn):
        resp = _client.post("/api/v1/projects/1/suggestions/7/reject")

    assert resp.status_code == 409
    assert conn.rollback.called
    assert not conn.commit.called


def test_accept_suggestion_completes_open_action_and_resolves_suggestion():
    """POST accept — 미완료 action은 completed_at=NOW(), suggestion은 accepted."""
    row = _suggestion_row(completed_at=None)
    updated = {**row, "status": "accepted", "resolved_at": "2026-07-02 11:00:00"}
    # 두 번째 fetchone: _apply_accepted_effect의 SELECT ... FOR UPDATE(최신 상태 재확인)용.
    locked = {"content": "원본 action 내용", "completed_at": None}
    conn, cur = _make_conn(fetchone=[row, locked, updated])
    with patch("backend.api.suggestion.require_project_access"), \
         patch("backend.api.suggestion.get_connection", return_value=conn):
        resp = _client.post("/api/v1/projects/1/suggestions/7/accept")

    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"
    sql_calls = [call.args[0] for call in cur.execute.call_args_list]
    completion_sql = next(sql for sql in sql_calls if "UPDATE memory SET completed_at = NOW()" in sql)
    assert "completion_status = 'completed'" in completion_sql
    assert "completion_status_source = 'pr'" in completion_sql
    assert any("UPDATE memory_suggestions SET status = %s" in sql for sql in sql_calls)


def test_accept_completed_action_only_resolves_suggestion():
    """POST accept — 이미 완료된 action이면 memory는 건드리지 않는다."""
    row = _suggestion_row(completed_at="2026-07-01 09:00:00")
    updated = {**row, "status": "accepted", "resolved_at": "2026-07-02 11:00:00"}
    # SELECT ... FOR UPDATE 재확인도 이미 완료 상태를 봐야 멱등 반환 경로를 탄다.
    locked = {"content": "원본 action 내용", "completed_at": "2026-07-01 09:00:00"}
    conn, cur = _make_conn(fetchone=[row, locked, updated])
    with patch("backend.api.suggestion.require_project_access"), \
         patch("backend.api.suggestion.get_connection", return_value=conn):
        resp = _client.post("/api/v1/projects/1/suggestions/7/accept")

    assert resp.status_code == 200
    sql_calls = [call.args[0] for call in cur.execute.call_args_list]
    assert not any("UPDATE memory SET completed_at = NOW()" in sql for sql in sql_calls)


def test_accept_split_action_rewrites_original_and_creates_completed_row():
    """POST accept(split_action) — 원본은 remaining_part만 남기고 열어두고, done_part는
    새 행으로 분리해 그 문서 날짜로 즉시 completed 처리한다."""
    row = _split_action_row()
    updated = {**row, "status": "accepted", "resolved_at": "2026-07-02 11:00:00"}
    locked = {"content": "인원 관리 및 알림 로직 구현", "completed_at": None}  # original_content와 일치 = 안 낡음
    conn, cur = _make_conn(fetchone=[row, locked, updated])
    cur.lastrowid = 55  # 새로 분리되는 행의 id
    with patch("backend.api.suggestion.require_project_access"), \
         patch("backend.api.suggestion.get_connection", return_value=conn), \
         patch("backend.retriever.memory_vector.upsert_memory_vectors") as mock_upsert:
        resp = _client.post("/api/v1/projects/1/suggestions/7/accept")

    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"
    sql_calls = [call.args[0] for call in cur.execute.call_args_list]

    rewrite_sql = next(sql for sql in sql_calls if sql.startswith("UPDATE memory SET content"))
    rewrite_params = next(
        c.args[1] for c in cur.execute.call_args_list if c.args[0] is rewrite_sql
    )
    assert rewrite_params[0] == "알림 로직 구현"  # remaining_part만 남음

    insert_sql = next(sql for sql in sql_calls if "INSERT INTO memory" in sql and "category" in sql)
    insert_params = next(
        c.args[1] for c in cur.execute.call_args_list if c.args[0] is insert_sql
    )
    assert "인원 관리 로직 완료" in insert_params  # done_part로 새 행 생성
    assert "2026-04-13" in insert_params  # 문서 날짜로 completed_at

    mock_upsert.assert_called_once()  # 원본·신규 두 행 벡터 재동기화


def test_accept_split_action_rejects_stale_content():
    """POST accept(split_action) — 그 사이 content가 바뀌었으면(다른 제안이 먼저 승인됨
    등) 409로 거부하고 memory를 건드리지 않는다."""
    row = _split_action_row()
    locked = {"content": "이미 바뀐 내용", "completed_at": None}  # original_content와 불일치
    conn, cur = _make_conn(fetchone=[row, locked])
    with patch("backend.api.suggestion.require_project_access"), \
         patch("backend.api.suggestion.get_connection", return_value=conn):
        resp = _client.post("/api/v1/projects/1/suggestions/7/accept")

    assert resp.status_code == 409
    assert conn.rollback.called
    sql_calls = [call.args[0] for call in cur.execute.call_args_list]
    assert not any(sql.startswith("UPDATE memory SET content") for sql in sql_calls)
    assert not any("INSERT INTO memory" in sql and "category" in sql for sql in sql_calls)


def test_reject_suggestion_only_resolves_suggestion():
    """POST reject — action은 변경하지 않고 suggestion만 rejected."""
    row = _suggestion_row(completed_at=None)
    updated = {**row, "status": "rejected", "resolved_at": "2026-07-02 11:00:00"}
    conn, cur = _make_conn(fetchone=[row, updated])
    with patch("backend.api.suggestion.require_project_access"), \
         patch("backend.api.suggestion.get_connection", return_value=conn):
        resp = _client.post("/api/v1/projects/1/suggestions/7/reject")

    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"
    sql_calls = [call.args[0] for call in cur.execute.call_args_list]
    assert not any("UPDATE memory SET completed_at = NOW()" in sql for sql in sql_calls)


def test_resolve_suggestion_denies_viewer():
    """R-003: viewer는 accept/reject를 할 수 없다 (member 경계 검증).

    실제 require_project_access를 통과시키고 역할 조회만 viewer로 mock한다.
    이전 테스트는 require_project_access 호출 유무만 봐서, _resolve_suggestion이
    기본 viewer 권한으로 회귀해도 통과하는 맹점이 있었다. 실제 역할로 검증한다.
    """
    with patch("backend.api.auth.get_current_user_id", return_value=99), \
         patch("backend.api.auth.get_project_role", return_value="viewer"):
        accept = _client.post("/api/v1/projects/1/suggestions/7/accept")
        reject = _client.post("/api/v1/projects/1/suggestions/7/reject")

    assert accept.status_code == 403
    assert reject.status_code == 403


def test_resolve_suggestion_allows_member():
    """R-003: member는 accept/reject가 허용된다 (viewer 거부와 대칭 확인)."""
    row = _suggestion_row(completed_at=None)
    updated = {**row, "status": "accepted", "resolved_at": "2026-07-02 11:00:00"}
    locked = {"content": "원본 action 내용", "completed_at": None}
    conn, _ = _make_conn(fetchone=[row, locked, updated])
    with patch("backend.api.auth.get_current_user_id", return_value=99), \
         patch("backend.api.auth.get_project_role", return_value="member"), \
         patch("backend.api.suggestion.get_connection", return_value=conn):
        accept = _client.post("/api/v1/projects/1/suggestions/7/accept")

    assert accept.status_code == 200
    assert accept.json()["status"] == "accepted"
