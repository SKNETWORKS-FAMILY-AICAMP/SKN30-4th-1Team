"""Current ingestion-graph and project-memory checks.

Router-branching Q&A graph tests remain in the frozen Legacy baseline suite.
"""

from types import SimpleNamespace


def test_update_project_memory_uses_the_configured_chat_model(monkeypatch):
    from backend import graph

    class FakeLLM:
        def invoke(self, prompt):
            assert "[새 항목]" in prompt
            return SimpleNamespace(content="갱신된 프로젝트 요약")

    monkeypatch.setattr(graph, "get_project_memory", lambda project_id: "")
    monkeypatch.setattr(graph, "upsert_project_memory", lambda project_id, summary: None)
    monkeypatch.setattr(graph, "get_chat_model", lambda: FakeLLM())

    items = [SimpleNamespace(category="action", content="배포 준비")]
    summary = graph.update_project_memory(project_id=1, items=items)

    assert summary == "갱신된 프로젝트 요약"


def test_graph_module_exposes_ingestion_not_router_qa():
    from backend import graph

    assert callable(graph.build_ingest_graph)
    assert callable(graph.run_ingest)
    assert not hasattr(graph, "run_qa")
