"""TASK-004 계층 3 — qa_engine 이력 체인·주석·recency RRF 회귀 테스트.

전부 결정론적 단언: LLM(멀티쿼리)·벡터 검색·DB는 stub으로 대체하고,
체인 선택(앵커·컴포넌트·예산)·주석 포맷·청크 융합(게이트·정규화·동률)을
문자열/디버그 값으로 고정한다.
"""
import hashlib
import types
from unittest.mock import MagicMock, patch

import pytest

from backend.retriever import qa_engine
from backend.retriever.index_scope import ProjectIndexScope


@pytest.fixture(autouse=True)
def _published_index_scope(monkeypatch):
    monkeypatch.setattr(
        qa_engine,
        "load_project_index_scope",
        lambda project_id: ProjectIndexScope(project_id),
    )


# ── 공통 fixture ──────────────────────────────────────────────────────────────

def _row(rid, content, superseded_by=None, date=None, topic=None, reason=None,
         source="minutes.md", category="decision"):
    return {
        "id": rid, "project_id": 1, "category": category, "content": content,
        "reason": reason, "topic": topic, "owner": None, "date": date,
        "due_date": None, "completed_at": None, "source": source,
        "superseded_by": superseded_by, "superseded_at": None,
    }


def _empty_chunk_collection():
    collection = MagicMock()
    collection.get.return_value = {"documents": [], "metadatas": [], "ids": []}
    collection.query.side_effect = RuntimeError("vector unavailable in test")
    return collection


def _build(question, rows, graph_rows, *, scope="global", tokens=(),
           monkeypatch=None, collection=None, history_mode=True):
    monkeypatch.setattr(
        qa_engine.mysql_search, "search",
        lambda pid, **kwargs: [dict(r) for r in rows],
    )
    monkeypatch.setattr(
        qa_engine.mysql_search, "fetch_supersede_graph",
        lambda pid, **kwargs: [dict(r) for r in graph_rows],
    )
    with patch("backend.retriever.qa_engine.get_collection",
               return_value=collection or _empty_chunk_collection()):
        return qa_engine._build_context(
            1, question,
            history_mode=history_mode,
            history_scope=scope if history_mode else None,
            history_topic_tokens=sorted(tokens) if history_mode else None,
            query_variants=[question],
        )


# ── 앵커 독립성 ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("scope,tokens", [("global", ()), ("topical", ("jwt",))])
def test_chain_included_independent_of_ranking(monkeypatch, scope, tokens):
    """무관 활성 행 20개 속에서도 A→B→C 체인이 회수된다 — superseded 행의 벡터는
    삭제되므로 랭킹(A₁)이 아니라 활성 종단 전수 열거(A₂)가 포함을 보장해야 한다."""
    noise = [_row(100 + i, f"무관 항목 {i} 데이터베이스 백업 점검") for i in range(20)]
    chain = [
        _row(1, "세션 쿠키 인증 사용", superseded_by=2, date="2026-01-05"),
        _row(2, "OAuth 프록시 도입", superseded_by=3, date="2026-02-10"),
        _row(3, "JWT 도입", date="2026-03-01"),
    ]
    active_rows = noise + [chain[2]]

    context, sources, debug = _build(
        "JWT로 왜 바뀌었어?", active_rows, chain,
        scope=scope, tokens=tokens, monkeypatch=monkeypatch,
    )

    assert "[decision #1][→ #2로 대체됨]" in context
    assert "[decision #2][→ #3로 대체됨][← #1 대체]" in context
    assert "[decision #3][최신][← #2 대체]" in context
    assert debug["history_mode"] is True
    assert debug["history_rows_added"] >= 2  # A·B는 슬롯 밖에서 추가됨
    assert "minutes.md" in sources


# ── 컴포넌트 우선순위 · 정규화 통일 ────────────────────────────────────────────

