"""mysql_search의 published-generation supersede 회귀 테스트."""
from unittest.mock import MagicMock, patch

import pytest

from backend.retriever import mysql_search
from backend.retriever.index_scope import ProjectIndexScope


_ACTIVE_PREDICATE = (
    "NOT EXISTS (SELECT 1 FROM memory visible_successor"
)


@pytest.fixture(autouse=True)
def _stable_empty_scope(monkeypatch):
    """Unit tests do not need a second real DB connection to capture scope."""
    monkeypatch.setattr(
        mysql_search,
        "load_project_index_scope",
        lambda project_id: ProjectIndexScope(project_id),
    )


def _make_conn():
    cursor = MagicMock()
    cursor.fetchall.return_value = []
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    conn.cursor.return_value.__exit__.return_value = False
    return conn, cursor


def _run(**kwargs):
    conn, cursor = _make_conn()
    with patch("backend.retriever.mysql_search.get_connection", return_value=conn):
        mysql_search.search(1, **kwargs)
    sql, params = cursor.execute.call_args.args
    return sql, params


class _FilteringCursor:
    """Interpret published visibility and the visible-successor predicate."""

    def __init__(self, rows):
        self._all_rows = rows
        self._result: list = []

    def execute(self, sql, params):
        visible_rows = [
            row for row in self._all_rows if row.get("_visible", True)
        ]
        if _ACTIVE_PREDICATE in sql:
            visible_ids = {row["id"] for row in visible_rows}
            self._result = [
                row
                for row in visible_rows
                if row["superseded_by"] not in visible_ids
            ]
        else:
            self._result = visible_rows

    def fetchall(self):
        # search()는 row를 mutate(pop/추가)하므로 복사본을 돌려준다.
        return [dict(r) for r in self._result]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _make_filtering_conn(rows):
    cursor = _FilteringCursor(rows)
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn


def _search_rows(rows, **kwargs):
    conn = _make_filtering_conn(rows)
    with patch("backend.retriever.mysql_search.get_connection", return_value=conn):
        return mysql_search.search(1, **kwargs)


# 정상 row와 superseded row가 혼재된 데이터셋.
_SUPERSEDE_ROWS = [
    {"id": 1, "superseded_by": None},
    {"id": 2, "superseded_by": 5},
    {"id": 3, "superseded_by": None},
    {"id": 5, "superseded_by": None},
]


def test_default_search_excludes_superseded():
    """기본 조회는 같은 scope에서 보이는 successor가 있는 항목을 제외한다."""
    sql, params = _run()
    assert _ACTIVE_PREDICATE in sql
    assert params == [1]


def test_include_superseded_omits_filter():
    """include_superseded=True이면 이력 조회를 위해 술어를 넣지 않는다."""
    sql, params = _run(include_superseded=True)
    assert _ACTIVE_PREDICATE not in sql
    assert params == [1]


def test_superseded_filter_combines_with_other_conditions():
    """필터가 category/owner 등 기존 조건과 독립적으로 조합되고 params 순서를 깨지 않는다."""
    sql, params = _run(category="decision", owner="Alice")
    assert _ACTIVE_PREDICATE in sql
    assert "m.category = %s" in sql
    assert "m.owner = %s" in sql
    # superseded 술어는 값 바인딩이 없으므로 params는 project_id/category/owner만.
    assert params == [1, "decision", "Alice"]


def test_include_superseded_still_applies_other_filters():
    """옵트인이어도 다른 필터는 그대로 적용된다."""
    sql, params = _run(category="decision", include_superseded=True)
    assert _ACTIVE_PREDICATE not in sql
    assert "m.category = %s" in sql
    assert params == [1, "decision"]


# --- R-001: 반환 row 차이로 검증하는 회귀 테스트 --------------------------------
# 위 테스트들은 생성된 SQL 문자열만 검사하므로, 술어가 문자열로 남아 있으나 실질
# 필터링이 사라지는 회귀를 잡지 못한다. 아래 두 테스트는 superseded 혼재 데이터에서
# 실제 반환 ID를 비교해 "기본 제외 / 옵트인 포함" 동작을 직접 검증한다.


def test_default_search_returns_only_active_rows():
    """기본 조회는 superseded row를 제외하고 활성 row만 반환한다."""
    result = _search_rows(_SUPERSEDE_ROWS)
    assert [r["id"] for r in result] == [1, 3, 5]


def test_include_superseded_returns_active_and_superseded_rows():
    """include_superseded=True이면 활성 row와 superseded row를 모두 반환한다."""
    result = _search_rows(_SUPERSEDE_ROWS, include_superseded=True)
    assert [r["id"] for r in result] == [1, 2, 3, 5]


