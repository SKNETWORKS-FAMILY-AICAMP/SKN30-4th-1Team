"""_split_text() chunk size 불변식 및 upload_document 비동기 경로 테스트."""
import pytest
from unittest.mock import patch, MagicMock, call, ANY

from fastapi.testclient import TestClient

from backend.main import app
from backend.pipeline.converters import Block, ConvertedDocument

_client = TestClient(app, raise_server_exceptions=False)

_URL = "/api/v1/projects/1/documents"
_FILE = ("test.md", b"test content here", "text/plain")
_DATA = {"doc_type": "meeting"}


# ─── _split_text() chunk size 불변식 ─────────────────────────────────────────

def test_split_text_normal():
    from backend.pipeline.ingestor import _split_text, CHUNK_SIZE
    chunks = _split_text("hello world. " * 100)
    assert chunks
    assert all(len(c) <= CHUNK_SIZE for c in chunks)


def test_split_text_oversized_sentence():
    """단일 문장이 CHUNK_SIZE 초과해도 각 청크는 CHUNK_SIZE 이내."""
    from backend.pipeline.ingestor import _split_text, CHUNK_SIZE
    chunks = _split_text("x" * 800)
    assert chunks
    assert all(len(c) <= CHUNK_SIZE for c in chunks)


def test_split_text_codex_repro():
    """Codex Entry 033 재현: overlap 적용 후 CHUNK_SIZE 초과 없음 (이전: [501, 651])."""
    from backend.pipeline.ingestor import _split_text, CHUNK_SIZE
    chunks = _split_text("a" * 500 + ". " + "b" * 500)
    assert all(len(c) <= CHUNK_SIZE for c in chunks)


def test_split_text_short_returns_as_is():
    from backend.pipeline.ingestor import _split_text
    assert _split_text("짧은 텍스트") == ["짧은 텍스트"]


def test_split_text_whitespace_returns_empty():
    from backend.pipeline.ingestor import _split_text
    assert _split_text("   ") == []


# ─── extractor._split_chunks() ──────────────────────────────────────────────

def test_extractor_split_chunks_short_returns_single():
    from backend.pipeline.extractor import _split_chunks
    assert _split_chunks("짧은 텍스트", chunk_size=100) == ["짧은 텍스트"]


def test_extractor_split_chunks_uses_paragraph_boundaries():
    from backend.pipeline.extractor import _split_chunks
    text = "a" * 8 + "\n\n" + "b" * 8 + "\n\n" + "c" * 8
    chunks = _split_chunks(text, chunk_size=17)
    assert chunks == ["a" * 8 + "\n\n", "b" * 8 + "\n\n", "c" * 8]
    assert "".join(chunks) == text


def test_extractor_split_chunks_long_single_paragraph_falls_back_to_overlap():
    from backend.pipeline.extractor import _split_chunks
    text = "x" * 650
    chunks = _split_chunks(text, chunk_size=300)
    assert len(chunks) > 1
    assert all(len(chunk) <= 300 for chunk in chunks)
    assert chunks[1] == text[100:400]


def test_extractor_split_chunks_no_content_loss_for_paragraph_chunks():
    from backend.pipeline.extractor import _split_chunks
    text = "첫 문단입니다.\n\n둘째 문단입니다.\n\n셋째 문단입니다."
    assert "".join(_split_chunks(text, chunk_size=20)) == text


def test_extractor_split_chunks_chunk_size_parameter():
    from backend.pipeline.extractor import _split_chunks
    text = "a" * 100
    assert len(_split_chunks(text)) == 1
    assert len(_split_chunks(text, chunk_size=30)) > 1


def test_extract_reports_progress_for_each_chunk(monkeypatch):
    from backend.llm.base import LLMResponse
    from backend.pipeline.extractor import extract

    class Client:
        def chat(self, **kwargs):
            return LLMResponse(content="", tool_input={"items": []})

    calls = []
    monkeypatch.setattr("backend.pipeline.extractor.get_llm_client", lambda provider=None: Client())
    monkeypatch.setattr("backend.pipeline.extractor._split_chunks", lambda text: ["one", "two"])

    extract("ignored", on_progress=lambda done, total: calls.append((done, total)))

    assert calls == [(0, 2), (1, 2), (2, 2)]


def test_extract_reports_progress_when_chunk_fails(monkeypatch):
    from backend.pipeline.extractor import PartialExtractionError, extract

    calls = []
    monkeypatch.setattr("backend.pipeline.extractor.get_llm_client", lambda provider=None: object())
    monkeypatch.setattr("backend.pipeline.extractor._split_chunks", lambda text: ["one", "two"])
    mock_extract = MagicMock(side_effect=[([], []), ValueError("bad chunk")])
    monkeypatch.setattr("backend.pipeline.extractor._extract_chunk", mock_extract)

    try:
        extract("ignored", on_progress=lambda done, total: calls.append((done, total)))
    except PartialExtractionError:
        pass

    assert calls == [(0, 2), (1, 2), (2, 2)]


def test_dedup_completions_later_report_wins_even_if_less_complete():
    """뒷 청크의 더 정확한 부분완료 보고가, 앞 청크의 부정확한 "전체 완료" 요약을
    덮어써야 한다 — fully_complete를 무조건 우선하면 이 케이스가 거꾸로 됨."""
    from backend.pipeline.extractor import _dedup_completions
    from backend.pipeline.models import CompletionReport

    early_optimistic = CompletionReport(
        action_id=1, evidence="모든 액션 완료", fully_complete=True,
    )
    later_precise = CompletionReport(
        action_id=1, evidence="인원관리는 완료, 알림은 진행중", fully_complete=False,
        done_parts=["인원관리"], remaining_parts=["알림"],
    )
    result = _dedup_completions([early_optimistic, later_precise])
    assert len(result) == 1
    assert result[0] is later_precise