_COMP_JWT = [
    _row(1, "세션 인증 유지", superseded_by=3, date="2026-01-05"),
    _row(3, "JWT 도입", date="2026-01-20"),
]
_COMP_DEPLOY = [
    _row(4, "배포 주기 1주", superseded_by=5, date="2026-06-01"),
    _row(5, "배포 주기 2주", date="2026-06-10"),
]


def test_topical_relevance_prefers_matching_component(monkeypatch):
    """주제형: 최신이지만 무관한 컴포넌트보다, 오래됐지만 주제 토큰이 겹치는
    컴포넌트가 먼저 온다. 관련도는 질문·컴포넌트 양쪽 canonical 정규화의 교집합."""
    monkeypatch.setenv("HISTORY_CHAIN_LIMIT", "1")  # soft=1, hard=3 → 첫 컴포넌트만
    context, _, debug = _build(
        "JWT로 왜 바뀌었어?", [], _COMP_JWT + _COMP_DEPLOY,
        scope="topical", tokens=("jwt",), monkeypatch=monkeypatch,
    )

    assert "[decision #1]" in context and "[decision #3]" in context  # jwt 컴포넌트
    assert "#4" not in context and "#5" not in context               # 배포 컴포넌트 생략
    assert "[이력 일부 생략됨]" not in context
    assert debug["history_truncated"] is False
    assert debug["chains_added"] == 1


def test_global_scope_orders_components_by_latest_date(monkeypatch):
    """전역형: 관련도 없이 컴포넌트 최신 날짜 내림차순 — 배포(6월) 체인이
    JWT(1월) 체인보다 먼저 나온다."""
    context, _, debug = _build(
        "왜 바뀌었어?", [], _COMP_JWT + _COMP_DEPLOY,
        scope="global", monkeypatch=monkeypatch,
    )

    assert debug["chains_added"] == 2
    assert debug["history_truncated"] is False
    assert context.index("[decision #4]") < context.index("[decision #1]")


# ── 예산 (soft/hard) ─────────────────────────────────────────────────────────

def _chain_rows(start_id, size, base_month, terminal_date_day=28):
    """start_id부터 size개 행의 단일 체인. 날짜는 순차 증가."""
    rows = []
    for i in range(size):
        rid = start_id + i
        rows.append(_row(
            rid, f"결정 {rid}",
            superseded_by=(rid + 1 if i < size - 1 else None),
            date=f"2026-{base_month:02d}-{min(i + 1, terminal_date_day):02d}",
        ))
    return rows


def test_budget_first_chain_atomic_second_skipped(monkeypatch):
    """7+7(soft=12): 첫 체인 7개 원자 포함 → 7+7=14>12 → 둘째 체인 통째 생략."""
    newer = _chain_rows(10, 7, base_month=6)   # 최신 — 먼저 선택됨
    older = _chain_rows(30, 7, base_month=1)
    context, _, debug = _build(
        "왜 바뀌었어?", [], newer + older, scope="global", monkeypatch=monkeypatch,
    )

    for rid in range(10, 17):
        assert f"[decision #{rid}]" in context
    for rid in range(30, 37):
        assert f"#{rid}" not in context
    assert "[이력 일부 생략됨]" in context
    assert debug["history_rows_added"] == 7
    assert debug["history_truncated"] is True


def test_budget_single_13_node_chain_included_atomically(monkeypatch):
    """13노드 단일 체인(soft=12 초과, hard=36 이하)은 원자 포함 — 절단 없음."""
    chain = _chain_rows(10, 13, base_month=3)
    context, _, debug = _build(
        "왜 바뀌었어?", [], chain, scope="global", monkeypatch=monkeypatch,
    )

    for rid in range(10, 23):
        assert f"[decision #{rid}]" in context
    assert "[이력 일부 생략됨]" not in context
    assert debug["history_rows_added"] == 13
    assert debug["history_truncated"] is False


