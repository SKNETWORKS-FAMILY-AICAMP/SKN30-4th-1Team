"""graph.py get_chat_model 경로 regression 테스트.

_make_llm() → get_chat_model() 교체 후 stale 함수명 참조로 인한
AttributeError 재발을 방지한다 (Codex Entry 103 blocker 수정 검증).
"""
import types
import pytest


class _FakeLLM:
    """실제 API 호출 없이 고정 텍스트를 반환하는 stub."""
    def invoke(self, prompt):
        return types.SimpleNamespace(content="- 테스트 todo 항목")


@pytest.fixture()
def fake_chat_model(monkeypatch):
    monkeypatch.setattr("backend.graph.get_chat_model", lambda: _FakeLLM())


@pytest.fixture()
def fake_qa_engine(monkeypatch):
    """qa_node가 DB/Chroma 없이 동작하도록 _build_context와 _get_chain을 stub."""
    import backend.retriever.qa_engine as qe

    monkeypatch.setattr(
        qe, "_build_context",
        lambda pid, q, **kwargs: ("컨텍스트", ["src.md"], {"mysql_rows": [1], "chroma_chunks": []}),
    )

    class _FakeChain:
        def invoke(self, inputs):
            return "테스트 답변"

    monkeypatch.setattr(qe, "_get_chain", lambda: _FakeChain())


@pytest.fixture()
def fake_project_memory(monkeypatch):
    monkeypatch.setattr("backend.graph.get_project_memory", lambda pid: "")
    monkeypatch.setattr("backend.graph.upsert_project_memory", lambda pid, s: None)


def test_plan_node_uses_get_chat_model(fake_chat_model):
    """plan_node()가 get_chat_model()을 통해 LLM을 호출해야 한다.
    _make_llm() 참조가 남아있으면 AttributeError로 실패한다."""
    from backend.graph import plan_node
    result = plan_node({"project_id": 1, "answer": "현재 리스크는 API 변경 가능성입니다."})
    assert "plan" in result
    assert isinstance(result["plan"], list)


def test_run_qa_returns_required_keys(fake_chat_model, fake_qa_engine, fake_project_memory):
    """run_qa()가 answer·plan·sources·route·debug를 모두 반환해야 한다."""
    from backend.graph import run_qa
    result = run_qa(project_id=1, question="현재 상태는?")
    for key in ("answer", "plan", "sources", "route", "debug"):
        assert key in result, f"응답에 '{key}' 키가 없음"
    assert result["route"] == "both"


def test_qa_node_does_not_mix_unversioned_summary_into_scoped_evidence(monkeypatch):
    """Semantic Q&A는 캡처한 generation 근거 뒤에 별도 summary를 읽지 않는다."""
    import backend.graph as graph

    captured = {}

    class _CaptureChain:
        def invoke(self, inputs):
            captured.update(inputs)
            return "테스트 답변"

    monkeypatch.setattr(
        graph.qa_engine,
        "_build_context",
        lambda *args, **kwargs: (
            "[구조화 기록]\n새 generation 근거",
            ["new.md"],
            {"mysql_rows": [1], "chroma_chunks": []},
        ),
    )
    monkeypatch.setattr(graph.qa_engine, "_get_chain", lambda: _CaptureChain())
    monkeypatch.setattr(
        graph,
        "get_project_memory",
        lambda project_id: (_ for _ in ()).throw(
            AssertionError("semantic Q&A must not read project_memory")
        ),
    )

    result = graph.qa_node({
        "project_id": 1,
        "question": "최신 결정은?",
        "history": [],
        "history_mode": False,
    })

    assert result["answer"] == "테스트 답변"
    assert captured["context"] == "[구조화 기록]\n새 generation 근거"
    assert "[프로젝트 메모리]" not in captured["context"]


def test_update_project_memory_uses_get_chat_model(fake_chat_model, fake_project_memory):
    """update_project_memory()가 get_chat_model()로 요약을 생성해야 한다."""
    import backend.pipeline.models as m
    from backend.graph import update_project_memory

    items = [m.MemoryItem(category="action", content="배포 준비", source="test.md")]
    summary = update_project_memory(project_id=1, items=items)
    assert isinstance(summary, str)


# ── TASK-004 계층 3: history_mode 전달 · 재검색 불변성 ────────────────────────