def test_dedup_completions_keeps_different_action_ids():
    from backend.pipeline.extractor import _dedup_completions
    from backend.pipeline.models import CompletionReport

    a = CompletionReport(action_id=1, evidence="a", fully_complete=True)
    b = CompletionReport(action_id=2, evidence="b", fully_complete=True)
    result = _dedup_completions([a, b])
    assert {c.action_id for c in result} == {1, 2}


def test_full_completion_is_stored_as_complete_action_doc_kind():
    """F-011: 문서 기반 전체 완료는 PR 기반과 다른 kind로 저장한다.

    evidence에 title/number/url이 없어 kind='complete_action'으로 저장하면 구 데스크톱이
    evidence.title.trim()에서 죽는다(해당 렌더 트리에 ErrorBoundary 없음). 부분 완료는
    기존대로 split_action."""
    from backend.pipeline.ingestor import ingest
    from backend.pipeline.models import CompletionReport

    cursor = MagicMock()
    cursor.fetchone.return_value = {"content": "인원 관리 로직 구현"}
    cursor.fetchall.return_value = []
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    conn.cursor.return_value.__exit__.return_value = False
    reports = [
        CompletionReport(action_id=1, evidence="완료 보고", fully_complete=True),
        CompletionReport(
            action_id=2, evidence="일부 완료", fully_complete=False,
            done_parts=["인원관리"], remaining_parts=["알림"],
        ),
    ]
    with patch("backend.pipeline.ingestor.get_connection", return_value=conn), \
         patch("backend.pipeline.ingestor.upsert_memory_vectors"):
        ingest(
            project_id=1, doc_id=5, items=[], raw_text="", source="2026-04-13.md",
            date="2026-04-13", doc_type="meeting", completions=reports,
        )

    kinds = [
        c.args[1][2] for c in cursor.execute.call_args_list
        if "INSERT INTO memory_suggestions" in c.args[0]
    ]
    assert kinds == ["complete_action_doc", "split_action"]


def _completion_conn(row=None):
    """ingest() completions 블록용 mock. row=None이면 대상이 열린 action이 아닌 상황."""
    cursor = MagicMock()
    cursor.fetchone.return_value = row
    cursor.fetchall.return_value = []
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    conn.cursor.return_value.__exit__.return_value = False
    return conn, cursor


def _suggestion_inserts(cursor):
    return [
        c for c in cursor.execute.call_args_list
        if "INSERT INTO memory_suggestions" in c.args[0]
    ]


def test_completion_with_action_id_outside_provided_list_is_dropped():
    """F-003: LLM이 제공 목록에 없는 action_id를 반환하면 제안을 만들지 않는다.

    프롬프트의 'never invent one'은 지시이지 검증이 아니다. 환각 id뿐 아니라 F-008
    예산 절단으로 LLM에게 보여주지 않은 id도 여기서 걸린다."""
    from backend.pipeline.ingestor import ingest
    from backend.pipeline.models import CompletionReport

    conn, cursor = _completion_conn({"content": "인원 관리 로직 구현"})
    reports = [
        CompletionReport(action_id=1, evidence="완료", fully_complete=True),
        CompletionReport(action_id=999, evidence="환각", fully_complete=True),
    ]
    with patch("backend.pipeline.ingestor.get_connection", return_value=conn), \
         patch("backend.pipeline.ingestor.upsert_memory_vectors"):
        ingest(
            project_id=1, doc_id=5, items=[], raw_text="", source="doc.md",
            date="2026-04-13", doc_type="meeting", completions=reports,
            open_actions=[{"id": 1, "content": "인원 관리 로직 구현"}],
        )

    inserted_ids = [c.args[1][1] for c in _suggestion_inserts(cursor)]
    assert inserted_ids == [1]


def test_split_suggestion_is_skipped_when_action_content_was_truncated():
    """프롬프트 예산으로 잘린 action은 split 제안을 만들지 않는다.

    cap_open_actions가 content를 _OPEN_ACTIONS_ITEM_CHARS로 자르므로 LLM은 뒷부분을
    본 적이 없는데, 승인 시 remaining_part가 전체 content를 덮어써 못 본 부분이
    영구 소실된다. original_content stale 검사는 전체끼리 비교라 이 경로를 못 막는다.
    content를 건드리지 않는 전체 완료(complete_action_doc)는 계속 허용한다.
    """
    from backend.pipeline.ingestor import ingest
    from backend.pipeline.models import CompletionReport
    from backend.pipeline.extractor import _OPEN_ACTIONS_ITEM_CHARS

    long_content = "가" * (_OPEN_ACTIONS_ITEM_CHARS + 1)
    conn, cursor = _completion_conn({"content": long_content})
    reports = [
        CompletionReport(
            action_id=1, evidence="일부 완료", fully_complete=False,
            done_parts=["앞부분"], remaining_parts=["뒷부분"],
        ),
        CompletionReport(action_id=1, evidence="전부 완료", fully_complete=True),
    ]
    with patch("backend.pipeline.ingestor.get_connection", return_value=conn), \
         patch("backend.pipeline.ingestor.upsert_memory_vectors"):
        ingest(
            project_id=1, doc_id=5, items=[], raw_text="", source="doc.md",
            date="2026-04-13", doc_type="meeting", completions=reports,
            open_actions=[{"id": 1, "content": long_content}],
        )

    kinds = [c.args[1][2] for c in _suggestion_inserts(cursor)]
    assert "split_action" not in kinds
    assert kinds == ["complete_action_doc"]