def test_budget_hard_truncation_keeps_terminal_side(monkeypatch):
    """hard 초과 단일 체인은 종단 기준 역방향 BFS로 hard까지만 — 종단 쪽이 남는다."""
    monkeypatch.setenv("HISTORY_CHAIN_LIMIT", "1")  # soft=1, hard=3
    chain = _chain_rows(10, 5, base_month=3)        # 10→11→12→13→14(종단)
    context, _, debug = _build(
        "왜 바뀌었어?", [], chain, scope="global", monkeypatch=monkeypatch,
    )

    for rid in (12, 13, 14):
        assert f"[decision #{rid}]" in context
    for rid in (10, 11):
        # 행 라인은 생략된다 — 남은 행 주석의 [← #11 대체] 참조는 그래프 사실이라 허용
        assert f"[decision #{rid}]" not in context
    # 표시는 시간순(시조 → 최신)
    assert context.index("[decision #12]") < context.index("[decision #14]")
    assert "[이력 일부 생략됨]" in context
    assert debug["history_truncated"] is True


def test_hard_truncation_multi_predecessor_input_order_invariant(monkeypatch):
    """다중 선행자 hard 절단: 레벨 내 norm_date ↓ → id ↓ 선택이 입력 순서와 무관하다."""
    monkeypatch.setenv("HISTORY_CHAIN_LIMIT", "1")
    monkeypatch.setenv("HISTORY_CHAIN_HARD_LIMIT", "2")
    diamond = [
        _row(1, "선행 A", superseded_by=3, date="2026-01-01"),
        _row(2, "선행 B", superseded_by=3, date="2026-01-05"),  # 같은 레벨, 더 최신
        _row(3, "통합 결정", date="2026-02-01"),
    ]
    ctx_forward, _, _ = _build("왜 바뀌었어?", [], diamond,
                               scope="global", monkeypatch=monkeypatch)
    ctx_reversed, _, _ = _build("왜 바뀌었어?", [], list(reversed(diamond)),
                                scope="global", monkeypatch=monkeypatch)

    assert ctx_forward == ctx_reversed
    assert "[decision #2]" in ctx_forward and "[decision #3]" in ctx_forward
    assert "[decision #1]" not in ctx_forward  # 행 라인은 생략(주석의 #1 참조는 무관)


def test_slot_rows_not_double_counted_or_duplicated(monkeypatch):
    """일반 슬롯의 관계 참여 행은 주석 포맷으로 교체되고(1회 출력), 예산에 재집계되지 않는다."""
    chain = [
        _row(1, "구버전 결정", superseded_by=2, date="2026-01-01"),
        _row(2, "신버전 결정", date="2026-02-01"),
    ]
    context, _, debug = _build(
        "신버전 결정은 왜 바뀌었어?",
        [chain[1]],
        chain,
        scope="global",
        monkeypatch=monkeypatch,
    )

    assert context.count("신버전 결정") == 1                    # 중복 출력 없음
    assert "[decision #2][최신][← #1 대체] 신버전 결정" in context  # 주석 포맷으로 교체
    assert "[decision] 신버전" not in context
    assert debug["history_rows_added"] == 1                     # 추가는 #1뿐


# ── 순환 컴포넌트 · NULL date ─────────────────────────────────────────────────

def test_cyclic_component_included_deterministically(monkeypatch):
    """순환 A→B→C→A: 활성 종단이 없어도 canonical 앵커(id 최대)로 전 경로가 포함되고,
    전 행이 중간 형 주석([최신] 없음)이며, 반복 호출 결과가 동일하다."""
    cycle = [
        _row(1, "결정 알파", superseded_by=2, date="2026-01-01"),
        _row(2, "결정 베타", superseded_by=3, date="2026-01-10"),
        _row(3, "결정 감마", superseded_by=1, date="2026-01-20"),
    ]
    ctx1, _, debug = _build("왜 바뀌었어?", [], cycle, scope="global", monkeypatch=monkeypatch)
    ctx2, _, _ = _build("왜 바뀌었어?", [], list(reversed(cycle)), scope="global", monkeypatch=monkeypatch)

    assert ctx1 == ctx2
    for rid in (1, 2, 3):
        assert f"[decision #{rid}][→ #" in ctx1
    assert "[최신]" not in ctx1
    assert debug["history_rows_added"] == 3
    assert debug["chains_added"] == 1