def test_hidden_successor_does_not_hide_published_predecessor():
    """staging/old-generation successor는 기존 published row를 숨기지 않는다."""
    rows = [
        {"id": 10, "superseded_by": 11},
        {"id": 11, "superseded_by": None, "_visible": False},
    ]

    assert [row["id"] for row in _search_rows(rows)] == [10]
    assert [
        row["id"]
        for row in _search_rows(rows, include_superseded=True)
    ] == [10]


def test_default_search_reuses_one_captured_scope(monkeypatch):
    """Outer visibility and successor visibility bind the same run snapshot."""
    scope = ProjectIndexScope(1, active_run_ids=("run-1",))
    loader = MagicMock(return_value=scope)
    monkeypatch.setattr(mysql_search, "load_project_index_scope", loader)

    sql, params = _run()

    loader.assert_called_once_with(1)
    assert "m.repo_sync_run_id IN (%s)" in sql
    assert "visible_successor.repo_sync_run_id IN (%s)" in sql
    assert params == [1, "run-1", "run-1"]


# --- R-001: completed/overdue/due_within_days와 양쪽 모드의 술어·params 조합 -----


@pytest.mark.parametrize("include_superseded", [False, True])
@pytest.mark.parametrize(
    "kwargs, expected_fragments, expected_params",
    [
        ({"completed": True}, ["m.completion_status = %s"], [1, "completed"]),
        ({"completed": False}, ["m.completion_status = %s"], [1, "open"]),
        (
            {"text_query": "API_v2 100%!"},
            ["CONCAT_WS(' ', m.content, m.topic, m.reason) LIKE %s ESCAPE '!'"],
            [1, "%API!_v2 100!%!!%"],
        ),
        (
            {"overdue": True},
            ["m.due_date < CURDATE()", "m.completion_status = 'open'"],
            [1],
        ),
        (
            {"due_within_days": 7},
            [
                "m.due_date >= CURDATE()",
                "m.due_date <= DATE_ADD(CURDATE(), INTERVAL 7 DAY)",
            ],
            [1],
        ),
    ],
)
def test_filter_predicates_combine_with_supersede_mode(
    include_superseded, kwargs, expected_fragments, expected_params
):
    """상태/기한 술어가 양쪽 supersede 모드와 독립 조합되고,
    completion 상태 값도 project_id 뒤에 안전하게 바인딩된다."""
    sql, params = _run(include_superseded=include_superseded, **kwargs)

    for fragment in expected_fragments:
        assert fragment in sql

    if include_superseded:
        assert _ACTIVE_PREDICATE not in sql
    else:
        assert _ACTIVE_PREDICATE in sql

    assert params == expected_params


# --- TASK-004: fetch_supersede_graph 전용 조회 -----------------------------------


def test_fetch_supersede_graph_sql_limits_to_participating_decisions():
    """전용 조회는 같은 scope의 visible edge 참여 decision만 대상으로 한다.

    category='decision' 한정. 체인 행에도 충돌 없는 출처 라벨을 만들려면
    memory_sources JOIN이 필요하다(리뷰 C-002)."""
    conn, cursor = _make_conn()

    with patch("backend.retriever.mysql_search.get_connection", return_value=conn):
        mysql_search.fetch_supersede_graph(7)

    sql, params = cursor.execute.call_args.args
    assert "m.category = 'decision'" in sql
    assert "LEFT JOIN memory visible_successor" in sql
    assert "visible_successor.id AS superseded_by" in sql
    assert "visible_successor.id IS NOT NULL" in sql
    assert "EXISTS (SELECT 1 FROM memory visible_predecessor" in sql
    assert "visible_predecessor.superseded_by=m.id" in sql
    assert "LEFT JOIN memory_sources" in sql          # C-002: 출처 식별자 조인
    assert "ms.repo_id" in sql
    assert "ORDER BY m.id ASC" in sql
    assert params == [7]


def test_fetch_graph_reuses_one_generation_scope(monkeypatch):
    """Join, outer rows, and predecessor lookup bind one captured run."""
    scope = ProjectIndexScope(7, active_run_ids=("run-7",))
    loader = MagicMock(return_value=scope)
    monkeypatch.setattr(mysql_search, "load_project_index_scope", loader)
    conn, cursor = _make_conn()

    with patch(
        "backend.retriever.mysql_search.get_connection",
        return_value=conn,
    ):
        mysql_search.fetch_supersede_graph(7)

    loader.assert_called_once_with(7)
    sql, params = cursor.execute.call_args.args
    assert "visible_successor.repo_sync_run_id IN (%s)" in sql
    assert "m.repo_sync_run_id IN (%s)" in sql
    assert "visible_predecessor.repo_sync_run_id IN (%s)" in sql
    # JOIN placeholders precede WHERE placeholders in SQL order.
    assert params == ["run-7", 7, "run-7", "run-7"]