def test_split_suggestion_is_kept_when_action_content_fits_budget():
    """예산 안에 들어오는 action은 LLM이 전체를 봤으므로 split 제안을 그대로 만든다.
    위 가드가 split 자체를 죽이지 않았음을 고정한다."""
    from backend.pipeline.ingestor import ingest
    from backend.pipeline.models import CompletionReport
    from backend.pipeline.extractor import _OPEN_ACTIONS_ITEM_CHARS

    short_content = "가" * _OPEN_ACTIONS_ITEM_CHARS  # 경계값 — 절단되지 않는 최대 길이
    conn, cursor = _completion_conn({"content": short_content})
    reports = [
        CompletionReport(
            action_id=1, evidence="일부 완료", fully_complete=False,
            done_parts=["앞부분"], remaining_parts=["뒷부분"],
        ),
    ]
    with patch("backend.pipeline.ingestor.get_connection", return_value=conn), \
         patch("backend.pipeline.ingestor.upsert_memory_vectors"):
        ingest(
            project_id=1, doc_id=5, items=[], raw_text="", source="doc.md",
            date="2026-04-13", doc_type="meeting", completions=reports,
            open_actions=[{"id": 1, "content": short_content}],
        )

    assert [c.args[1][2] for c in _suggestion_inserts(cursor)] == ["split_action"]


def test_completion_suggestion_failure_does_not_destroy_indexed_document():
    """제안 생성 실패가 이미 색인된 문서를 파괴하면 안 된다.

    completions 블록은 status='indexed' 커밋 뒤에 실행되는 부차 단계다. 여기서 예외가
    새면 _process_upload_locked의 except가 fail_document를 불러 memory 행 DELETE + 파일·
    벡터 삭제까지 간다 — 제안 하나 실패의 대가로 적재 결과 전체가 사라진다. 바로 위
    supersede 블록과 동일하게 best-effort로 격리돼 있어야 한다."""
    from backend.api import upload
    from backend.pipeline.models import CompletionReport

    cursor = MagicMock()
    # 리스 fence 검사와 completions SELECT를 한 dict으로 동시에 만족시킨다
    cursor.fetchone.return_value = {
        "status": "processing", "processing_token": "tok",
        "content": "인원 관리 및 알림 로직 구현",
    }
    cursor.fetchall.return_value = []
    cursor.rowcount = 1  # status='indexed' UPDATE의 fence 확인 통과
    ingest_conn = MagicMock()
    ingest_conn.cursor.return_value.__enter__.return_value = cursor
    ingest_conn.cursor.return_value.__exit__.return_value = False

    calls = {"n": 0}

    def fake_get_connection():
        calls["n"] += 1
        if calls["n"] == 1:
            return ingest_conn          # ingest 본체 — 성공
        raise RuntimeError("DB 순단")   # completions 블록 — 실패

    reports = [CompletionReport(
        action_id=1, evidence="일부 완료", fully_complete=False,
        done_parts=["인원관리"], remaining_parts=["알림"],
    )]

    with patch("backend.pipeline.ingestor.get_connection", side_effect=fake_get_connection), \
         patch("backend.pipeline.ingestor.upsert_memory_vectors"), \
         patch("backend.pipeline.ingestor.get_collection"), \
         patch("backend.api.upload.extract", return_value=([], reports)), \
         patch("backend.api.upload.cap_open_actions",
               return_value=[{"id": 1, "content": "인원 관리 및 알림 로직 구현"}]), \
         patch("backend.api.upload._fetch_open_actions", return_value=[]), \
         patch("backend.api.upload.processing_owned", return_value=True), \
         patch("backend.api.upload.update_project_memory"), \
         patch("backend.api.upload.fail_document") as mock_fail:
        upload._process_upload_locked(
            project_id=1, doc_id=5, old_doc_ids=[],
            document=ConvertedDocument(
                source="2026-04-13.md", format="text",
                blocks=[Block(order=0, kind="paragraph", text="본문")],
            ),
            filename="2026-04-13.md", date="2026-04-13", doc_type="meeting",
            file_path="/tmp/x", processing_token="tok",
        )

    # 재현 조건 확인 — completions 블록까지 도달했고 색인이 이미 확정된 상태여야 한다
    assert calls["n"] >= 2
    assert any(
        "status='indexed'" in str(c.args[0]) for c in cursor.execute.call_args_list
    )
    assert not mock_fail.called  # 적재 결과는 그대로 유지된다


def test_split_suggestion_is_skipped_when_parts_overlap():
    """완료·잔여 조각이 겹치면 split 제안을 만들지 않는다.

    겹친 채로 승인되면 그 조각이 open 행과 completed 행으로 동시에 존재하고, 검색이
    둘 다 반환해 LLM이 모순된 근거를 받는다. 어느 쪽이 맞는지 판단할 근거가 없으므로
    절단 가드와 같은 방침으로 제안 자체를 생략한다."""
    from backend.pipeline.ingestor import ingest
    from backend.pipeline.models import CompletionReport

    conn, cursor = _completion_conn({"content": "인원 관리 및 알림 로직 구현"})
    reports = [
        CompletionReport(
            action_id=1, evidence="일부 완료", fully_complete=False,
            done_parts=["알림"], remaining_parts=["알림", "인원관리"],
        ),
    ]
    with patch("backend.pipeline.ingestor.get_connection", return_value=conn), \
         patch("backend.pipeline.ingestor.upsert_memory_vectors"):
        ingest(
            project_id=1, doc_id=5, items=[], raw_text="", source="doc.md",
            date="2026-04-13", doc_type="meeting", completions=reports,
            open_actions=[{"id": 1, "content": "인원 관리 및 알림 로직 구현"}],
        )

    assert _suggestion_inserts(cursor) == []