def test_null_date_rows_sort_last_without_error(monkeypatch):
    """같은 레벨에 NULL·유효 date 혼재: norm_date=date.min 정규화로 TypeError 없이
    유효 날짜 행이 먼저 선택되고, 입력 순서 반전에 불변이다."""
    monkeypatch.setenv("HISTORY_CHAIN_LIMIT", "1")
    monkeypatch.setenv("HISTORY_CHAIN_HARD_LIMIT", "2")
    diamond = [
        _row(1, "날짜 없는 선행", superseded_by=3, date=None),
        _row(2, "날짜 있는 선행", superseded_by=3, date="2026-01-05"),
        _row(3, "통합 결정", date="2026-02-01"),
    ]
    ctx_forward, _, _ = _build("왜 바뀌었어?", [], diamond,
                               scope="global", monkeypatch=monkeypatch)
    ctx_reversed, _, _ = _build("왜 바뀌었어?", [], list(reversed(diamond)),
                                scope="global", monkeypatch=monkeypatch)

    assert ctx_forward == ctx_reversed
    assert "날짜 있는 선행" in ctx_forward
    assert "날짜 없는 선행" not in ctx_forward


# ── 주석 포맷 ─────────────────────────────────────────────────────────────────

def test_annotation_three_forms_and_reason(monkeypatch):
    """시조/중간/종단 3형 토큰 + reason 표기."""
    chain = [
        _row(1, "결정 원안", superseded_by=2, date="2026-01-01"),
        _row(2, "결정 수정안", superseded_by=3, date="2026-01-10", reason="예산 초과"),
        _row(3, "결정 최종안", date="2026-01-20"),
    ]
    context, _, _ = _build("왜 바뀌었어?", [], chain, scope="global", monkeypatch=monkeypatch)

    assert "[decision #1][→ #2로 대체됨] 결정 원안" in context
    assert "[← #1 대체]" not in context.split("결정 원안")[0]     # 시조에 ← 없음
    assert "[decision #2][→ #3로 대체됨][← #1 대체] 결정 수정안" in context
    assert "이유: 예산 초과" in context
    assert "[decision #3][최신][← #2 대체] 결정 최종안" in context


def test_annotation_multiple_predecessors_listed(monkeypatch):
    """다중 선행자는 [← #A, #B 대체]로 오름차순 나열."""
    diamond = [
        _row(1, "선행 A", superseded_by=3, date="2026-01-01"),
        _row(2, "선행 B", superseded_by=3, date="2026-01-05"),
        _row(3, "통합 결정", date="2026-02-01"),
    ]
    context, _, _ = _build("왜 바뀌었어?", [], diamond, scope="global", monkeypatch=monkeypatch)

    assert "[decision #3][최신][← #1, #2 대체] 통합 결정" in context


def test_no_annotation_outside_history_mode_and_for_nonparticipants(monkeypatch):
    """비이력 모드·비참여 행은 기존 포맷 그대로 — supersede 0건이면 이력 모드
    컨텍스트가 비이력 모드와 문자열 수준으로 동일하다."""
    rows = [_row(1, "일반 결정", date="2026-01-01"), _row(2, "일반 액션", category="action")]

    question = "일반 결정과 일반 액션"
    ctx_history, _, _ = _build(
        question, rows, [], scope="global", monkeypatch=monkeypatch
    )
    ctx_plain, _, plain_debug = _build(
        question, rows, [], monkeypatch=monkeypatch, history_mode=False
    )

    assert ctx_history == ctx_plain
    assert "[decision #" not in ctx_history
    assert "[decision] 일반 결정" in ctx_history
    assert ctx_history.startswith("[구조화 기록]\n")
    assert plain_debug["history_mode"] is False