def test_fetch_supersede_graph_attaches_source_info():
    """C-002: 체인 행이 source_info(repo_id·path)를 실어, 다른 저장소의 동명
    파일이 repo#N으로 구분되도록 한다 — 없으면 이력 인용 근거성이 깨진다."""
    from backend.retriever import qa_engine
    row = {"id": 1, "category": "decision", "content": "정비", "superseded_by": None,
           "source": "README.md", "source_kind": "repository", "ms_doc_id": None,
           "ms_repo_id": 3, "source_type": "readme", "source_path": "README.md",
           "source_ref": "abc", "source_url": ""}
    cursor = MagicMock()
    cursor.fetchall.return_value = [dict(row)]
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor

    with patch("backend.retriever.mysql_search.get_connection", return_value=conn):
        [out] = mysql_search.fetch_supersede_graph(1)

    assert out["source_info"]["repo_id"] == 3
    assert out["source_info"]["path"] == "README.md"
    # 체인 행 라벨도 일반 검색 행처럼 repo#N으로 충돌 방지
    assert qa_engine._row_source_label(out) == "README.md (repo#3)"


class _GraphCursor:
    """fetch_supersede_graph의 술어를 행 필터로 해석하는 fake cursor.

    문자열 매칭이 아니라 반환 행 수 차이로 '관계 참여 행만 반환' 계약을 검증한다."""

    def __init__(self, rows):
        self._all_rows = rows
        self._result: list = []

    def execute(self, sql, params):
        assert "LEFT JOIN memory visible_successor" in sql
        visible_rows = [
            row for row in self._all_rows if row.get("_visible", True)
        ]
        visible_ids = {row["id"] for row in visible_rows}
        referenced = {
            row["superseded_by"]
            for row in visible_rows
            if row["superseded_by"] in visible_ids
        }
        selected = [
            r for r in visible_rows
            if r["category"] == "decision"
            and (
                r["superseded_by"] in visible_ids
                or r["id"] in referenced
            )
        ]
        self._result = sorted(
            (
                {
                    **row,
                    "superseded_by": (
                        row["superseded_by"]
                        if row["superseded_by"] in visible_ids
                        else None
                    ),
                }
                for row in selected
            ),
            key=lambda row: row["id"],
        )

    def fetchall(self):
        return [dict(r) for r in self._result]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_fetch_supersede_graph_returns_only_participating_rows():
    """관계 비참여 행(활성 단독 decision·타 카테고리)은 반환되지 않는다 —
    반환 행 수가 관계 참여 행 수에 비례해야 이력 모드 비용이 보장된다."""
    rows = [
        {"id": 1, "category": "decision", "superseded_by": 3},   # 시조
        {"id": 3, "category": "decision", "superseded_by": None}, # 참조되는 종단
        {"id": 5, "category": "decision", "superseded_by": None}, # 비참여 활성 decision
        {"id": 6, "category": "action",   "superseded_by": None}, # 타 카테고리
    ]
    cursor = _GraphCursor(rows)
    conn = MagicMock()
    conn.cursor.return_value = cursor

    with patch("backend.retriever.mysql_search.get_connection", return_value=conn):
        result = mysql_search.fetch_supersede_graph(1)

    assert [r["id"] for r in result] == [1, 3]


def test_fetch_supersede_graph_ignores_edge_to_hidden_successor():
    """History graph must not expose an edge that active search does not see."""
    rows = [
        {
            "id": 1,
            "category": "decision",
            "superseded_by": 2,
        },
        {
            "id": 2,
            "category": "decision",
            "superseded_by": None,
            "_visible": False,
        },
    ]
    cursor = _GraphCursor(rows)
    conn = MagicMock()
    conn.cursor.return_value = cursor

    with patch(
        "backend.retriever.mysql_search.get_connection",
        return_value=conn,
    ):
        result = mysql_search.fetch_supersede_graph(1)

    assert result == []


def test_fetch_graph_treats_node_with_hidden_successor_as_visible_terminal():
    """A visible incoming edge remains, but the hidden outgoing edge is NULL."""
    rows = [
        {"id": 1, "category": "decision", "superseded_by": 2},
        {"id": 2, "category": "decision", "superseded_by": 3},
        {
            "id": 3,
            "category": "decision",
            "superseded_by": None,
            "_visible": False,
        },
    ]
    cursor = _GraphCursor(rows)
    conn = MagicMock()
    conn.cursor.return_value = cursor

    with patch(
        "backend.retriever.mysql_search.get_connection",
        return_value=conn,
    ):
        result = mysql_search.fetch_supersede_graph(1)

    assert [row["id"] for row in result] == [1, 2]
    assert result[0]["superseded_by"] == 2
    assert result[1]["superseded_by"] is None