def test_suggestion_dedup_key_includes_source_document():
    """중복 방지 키에 근거 문서(doc_id)가 들어간다.

    빠져 있으면 (memory_id, kind)만으로 걸러져, 같은 action에 대해 다른 문서가 보고한
    진행 상황이 앞 제안이 pending인 동안 0행 INSERT로 조용히 사라진다(예외도 로그도
    없음). 문서는 이미 indexed라 재처리되지 않으므로 그 판정은 영구 소실이다.
    PR 경로($.number)·supersede 경로($.superseding_memory_id)와 같은 규칙."""
    from backend.pipeline.ingestor import ingest
    from backend.pipeline.models import CompletionReport

    conn, cursor = _completion_conn({"content": "인원 관리 및 알림 로직 구현"})
    reports = [
        CompletionReport(
            action_id=1, evidence="일부 완료", fully_complete=False,
            done_parts=["인원관리"], remaining_parts=["알림"],
        ),
    ]
    with patch("backend.pipeline.ingestor.get_connection", return_value=conn), \
         patch("backend.pipeline.ingestor.upsert_memory_vectors"):
        ingest(
            project_id=1, doc_id=9, items=[], raw_text="", source="2026-04-20.md",
            date="2026-04-20", doc_type="meeting", completions=reports,
            open_actions=[{"id": 1, "content": "인원 관리 및 알림 로직 구현"}],
        )

    insert = _suggestion_inserts(cursor)[0]
    assert "JSON_EXTRACT(evidence, '$.doc_id')" in insert.args[0]
    assert insert.args[1][-1] == 9  # 중복 검사에 이 문서의 doc_id가 실제로 바인딩된다


def test_completion_targeting_non_open_action_is_dropped():
    """F-003: 목록 조회 이후 상태가 바뀌었거나(이미 완료) decision id가 섞여 반환되면
    제안을 만들지 않는다 — SELECT가 category='action' AND completion_status='open'을
    함께 확인하고, 못 찾으면 건너뛴다."""
    from backend.pipeline.ingestor import ingest
    from backend.pipeline.models import CompletionReport

    conn, cursor = _completion_conn(None)  # 열린 action 조건에 안 맞아 조회 결과 없음
    with patch("backend.pipeline.ingestor.get_connection", return_value=conn), \
         patch("backend.pipeline.ingestor.upsert_memory_vectors"):
        ingest(
            project_id=1, doc_id=5, items=[], raw_text="", source="doc.md",
            date="2026-04-13", doc_type="meeting",
            completions=[CompletionReport(action_id=1, evidence="완료", fully_complete=True)],
            open_actions=[{"id": 1, "content": "이미 완료된 action"}],
        )

    assert _suggestion_inserts(cursor) == []
    select_sql = cursor.execute.call_args_list[0].args[0]
    assert "completion_status = 'open'" in select_sql
    assert "category = 'action'" in select_sql


def test_completion_evidence_date_is_normalized():
    """F-004: evidence 날짜도 memory 행과 동일하게 정규화한다. 무효한 날짜가 그대로
    저장되면 승인 시 DATETIME 컬럼에 들어가 strict MySQL에서 500 + 롤백된다.
    정규화 실패는 None — 승인 시 NOW() 폴백 경로를 탄다."""
    import json
    from backend.pipeline.ingestor import ingest
    from backend.pipeline.models import CompletionReport

    for raw_date, expected in (("2026년 4월 13일", "2026-04-13"), ("2026-02-30", None)):
        conn, cursor = _completion_conn({"content": "인원 관리 로직 구현"})
        with patch("backend.pipeline.ingestor.get_connection", return_value=conn), \
             patch("backend.pipeline.ingestor.upsert_memory_vectors"):
            ingest(
                project_id=1, doc_id=5, items=[], raw_text="", source="doc.md",
                date=raw_date, doc_type="meeting",
                completions=[CompletionReport(action_id=1, evidence="완료", fully_complete=True)],
                open_actions=[{"id": 1, "content": "인원 관리 로직 구현"}],
            )
        evidence = json.loads(_suggestion_inserts(cursor)[0].args[1][3])
        assert evidence["date"] == expected


def test_cap_open_actions_bounds_prompt_size():
    """F-008: 열린 action 목록을 프롬프트 예산 안으로 자른다. 이 system은 청크마다
    재사용되므로 상한이 없으면 해당 프로젝트의 업로드가 통째로 extraction 실패한다."""
    from backend.pipeline.extractor import (
        _OPEN_ACTIONS_ITEM_CHARS, _OPEN_ACTIONS_MAX_CHARS, _OPEN_ACTIONS_MAX_ITEMS,
        _open_actions_prompt, cap_open_actions,
    )

    many = [{"id": i, "content": f"액션 {i} " * 40} for i in range(500)]
    capped = cap_open_actions(many)
    assert 0 < len(capped) <= _OPEN_ACTIONS_MAX_ITEMS
    assert all(len(a["content"]) <= _OPEN_ACTIONS_ITEM_CHARS for a in capped)

    # 항목 하나가 초장문이어도 예산을 독식하지 못한다
    huge = cap_open_actions([{"id": 1, "content": "가" * 100_000}])
    assert len(huge[0]["content"]) == _OPEN_ACTIONS_ITEM_CHARS

    # 실제 렌더링 결과도 예산 근처에 머문다(항목당 서식 오버헤드 감안)
    assert len(_open_actions_prompt(capped)) < _OPEN_ACTIONS_MAX_CHARS * 2