def test_zero_relevance_component_slot_rows_keep_annotation(monkeypatch):
    """현재 질의로 선택된 슬롯은 topical 추가 대상이 아니어도 관계 주석을 유지한다."""
    monkeypatch.setenv("HISTORY_CHAIN_LIMIT", "1")  # jwt 체인만 포함, 배포 체인 생략
    deploy_terminal = _COMP_DEPLOY[1]  # id=5, [← #4 대체] 대상

    context, _, debug = _build(
        "JWT 이력과 배포 주기 2주", [deploy_terminal], _COMP_JWT + _COMP_DEPLOY,
        scope="topical", tokens=("jwt",), monkeypatch=monkeypatch,
    )

    assert debug["history_truncated"] is False
    assert "[decision #4]" not in context                          # 과거 행은 주제 무관
    assert "[decision #5][최신][← #4 대체] 배포 주기 2주" in context
    assert "[decision] 배포 주기 2주" not in context


def test_bm25_tie_input_order_invariant_without_dense(monkeypatch):
    """round-1 R-003: dense 후보·날짜가 없고 BM25 동점 청크가 TOP_N을 초과해도
    tie key 보조 정렬로 선택·순서가 입력 반전에 불변이다."""
    labels = ["알파", "베타", "감마", "델타", "엡실론", "제타"]
    # 전부 (라벨 1토큰 + '회의록') 2토큰 문서 — 질의 '회의록'에 동일 BM25 점수
    chunks = [(f"{label} 회의록", "", f"doc1_chunk{i}") for i, label in enumerate(labels)]

    _, _, debug_fwd = _build_chunks("회의록", ["회의록"], chunks, {}, monkeypatch)
    _, _, debug_rev = _build_chunks("회의록", ["회의록"], list(reversed(chunks)), {}, monkeypatch)

    order_fwd = [c["text"] for c in debug_fwd["chroma_chunks"]]
    order_rev = [c["text"] for c in debug_rev["chroma_chunks"]]
    expected = [f"{label} 회의록" for label in labels[:5]]  # tie key(ID) 오름차순 상위 5
    assert order_fwd == order_rev == expected
    assert all(c["dense_rank"] is None for c in debug_fwd["chroma_chunks"])


def test_chain_only_context_remains_visible_to_agentic_retrieval(monkeypatch):
    """round-1 R-004: 일반 슬롯 0행 + 체인 행만 있는 컨텍스트(전 행 superseded 순환)가
    Agentic evidence tool에 전달될 debug.mysql_rows에 반영되어야 한다."""

    cycle = [
        _row(1, "결정 알파", superseded_by=2, date="2026-01-01"),
        _row(2, "결정 베타", superseded_by=3, date="2026-01-10"),
        _row(3, "결정 감마", superseded_by=1, date="2026-01-20"),
    ]
    _, _, debug = _build("왜 바뀌었어?", [], cycle, scope="global", monkeypatch=monkeypatch)

    assert len(debug["mysql_rows"]) == 3
    assert {r["content"] for r in debug["mysql_rows"]} == {"결정 알파", "결정 베타", "결정 감마"}
    assert bool(debug["mysql_rows"] or debug["chroma_chunks"]) is True


def test_rewrite_suffix_selects_same_component_ids(monkeypatch):
    """재검색 불변성(_build_context 수준): 고정된 scope·토큰이 같으면 rewrite suffix가
    붙은 질문으로도 선택 컴포넌트/행 ID가 동일하다."""
    graph_rows = _COMP_JWT + _COMP_DEPLOY

    def _decisions(context):
        return sorted(
            line.split("]")[0] for line in context.splitlines()
            if line.startswith("[decision #")
        )

    ctx1, _, _ = _build("왜 바뀌었어?", [], graph_rows,
                        scope="global", monkeypatch=monkeypatch)
    ctx2, _, _ = _build("왜 바뀌었어? (관련 배경과 세부 내용 포함)", [], graph_rows,
                        scope="global", monkeypatch=monkeypatch)

    assert _decisions(ctx1) == _decisions(ctx2)


# ── 전용 조회 사용 ────────────────────────────────────────────────────────────