@pytest.fixture()
def recording_build_context(monkeypatch):
    """_build_context 호출(question + history 키워드 인자)을 기록하는 stub.
    컨텍스트 없음으로 응답해 verify_answer가 재검색 루프를 돌게 만들 수 있다."""
    import backend.retriever.qa_engine as qe

    calls = []

    def _record(pid, q, **kwargs):
        calls.append({"question": q, **kwargs})
        return "", [], {"mysql_rows": [], "chroma_chunks": []}

    monkeypatch.setattr(qe, "_build_context", _record)

    class _FakeChain:
        def invoke(self, inputs):
            return "테스트 답변"

    monkeypatch.setattr(qe, "_get_chain", lambda: _FakeChain())
    return calls


def test_run_qa_passes_frozen_history_state(fake_chat_model, fake_project_memory, recording_build_context):
    """run_qa()가 이력 predicate·주제 토큰을 진입 시 1회 계산해 _build_context에 넘긴다."""
    from backend.graph import run_qa

    run_qa(project_id=1, question="JWT로 왜 바뀌었어?", history_mode=True)

    first = recording_build_context[0]
    assert first["history_mode"] is True
    assert first["history_scope"] == "topical"
    assert first["history_topic_tokens"] == ["jwt"]


def test_run_qa_history_mode_false_disables_detection(fake_chat_model, fake_project_memory, recording_build_context):
    """라우터가 history_mode=False를 확정하면 자체 감지로 뒤집지 않는다."""
    from backend.graph import run_qa

    run_qa(project_id=1, question="왜 바뀌었어?", history_mode=False)

    assert recording_build_context[0]["history_mode"] is False
    assert recording_build_context[0]["history_scope"] is None


def test_run_qa_self_detects_when_history_mode_omitted(fake_chat_model, fake_project_memory, recording_build_context):
    """history_mode 미전달(None)이면 자체 감지 — 구 호출부 호환."""
    from backend.graph import run_qa

    run_qa(project_id=1, question="배포 주기가 왜 바뀌었어?")

    first = recording_build_context[0]
    assert first["history_mode"] is True
    assert first["history_scope"] == "topical"
    assert {"배포", "주기"} <= set(first["history_topic_tokens"])


def test_rewrite_loop_does_not_flip_history_predicate(fake_chat_model, fake_project_memory, recording_build_context):
    """재검색 불변성: 검증 실패로 rewrite_node가 질문에 '(관련 배경과 세부 내용 포함)'
    suffix를 붙여도, 고정된 history_scope·주제 토큰은 1·2차 시도에서 동일하다.
    (전역형 질문이 suffix의 '배경'·'내용' 때문에 주제형으로 뒤집히는 결함 방지)"""
    from backend.graph import run_qa

    run_qa(project_id=1, question="왜 바뀌었어?", history_mode=True)

    assert len(recording_build_context) == 2  # 초기 + 재검색 1회(MAX_RETRY)
    first, second = recording_build_context
    assert "관련 배경" in second["question"] and "관련 배경" not in first["question"]
    assert first["history_scope"] == second["history_scope"] == "global"
    assert first["history_topic_tokens"] == second["history_topic_tokens"] == []


def test_deictic_question_inherits_previous_topic(fake_chat_model, fake_project_memory, recording_build_context):
    """지시어 질문은 직전 사용자 질문과 결합해 주제를 승계한다."""
    from backend.graph import run_qa

    history = [
        {"role": "user", "content": "배포 주기 어떻게 하기로 했어?"},
        {"role": "assistant", "content": "2주로 결정했습니다."},
    ]
    run_qa(project_id=1, question="그건 왜 바뀌었어?", history=history, history_mode=True)

    first = recording_build_context[0]
    assert first["history_scope"] == "topical"
    assert {"배포", "주기"} <= set(first["history_topic_tokens"])
    # 결합 질문이 검색 질의로도 쓰인다 — 멀티쿼리·dense와 관련도가 같은 주제를 본다
    assert first["question"] == "배포 주기 어떻게 하기로 했어? 그건 왜 바뀌었어?"


def test_deictic_chain_does_not_cascade(fake_chat_model, fake_project_memory, recording_build_context):
    """직전 질문도 지시어면 결합하지 않는다(연쇄 승계 방지) — 전역형으로 남는다."""
    from backend.graph import run_qa

    history = [{"role": "user", "content": "그건 뭐야?"}]
    run_qa(project_id=1, question="그건 왜 바뀌었어?", history=history, history_mode=True)

    first = recording_build_context[0]
    assert first["history_scope"] == "global"
    assert first["history_topic_tokens"] == []