def test_process_upload_wires_capped_open_actions_through_to_ingest():
    """E2E: _fetch_open_actions → cap_open_actions → extract → ingest 배선 전체를,
    개별 함수 단위 테스트가 아니라 실제 연결 지점(_process_upload_locked)에서 검증한다.

    F-008 예산 절단 결과가 extract와 ingest 양쪽에 "같은" 목록으로 전달되는지가 핵심 —
    한쪽만 자르고 다른 쪽은 원본을 넘기면 LLM이 본 적 없는 id가 F-003 허용 목록을
    통과하거나(반대로 자름 누락), 자른 목록끼리 불일치가 나도 개별 단위 테스트로는
    안 잡힌다. 전체 완료 + 부분 완료 + 목록 밖 id(환각/절단분) 세 종류를 한 번에 검증한다.
    """
    from backend.api import upload
    from backend.pipeline.models import CompletionReport

    many_actions = [{"id": i, "content": f"액션 {i}"} for i in range(1, 60)]  # 상한(50) 초과
    completions = [
        CompletionReport(action_id=1, evidence="전체 완료", fully_complete=True),
        CompletionReport(
            action_id=2, evidence="일부 완료", fully_complete=False,
            done_parts=["일부"], remaining_parts=["나머지"],
        ),
        CompletionReport(action_id=999, evidence="목록 밖 id", fully_complete=True),
        # 51~59는 원본 open_actions(59개)엔 있지만 상한(50)엔 잘려나간 구간. extract가
        # 실제로 본 목록(50개)엔 없는 id이므로, ingest가 절단 전 원본을 쓰는 배선 버그가
        # 있으면 이 id는 잘못 허용된다 — 999(완전히 밖)만으로는 그 버그를 못 잡는다.
        CompletionReport(action_id=55, evidence="절단 경계 밖", fully_complete=True),
    ]

    cursor = MagicMock()
    cursor.fetchone.return_value = {"content": "원본 내용"}
    cursor.fetchall.return_value = []
    ingest_conn = MagicMock()
    ingest_conn.cursor.return_value.__enter__.return_value = cursor
    ingest_conn.cursor.return_value.__exit__.return_value = False

    with patch.object(upload, "_fetch_open_actions", return_value=many_actions), \
         patch.object(upload, "extract") as mock_extract, \
         patch.object(upload, "update_project_memory"), \
         patch.object(upload, "get_connection", return_value=MagicMock()), \
         patch("backend.pipeline.ingestor.get_connection", return_value=ingest_conn), \
         patch("backend.pipeline.ingestor.upsert_memory_vectors"):
        mock_extract.return_value = ([], completions)

        upload._process_upload_locked(
            project_id=1, doc_id=5, old_doc_ids=[],
            # blocks=[] → ConvertedDocument.text 가 "" → 청크 없음 → Chroma 임베딩 호출
            # 자체가 생략된다(이 테스트의 관심사가 아님). 정상 변환기는 빈 blocks 문서를
            # 만들지 않으므로 이것은 운영 입력을 대표하지 않는 인공 fixture 다.
            document=ConvertedDocument(source="2026-04-13.md", format="text", blocks=[]),
            filename="2026-04-13.md", date="2026-04-13", doc_type="meeting",
            file_path="/tmp/x",
        )

        extract_open_actions = mock_extract.call_args.kwargs["open_actions"]

    assert len(extract_open_actions) == 50  # cap_open_actions 상한 적용됨

    inserted = [
        c.args[1] for c in cursor.execute.call_args_list
        if "INSERT INTO memory_suggestions" in c.args[0]
    ]
    inserted_by_action_id = {row[1]: row[2] for row in inserted}  # action_id → kind
    assert inserted_by_action_id == {1: "complete_action_doc", 2: "split_action"}
    assert 999 not in inserted_by_action_id  # extract에 안 보여준 id는 ingest에서도 거부
    assert 55 not in inserted_by_action_id   # 절단으로 잘려나간 id도 마찬가지


# ─── upload_document 비동기 경로 ──────────────────────────────────────────────

def _make_conn(fetchone=None, fetchall=None, lastrowid=99):
    """get_connection() 단일 호출용 mock."""
    cursor = MagicMock()
    cursor.fetchone.return_value = fetchone
    cursor.fetchall.return_value = fetchall or []
    cursor.lastrowid = lastrowid
    cm = MagicMock()
    cm.__enter__ = lambda s: cursor
    cm.__exit__ = MagicMock(return_value=False)
    conn = MagicMock()
    conn.cursor.return_value = cm
    return conn


def _conn_seq(old_doc_ids=(), new_doc_id=99):
    """get_connection() 호출 순서별 mock 목록.
    1st: project 확인 + old_doc_ids 조회 (endpoint)
    2nd: INSERT document status='processing' (endpoint)
    3rd: _set_doc_status UPDATE (background)
    """
    return [
        _make_conn({"id": 1}, [{"id": i} for i in old_doc_ids]),
        _make_conn(None, [], new_doc_id),
        _make_conn(None, []),
    ]