def test_history_mode_uses_dedicated_graph_query(monkeypatch):
    """이력 모드는 fetch_supersede_graph()를 쓰고 search(include_superseded=True)로
    전 행을 끌어오지 않는다 — 비용이 관계 참여 행 수에 비례해야 한다."""
    search_kwargs = []

    def spy_search(pid, **kwargs):
        search_kwargs.append(kwargs)
        return []

    monkeypatch.setattr(qa_engine.mysql_search, "search", spy_search)
    graph_calls = []
    monkeypatch.setattr(
        qa_engine.mysql_search, "fetch_supersede_graph",
        lambda pid, **kwargs: graph_calls.append(pid) or [],
    )
    with patch("backend.retriever.qa_engine.get_collection",
               return_value=_empty_chunk_collection()):
        qa_engine._build_context(1, "왜 바뀌었어?", history_mode=True,
                                 history_scope="global", history_topic_tokens=[],
                                 query_variants=["왜 바뀌었어?"])

    assert graph_calls == [1]
    assert all(not kw.get("include_superseded") for kw in search_kwargs)


# ── recency RRF ───────────────────────────────────────────────────────────────

def _chunk_collection(chunks):
    """chunks: (text, date, chunk_id) 목록으로 Chroma get 응답을 만든다."""
    collection = MagicMock()
    collection.get.return_value = {
        "documents": [text for text, _, _ in chunks],
        "metadatas": [{"source": "doc.md", "date": chunk_date, "item_type": "document"}
                      for _, chunk_date, _ in chunks],
        "ids": [chunk_id for _, _, chunk_id in chunks],
    }
    collection.query.side_effect = RuntimeError("vector unavailable in test")
    return collection


def _fake_vectorstore(order_by_query):
    """query → page_content 목록 매핑으로 dense 검색을 흉내 낸다."""
    store = MagicMock()

    def _search(query, k, filter=None):
        return [
            (types.SimpleNamespace(page_content=text, metadata={"item_type": "document"}), 0.1)
            for text in order_by_query.get(query, [])
        ]

    store.similarity_search_with_score.side_effect = _search
    return store


def _build_chunks(question, queries, chunks, dense_map, monkeypatch):
    # RRF 자체를 검사하므로 운영 Tool 스키마의 최대 4개 정규화와 분리한다.
    monkeypatch.setattr(
        qa_engine,
        "_normalize_multi_queries",
        lambda _question, _variants: list(queries),
    )
    monkeypatch.setattr(qa_engine.mysql_search, "search", lambda pid, **kw: [])
    monkeypatch.setattr(
        qa_engine.mysql_search,
        "fetch_supersede_graph",
        lambda pid, **kwargs: [],
    )
    monkeypatch.setattr(qa_engine, "_get_vectorstore", lambda: _fake_vectorstore(dense_map))
    with patch("backend.retriever.qa_engine.get_collection",
               return_value=_chunk_collection(chunks)):
        return qa_engine._build_context(
            1,
            question,
            query_variants=list(queries),
        )


_CHUNKS = [
    ("알파 내용 회의록", "2026-01-10", "doc1_chunk0"),
    ("베타 내용 회의록", "2026-03-10", "doc1_chunk1"),
    ("감마 내용 회의록", "2026-02-10", "doc1_chunk2"),
]


def test_axis_weights_invariant_to_multi_query_count(monkeypatch):
    """축별 정규화: 동일 dense 결과를 내는 쿼리가 1개든 4개든 융합 점수·순서가 같다."""
    q = "회의록"
    dense = [c[0] for c in _CHUNKS]
    monkeypatch.setattr(qa_engine, "_bm25_scores", lambda query, texts: [0.0] * len(texts))

    _, _, debug1 = _build_chunks(q, [q], _CHUNKS, {q: dense}, monkeypatch)
    queries4 = [q, f"{q} 2", f"{q} 3", f"{q} 4"]
    _, _, debug4 = _build_chunks(q, queries4, _CHUNKS,
                                 {query: dense for query in queries4}, monkeypatch)

    kept1 = [(c["text"], c["rrf"]) for c in debug1["chroma_chunks"]]
    kept4 = [(c["text"], c["rrf"]) for c in debug4["chroma_chunks"]]
    assert kept1 == kept4


