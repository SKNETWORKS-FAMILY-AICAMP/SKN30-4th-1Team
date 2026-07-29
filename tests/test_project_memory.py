"""Project-summary cache checks.

Router-branching Q&A graph tests remain in the frozen Legacy baseline suite.
"""

from types import SimpleNamespace


def test_update_project_memory_uses_the_configured_chat_model(monkeypatch):
    from backend import project_memory

    class FakeLLM:
        def invoke(self, prompt):
            assert "[새 항목]" in prompt
            return SimpleNamespace(content="갱신된 프로젝트 요약")

    monkeypatch.setattr(project_memory, "get_project_memory", lambda project_id: "")
    monkeypatch.setattr(
        project_memory, "upsert_project_memory", lambda project_id, summary: None
    )
    monkeypatch.setattr(project_memory, "get_chat_model", lambda: FakeLLM())

    items = [SimpleNamespace(category="action", content="배포 준비")]
    summary = project_memory.update_project_memory(project_id=1, items=items)

    assert summary == "갱신된 프로젝트 요약"