def _reservation():
    return {
        "reservation_id": "reservation-1",
        "temp_path": "/tmp/upload.tmp",
        "target_path": "/tmp/upload.txt",
    }


def _finalized(old_doc_ids=()):
    return {
        "doc_id": 99,
        "old_doc_ids": list(old_doc_ids),
        "file_path": "/tmp/upload.txt",
        "processing_token": "processing-token",
    }


def test_document_status_includes_progress_fields():
    """status 응답은 진행률 컬럼을 그대로 내려준다."""
    from backend.api.upload import get_document_status

    conn = _make_conn(
        {"id": 99, "status": "processing", "last_error": None, "progress_done": 1, "progress_total": 3},
        [{"category": "action", "cnt": 2}],
    )
    with patch("backend.api.upload.require_project_access"), \
         patch("backend.api.upload.get_connection", return_value=conn):
        result = get_document_status(1, 99)

    assert result["progress_done"] == 1
    assert result["progress_total"] == 3
    assert result["extracted"]["action"] == 2


def test_extract_failure_sets_failed_status():
    """extract 실패 시 durable cleanup으로 전환하고 안전한 code만 저장한다."""
    with patch("backend.api.upload.require_upload_user", return_value=1), \
         patch("backend.api.upload.reserve_document", return_value=_reservation()), \
         patch("backend.api.upload.write_reserved_file"), \
         patch("backend.api.upload.finalize_document", return_value=_finalized((42,))), \
         patch("backend.api.upload.processing_owned", return_value=True), \
         patch("backend.api.upload.extract", side_effect=ValueError("LLM error")), \
         patch("backend.api.upload._fetch_open_actions", return_value=[]), \
         patch("backend.api.upload.fail_document") as fail_document:

        resp = _client.post(_URL, files={"file": _FILE}, data=_DATA)

        assert resp.status_code == 201
        assert resp.json()["status"] == "processing"
        fail_document.assert_called_once_with(99, "UPLOAD_EXTRACT_FAILED")


def test_ingest_failure_sets_failed_status():
    """ingest 실패 시 document accounting을 durable cleanup으로 넘긴다."""
    with patch("backend.api.upload.require_upload_user", return_value=1), \
         patch("backend.api.upload.reserve_document", return_value=_reservation()), \
         patch("backend.api.upload.write_reserved_file"), \
         patch("backend.api.upload.finalize_document", return_value=_finalized((42,))), \
         patch("backend.api.upload.processing_owned", return_value=True), \
         patch("backend.api.upload.extract", return_value=([], [])), \
         patch("backend.api.upload._fetch_open_actions", return_value=[]), \
         patch("backend.api.upload.ingest", side_effect=RuntimeError("DB error")), \
         patch("backend.api.upload.fail_document") as fail_document:

        resp = _client.post(_URL, files={"file": _FILE}, data=_DATA)

        assert resp.status_code == 201
        assert resp.json()["status"] == "processing"
        fail_document.assert_called_once_with(99, "UPLOAD_INGEST_FAILED")


def test_success_cleans_up_all_old_docs():
    """성공 후 old doc_ids 전체 삭제, 요약 갱신은 마지막에 한 번만 수행."""
    with patch("backend.api.upload.require_upload_user", return_value=1), \
         patch("backend.api.upload.reserve_document", return_value=_reservation()), \
         patch("backend.api.upload.write_reserved_file"), \
         patch("backend.api.upload.finalize_document", return_value=_finalized((10, 11))), \
         patch("backend.api.upload.processing_owned", return_value=True), \
         patch("backend.api.upload.extract", return_value=([], [])) as mock_extract, \
         patch("backend.api.upload._fetch_open_actions", return_value=[{"id": 7, "content": "x"}]), \
         patch("backend.api.upload.ingest") as mock_ingest, \
         patch("backend.api.upload._delete_document") as mock_del, \
         patch("backend.api.upload.refresh_project_memory_after_delete") as mock_refresh:

        resp = _client.post(_URL, files={"file": _FILE}, data=_DATA)

        assert resp.status_code == 201
        assert resp.json()["status"] == "processing"
        assert call(10, refresh_project_memory=False) in mock_del.call_args_list
        assert call(11, refresh_project_memory=False) in mock_del.call_args_list
        assert call(99, refresh_project_memory=False) not in mock_del.call_args_list
        mock_refresh.assert_called_once_with(1)
        # open_actions 조회 결과가 실제로 extract()에 전달되고, extract()의 completions
        # 반환값이 실제로 ingest()에 전달되는지 — 배선 자체를 검증(2번 finding 대응).
        assert mock_extract.call_args.kwargs["open_actions"] == [{"id": 7, "content": "x"}]
        assert mock_ingest.call_args.kwargs["completions"] == []


def test_no_old_doc_skips_cleanup():
    """기존 문서 없으면 _delete_document 호출 없음."""
    with patch("backend.api.upload.require_upload_user", return_value=1), \
         patch("backend.api.upload.reserve_document", return_value=_reservation()), \
         patch("backend.api.upload.write_reserved_file"), \
         patch("backend.api.upload.finalize_document", return_value=_finalized()), \
         patch("backend.api.upload.processing_owned", return_value=True), \
         patch("backend.api.upload.extract", return_value=([], [])), \
         patch("backend.api.upload._fetch_open_actions", return_value=[]), \
         patch("backend.api.upload.ingest"), \
         patch("backend.api.upload._delete_document") as mock_del:

        resp = _client.post(_URL, files={"file": _FILE}, data=_DATA)

        assert resp.status_code == 201
        assert resp.json()["status"] == "processing"
        mock_del.assert_not_called()


