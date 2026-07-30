from langchain_core.messages import AIMessage, ToolMessage

from backend import agentic_graph
from backend.retriever.question_scope import QuestionScope, resolve_question_scope


class _StructuredModel:
    def __init__(self, result):
        self.result = result
        self.messages = None

    def with_structured_output(self, schema):
        assert schema is QuestionScope
        return self

    def invoke(self, messages):
        self.messages = messages
        return self.result


def test_scope_uses_only_user_turn_payload_and_validates_result():
    model = _StructuredModel({
        "operation": "count",
        "category": "action",
        "owner": "Alpha",
        "completion_status": "open",
        "include_history": False,
    })

    scope = resolve_question_scope(
        "그 사람의 남은 작업 수는?",
        ["Alpha의 작업을 보여줘"],
        model=model,
    )

    assert scope.operation == "count"
    assert scope.category == "action"
    assert scope.owner == "Alpha"
    assert scope.completion_status == "open"
    assert "Alpha의 작업을 보여줘" in model.messages[-1].content


def test_scope_rejects_conflicting_time_filters():
    try:
        QuestionScope(
            operation="count",
            category="action",
            due_within_days=30,
            overdue=True,
        )
    except ValueError as exc:
        assert "overdue conflicts" in str(exc)
    else:
        raise AssertionError("conflicting time filters must fail")


def test_scope_rejects_included_and_excluded_same_owner():
    try:
        QuestionScope(owner="Alpha", excluded_owners=["alpha"])
    except ValueError as exc:
        assert "owner cannot also be excluded" in str(exc)
    else:
        raise AssertionError("opposite owner constraints must fail")


def test_scope_preserves_plural_constraints_and_named_subject():
    scope = QuestionScope(
        operation="list",
        categories=["decision", "risk"],
        owners=["Alpha", "Beta"],
        completion_statuses=[],
        subject="Quartz relay",
    )

    assert scope.categories == ["decision", "risk"]
    assert scope.owners == ["Alpha", "Beta"]
    assert scope.subject == "Quartz relay"


def test_scope_rejects_coercible_or_unknown_shapes():
    for payload in (
        {"due_within_days": "7", "category": "action"},
        {"overdue": 1, "category": "action"},
        {"owner": 7},
        {"owners": "Alpha"},
        {"unexpected": "value"},
    ):
        try:
            QuestionScope.model_validate(payload)
        except ValueError:
            pass
        else:
            raise AssertionError(f"scope must reject {payload!r}")


def test_scope_rejects_singular_and_plural_versions_together():
    try:
        QuestionScope(
            category="action",
            categories=["issue"],
        )
    except ValueError as exc:
        assert "either category or categories" in str(exc)
    else:
        raise AssertionError("ambiguous category shapes must fail")


def test_production_run_resolves_scope_once_and_injects_it(monkeypatch):
    captured = {}

    class _App:
        def invoke(self, state):
            captured["state"] = state
            return {
                "messages": [
                    AIMessage(content="", tool_calls=[{
                        "name": "search_hybrid_vector_rag",
                        "args": {"query": "Nimbus42"},
                        "id": "scope_call",
                        "type": "tool_call",
                    }]),
                    ToolMessage(
                        content="evidence",
                        name="search_hybrid_vector_rag",
                        tool_call_id="scope_call",
                        artifact={
                            "tool": "search_hybrid_vector_rag",
                            "status": "ok",
                            "sources": ["repo#1:notes.md"],
                            "model_contexts": ["evidence"],
                        },
                    ),
                    AIMessage(content="answer"),
                ],
                "tool_rounds": 1,
            }

    scope_model = object()

    def fake_resolve(question, user_history, *, model):
        captured["resolved"] = (question, user_history, model)
        return QuestionScope(
            include_history=True,
            inherit_previous_topic=True,
            history_scope="topical",
            history_topic="Nimbus42",
        )

    monkeypatch.setattr(agentic_graph, "_agentic_app", _App())
    monkeypatch.setattr(
        agentic_graph,
        "get_agentic_qa_model",
        lambda: scope_model,
    )
    monkeypatch.setattr(agentic_graph, "resolve_question_scope", fake_resolve)

    result = agentic_graph.run_agentic_qa(
        1,
        "What preceded it?",
        history=[
            {"role": "user", "content": "Explain Nimbus42."},
            {"role": "assistant", "content": "untrusted answer"},
        ],
    )

    assert captured["resolved"] == (
        "What preceded it?",
        ["Explain Nimbus42."],
        scope_model,
    )
    assert captured["state"]["question_scope"]["include_history"] is True
    assert result["debug"]["scope_llm_calls"] == 1
    assert result["debug"]["llm_calls"] == 3