def test_bm25_zero_score_gate(monkeypatch):
    """질문과 전혀 안 겹치는 문서는 BM25 순위에 못 들어온다(0점 게이트) —
    dense 축만으로 후보가 유지되고 bm25_rank는 전부 None."""
    q = "회의록"
    monkeypatch.setattr(qa_engine, "_bm25_scores", lambda query, texts: [0.0] * len(texts))
    _, _, debug = _build_chunks(q, [q], _CHUNKS, {q: [c[0] for c in _CHUNKS]}, monkeypatch)

    chunks = debug["chroma_chunks"]
    assert chunks  # dense 후보는 살아 있음
    assert all(c["bm25_rank"] is None for c in chunks)


def test_recency_axis_ranks_by_date_and_excludes_malformed(monkeypatch):
    """recency 축: 유효 날짜 내림차순 dense-rank(1-based), 무효 날짜는 recency 제외
    (다른 축 점수는 유지)."""
    q = "회의록"
    monkeypatch.setattr(qa_engine, "_bm25_scores", lambda query, texts: [0.0] * len(texts))
    chunks = [
        ("알파 내용 회의록", "2026-01-10", "doc1_chunk0"),
        ("베타 내용 회의록", "2026-03-10", "doc1_chunk1"),
        ("감마 내용 회의록", "날짜아님", "doc1_chunk2"),
    ]
    _, _, debug = _build_chunks(q, [q], chunks, {q: [c[0] for c in chunks]}, monkeypatch)

    by_text = {c["text"]: c for c in debug["chroma_chunks"]}
    assert by_text["베타 내용 회의록"]["recency_rank"] == 1   # 최신
    assert by_text["알파 내용 회의록"]["recency_rank"] == 2
    assert by_text["감마 내용 회의록"]["recency_rank"] is None  # 무효 날짜
    assert by_text["감마 내용 회의록"]["dense_rank"] is not None


def test_recency_candidates_limited_to_gated_union(monkeypatch):
    """recency 후보 제한: dense·BM25 어느 축에도 없는 문서는 최신 날짜여도
    recency 축만으로 컨텍스트에 진입할 수 없다."""
    q = "회의록"
    monkeypatch.setattr(qa_engine, "_bm25_scores", lambda query, texts: [0.0] * len(texts))
    chunks = [
        ("알파 내용 회의록", "2026-01-10", "doc1_chunk0"),
        ("베타 내용 회의록", "2026-03-10", "doc1_chunk1"),
        ("최신 미후보 회의록", "2026-12-31", "doc1_chunk2"),  # 어떤 축에도 없음
    ]
    dense_map = {q: ["알파 내용 회의록", "베타 내용 회의록"]}
    _, _, debug = _build_chunks(q, [q], chunks, dense_map, monkeypatch)

    texts = [c["text"] for c in debug["chroma_chunks"]]
    assert "최신 미후보 회의록" not in texts
    assert set(texts) == {"알파 내용 회의록", "베타 내용 회의록"}


def test_tie_break_by_chroma_id_input_order_invariant(monkeypatch):
    """정확 동률(서로 다른 쿼리의 dense 1위)은 Chroma ID로 결정 — 코퍼스 순서 반전 불변."""
    q1, q2 = "질의 하나", "질의 둘"
    chunks = [
        ("알파 내용 회의록", "", "doc1_chunk0"),
        ("베타 내용 회의록", "", "doc1_chunk1"),
    ]
    dense_map = {q1: ["베타 내용 회의록"], q2: ["알파 내용 회의록"]}

    _, _, debug_fwd = _build_chunks("회의록", [q1, q2], chunks, dense_map, monkeypatch)
    _, _, debug_rev = _build_chunks(
        "회의록", [q1, q2], list(reversed(chunks)), dense_map, monkeypatch
    )

    order_fwd = [c["text"] for c in debug_fwd["chroma_chunks"]]
    order_rev = [c["text"] for c in debug_rev["chroma_chunks"]]
    assert order_fwd == order_rev == ["알파 내용 회의록", "베타 내용 회의록"]  # ID 오름차순