def test_upload_preserves_folder_relative_filename():
    """폴더 업로드 파일은 basename이 아니라 상대경로로 중복 판정한다."""
    with patch("backend.api.upload.require_upload_user", return_value=1), \
         patch("backend.api.upload.reserve_document", return_value=_reservation()) as reserve, \
         patch("backend.api.upload.write_reserved_file"), \
         patch("backend.api.upload.finalize_document", return_value=_finalized()) as finalize, \
         patch("backend.api.upload._process_upload"):

        resp = _client.post(
            _URL,
            files={"file": ("docs/README.md", b"test content here", "text/markdown")},
            data=_DATA,
        )

        assert resp.status_code == 201
        assert reserve.call_args.kwargs["filename"] == "docs/README.md"
        assert finalize.call_args.args[1] == "docs/README.md"


def _tool_response(tool_input):
    from backend.llm.base import LLMResponse
    return LLMResponse(content="", tool_input=tool_input)


def test_malformed_completion_does_not_discard_chunk_items():
    """완료 판정 1건의 형식 오류가 그 청크의 정상 items까지 버리면 안 된다.

    items와 completions를 한 번에 검증하면 CompletionReport의 ValidationError
    (⊂ ValueError)가 청크 실패로 집계된다. 단일 청크 문서(_CHUNK_SIZE=15000자라
    대부분이 해당)면 extract()가 '모든 청크 실패'로 ValueError를 올리고 호출부가
    fail_document를 불러 업로드 자체가 파괴된다. 부가 기능의 형식 오류가 치를
    대가가 아니다."""
    from backend.pipeline.extractor import extract

    client = MagicMock()
    client.chat.return_value = _tool_response({
        "items": [{"category": "decision", "content": "기술스택은 FastAPI로 간다"}],
        "completions": [
            {"action_id": "숫자가 아님", "evidence": "완료", "fully_complete": True},
        ],
    })
    with patch("backend.pipeline.extractor.get_llm_client", return_value=client):
        items, completions = extract(
            "짧은 문서", default_source="doc.md",
            open_actions=[{"id": 1, "content": "액션"}],
        )

    assert [i.content for i in items] == ["기술스택은 FastAPI로 간다"]  # 적재는 살아남는다
    assert completions == []                                            # 잘못된 판정만 버린다


def test_valid_completions_survive_alongside_a_malformed_one():
    """형식이 맞는 완료 판정은 같은 응답에 잘못된 항목이 있어도 살아남는다 —
    가드가 completions를 통째로 버리지 않는지 고정한다."""
    from backend.pipeline.extractor import extract

    client = MagicMock()
    client.chat.return_value = _tool_response({
        "items": [],
        "completions": [
            {"action_id": 1, "evidence": "인원관리 완료", "fully_complete": True},
            {"evidence": "action_id 누락", "fully_complete": True},
        ],
    })
    with patch("backend.pipeline.extractor.get_llm_client", return_value=client):
        _items, completions = extract(
            "짧은 문서", default_source="doc.md",
            open_actions=[{"id": 1, "content": "액션"}],
        )

    assert [c.action_id for c in completions] == [1]


def test_tool_schema_still_declares_completions():
    """LLM에게 보여주는 tool_schema는 그대로여야 한다 — 분리한 것은 파싱뿐이고,
    스키마가 바뀌면 모델이 완료 판정을 아예 반환하지 않게 된다."""
    from backend.pipeline.models import ExtractionResult

    schema = ExtractionResult.model_json_schema()
    assert "completions" in schema["properties"]
    assert "items" in schema["properties"]


# ─── main 동기화 경계 회귀 (N1~N3) ──────────────────────────────────────────
# origin/main 의 ConvertedDocument·구조 청킹과 이 브랜치의 완료 판정이 upload→ingest
# 경계에서 자동 병합됐다. git 이 서로 다른 줄이라 합쳐준 것뿐이라, 결합이 의미상
# 맞는지는 별도로 고정해야 한다.


def test_upload_passes_document_text_and_same_objects_to_extract_and_ingest():
    """N1: upload→extract→ingest 배선을 값과 '객체 동일성'으로 고정한다.

    _process_upload_locked 는 main 이 넘긴 ConvertedDocument 를 `content = document.text`
    로 풀어 extract 에 주고, 같은 document 를 converted= 로 ingest 에 넘긴다. 그 다리 줄이
    사라지거나 다른 문자열로 바뀌어도 **라인 커버리지는 그대로다**(실행은 되므로).
    값·동일성 단언이 없으면 검출되지 않는 종류라 다섯 축을 한 테스트에 묶는다.
    """
    from backend.api import upload
    from backend.pipeline.models import CompletionReport

    document = ConvertedDocument(
        source="회의록.md", format="text",
        blocks=[
            Block(order=0, kind="paragraph", text="첫 문단"),
            Block(order=1, kind="paragraph", text="둘째 문단"),
        ],
    )
    # 블록이 2개라 document.text 는 "첫 문단\n\n둘째 문단" — 앞 블록만 넘기는 배선 버그도 잡힌다.
    capped = [{"id": 1, "content": "액션 1"}]
    completions = [CompletionReport(action_id=1, evidence="완료", fully_complete=True)]

    with patch.object(upload, "_fetch_open_actions", return_value=[{"id": 1, "content": "액션 1"}]), \
         patch.object(upload, "cap_open_actions", return_value=capped), \
         patch.object(upload, "processing_owned", return_value=True), \
         patch.object(upload, "extract", return_value=([], completions)) as mock_extract, \
         patch.object(upload, "ingest") as mock_ingest:
        upload._process_upload_locked(
            project_id=1, doc_id=5, old_doc_ids=[],
            document=document,
            filename="회의록.md", date="2026-04-13", doc_type="meeting",
            file_path="/tmp/x", processing_token="tok",
        )

    assert mock_extract.call_args.args[0] == document.text            # A1
    assert mock_ingest.call_args.kwargs["raw_text"] == document.text  # A2
    assert mock_ingest.call_args.kwargs["converted"] is document      # A3
    # A4 — 절단된 목록이 양쪽에 "같은 객체"로. 한쪽만 원본을 넘기는 배선 버그 차단.
    assert mock_extract.call_args.kwargs["open_actions"] is capped
    assert mock_ingest.call_args.kwargs["open_actions"] is capped
    # A5 — extract 가 돌려준 completions 가 그대로 ingest 로.
    assert mock_ingest.call_args.kwargs["completions"] is completions


def test_chunk_source_coordinates_reach_chroma_metadata():
    """N2: 구조 청킹의 출처 좌표가 실제 collection.add 까지 도달하는지 '값'으로 확인한다.

    source_format 은 _build_chunks() 가 아니라 ingest() 가 collection.add 직전에 붙이므로
    청커 단위 테스트로는 덮이지 않는다. 그리고 평문 폴백 경로도 같은 키를 갖기 때문에
    (_UNKNOWN_CHUNK_META) **키 존재만 검사하면 구조 경로가 죽어도 통과한다.** 그래서
    -1/"" 이 아닌 실제 좌표값을 대조한다.
    """
    from backend.pipeline import ingestor

    document = ConvertedDocument(
        source="보고서.pdf", format="pdf",
        blocks=[Block(order=7, kind="paragraph", text="본문 조각", page=3)],
    )
    collection = MagicMock()
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = MagicMock()
    conn.cursor.return_value.__exit__.return_value = False

    with patch.object(ingestor, "get_connection", return_value=conn), \
         patch.object(ingestor, "upsert_memory_vectors"), \
         patch.object(ingestor, "get_collection", return_value=collection):
        ingestor.ingest(
            project_id=1, doc_id=5, items=[], raw_text=document.text,
            source="보고서.pdf", date="2026-04-13", doc_type="meeting",
            source_metadata={"source_kind": "document"},
            converted=document,
        )

    meta = collection.add.call_args.kwargs["metadatas"][0]
    assert meta["source_format"] == "pdf"   # ingest 가 converted.format 에서 붙이는 값
    assert meta["page_start"] == 3          # Block.page → chunk_document → to_metadata
    assert meta["block_start"] == 7         # Block.order 에서 온 실제 좌표


@pytest.mark.parametrize("failing_step", ["upsert_memory_vectors", "chunk_add"])
def test_vector_write_failure_rolls_back_and_leaves_document_unindexed(failing_step):
    """N3: 벡터 쓰기 두 지점의 실패가 각각 rollback 되고 indexed 로 넘어가지 않는다.

    upsert_memory_vectors(memory 벡터)와 collection.add(문서 청크)는 실패 시점과 남을 수
    있는 Chroma 기록이 달라 한쪽만 검증하면 다른 쪽 회귀를 놓친다. 기존
    test_ingest_failure_sets_failed_status 는 ingest 전체를 mock 으로 실패시켜 이 내부
    두 지점을 구분하지 못하고, test_ingest_skips_supersede_when_chunk_add_fails 는
    예외 전파와 supersede 미호출만 본다.
    """
    from backend.pipeline import ingestor

    document = ConvertedDocument(
        source="보고서.pdf", format="pdf",
        blocks=[Block(order=0, kind="paragraph", text="본문 조각", page=1)],
    )
    cursor = MagicMock()
    cursor.fetchone.return_value = {"status": "processing", "processing_token": "tok"}
    cursor.fetchall.return_value = []
    cursor.rowcount = 1
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    conn.cursor.return_value.__exit__.return_value = False

    collection = MagicMock()
    boom = RuntimeError("벡터 저장소 장애")
    upsert_patch = {"side_effect": boom} if failing_step == "upsert_memory_vectors" else {}
    if failing_step == "chunk_add":
        collection.add.side_effect = boom

    with patch.object(ingestor, "get_connection", return_value=conn), \
         patch.object(ingestor, "get_collection", return_value=collection), \
         patch.object(ingestor, "upsert_memory_vectors", **upsert_patch):
        with pytest.raises(RuntimeError, match="벡터 저장소 장애"):
            ingestor.ingest(
                project_id=1, doc_id=5, items=[], raw_text=document.text,
                source="보고서.pdf", date="2026-04-13", doc_type="meeting",
                source_metadata={"source_kind": "document"},
                converted=document, processing_token="tok",
            )

    # 예외가 ingest 밖으로 전파됐고(위 raises), 트랜잭션은 되돌려졌다
    assert conn.rollback.called, "실패 시 rollback 이 호출돼야 한다"
    # 문서가 indexed 로 확정되지 않았다 — 이게 없으면 벡터 없는 문서가 색인 완료로 남는다
    indexed_updates = [
        c for c in cursor.execute.call_args_list
        if c.args and "status='indexed'" in str(c.args[0])
    ]
    assert not indexed_updates, "실패 경로에서 indexed UPDATE 가 실행되면 안 된다"