def test_tie_candidates_exceeding_top_n_input_order_invariant(monkeypatch):
    """동일 점수 후보가 CHROMA_TOP_N(5)을 초과(6개)해도 선택 ID 목록·순서가
    입력 반전에 불변이다 — Chroma ID 오름차순으로 상위 5개."""
    labels = ["알파", "베타", "감마", "델타", "엡실론", "제타"]
    chunks = [(f"{label} 내용 회의록", "", f"doc1_chunk{i}") for i, label in enumerate(labels)]
    # 쿼리 6개가 각자 서로 다른 청크 1개를 dense 1위로 반환 → 전원 정확 동률
    queries = [f"질의 {i}" for i in range(6)]
    dense_map = {q: [chunks[i][0]] for i, q in enumerate(queries)}

    _, _, debug_fwd = _build_chunks("회의록", queries, chunks, dense_map, monkeypatch)
    _, _, debug_rev = _build_chunks(
        "회의록", queries, list(reversed(chunks)), dense_map, monkeypatch
    )

    order_fwd = [c["text"] for c in debug_fwd["chroma_chunks"]]
    order_rev = [c["text"] for c in debug_rev["chroma_chunks"]]
    expected = [f"{label} 내용 회의록" for label in labels[:5]]  # chunk0~4 (ID 오름차순)
    assert order_fwd == order_rev == expected


def test_chunk_tie_key_sha256_fallback_fixed_value():
    """폴백 digest는 길이-prefix 인코딩 — 고정 기대값과 경계 모호성 제거를 단언."""
    expected = hashlib.sha256("4:s.md|4:text".encode("utf-8")).hexdigest()
    assert qa_engine._chunk_tie_key("", "s.md", "text") == expected
    assert (qa_engine._chunk_tie_key("", "a|b", "c")
            != qa_engine._chunk_tie_key("", "a", "b|c"))
    assert qa_engine._chunk_tie_key("doc1_chunk0", "s.md", "text") == "doc1_chunk0"


def test_duplicate_chunks_deduped_before_ranking(monkeypatch):
    """동일 source·text 완전 중복(ID 없는 fixture)은 사전 제거 — 입력 순서 반전 불변."""
    q = "회의록"
    chunks = [
        ("알파 내용 회의록", "2026-01-10", ""),
        ("알파 내용 회의록", "2026-01-10", ""),   # 완전 중복
        ("베타 내용 회의록", "2026-03-10", ""),
    ]
    dense_map = {q: ["알파 내용 회의록", "베타 내용 회의록"]}

    ctx_fwd, _, debug_fwd = _build_chunks(q, [q], chunks, dense_map, monkeypatch)
    ctx_rev, _, debug_rev = _build_chunks(q, [q], list(reversed(chunks)), dense_map, monkeypatch)

    texts_fwd = [c["text"] for c in debug_fwd["chroma_chunks"]]
    assert texts_fwd.count("알파 내용 회의록") == 1
    assert sorted(texts_fwd) == sorted(c["text"] for c in debug_rev["chroma_chunks"])


# ── 예산 env 경계 ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("soft_env,hard_env,expected", [
    (None, None, (12, 36)),
    ("5", None, (5, 15)),
    ("0", None, (12, 36)),      # 무효(0) → 기본값
    ("abc", None, (12, 36)),    # 무효(비정수) → 기본값
    ("10", "3", (10, 10)),      # hard < soft → soft로 보정
    ("4", "20", (4, 20)),
])
def test_history_limit_env_boundaries(monkeypatch, soft_env, hard_env, expected):
    for name, value in (("HISTORY_CHAIN_LIMIT", soft_env),
                        ("HISTORY_CHAIN_HARD_LIMIT", hard_env)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    assert qa_engine._history_limits() == expected
