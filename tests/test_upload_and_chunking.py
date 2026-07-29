"""_split_text() chunk size 불변식 및 upload_document 비동기 경로 테스트."""
from unittest.mock import patch, MagicMock, call, ANY

import pytest
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
    mock_extract = MagicMock(side_effect=[[], ValueError("bad chunk")])
    monkeypatch.setattr("backend.pipeline.extractor._extract_chunk", mock_extract)

    try:
        extract("ignored", on_progress=lambda done, total: calls.append((done, total)))
    except PartialExtractionError:
        pass

    assert calls == [(0, 2), (1, 2), (2, 2)]


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
    from backend.api.documents import get_document_status

    conn = _make_conn(
        {"id": 99, "status": "processing", "last_error": None, "progress_done": 1, "progress_total": 3},
        [{"category": "action", "cnt": 2}],
    )
    with patch("backend.api.documents.require_project_access"), \
         patch("backend.api.documents.get_connection", return_value=conn):
        result = get_document_status(1, 99)

    assert result["progress_done"] == 1
    assert result["progress_total"] == 3
    assert result["extracted"]["action"] == 2


def test_extract_failure_sets_failed_status():
    """extract 실패 시 durable cleanup으로 전환하고 안전한 code만 저장한다."""
    with patch("backend.api.documents.require_upload_user", return_value=1), \
         patch("backend.api.documents.reserve_document", return_value=_reservation()), \
         patch("backend.api.documents.write_reserved_file"), \
         patch("backend.api.documents.finalize_document", return_value=_finalized((42,))), \
         patch("backend.api.documents.processing_owned", return_value=True), \
         patch("backend.api.documents.extract", side_effect=ValueError("LLM error")), \
         patch("backend.api.documents.fail_document") as fail_document:

        resp = _client.post(_URL, files={"file": _FILE}, data=_DATA)

        assert resp.status_code == 201
        assert resp.json()["status"] == "processing"
        fail_document.assert_called_once_with(99, "UPLOAD_EXTRACT_FAILED")


def test_ingest_failure_sets_failed_status():
    """ingest 실패 시 document accounting을 durable cleanup으로 넘긴다."""
    with patch("backend.api.documents.require_upload_user", return_value=1), \
         patch("backend.api.documents.reserve_document", return_value=_reservation()), \
         patch("backend.api.documents.write_reserved_file"), \
         patch("backend.api.documents.finalize_document", return_value=_finalized((42,))), \
         patch("backend.api.documents.processing_owned", return_value=True), \
         patch("backend.api.documents.extract", return_value=[]), \
         patch("backend.api.documents.ingest", side_effect=RuntimeError("DB error")), \
         patch("backend.api.documents.fail_document") as fail_document:

        resp = _client.post(_URL, files={"file": _FILE}, data=_DATA)

        assert resp.status_code == 201
        assert resp.json()["status"] == "processing"
        fail_document.assert_called_once_with(99, "UPLOAD_INGEST_FAILED")


def test_success_cleans_up_all_old_docs():
    """성공 후 old doc_ids 전체 삭제, 요약 갱신은 마지막에 한 번만 수행."""
    with patch("backend.api.documents.require_upload_user", return_value=1), \
         patch("backend.api.documents.reserve_document", return_value=_reservation()), \
         patch("backend.api.documents.write_reserved_file"), \
         patch("backend.api.documents.finalize_document", return_value=_finalized((10, 11))), \
         patch("backend.api.documents.processing_owned", return_value=True), \
         patch("backend.api.documents.extract", return_value=[]), \
         patch("backend.api.documents.ingest"), \
         patch("backend.api.documents._delete_document") as mock_del, \
         patch("backend.api.documents.refresh_project_memory_after_delete") as mock_refresh:

        resp = _client.post(_URL, files={"file": _FILE}, data=_DATA)

        assert resp.status_code == 201
        assert resp.json()["status"] == "processing"
        assert call(10, refresh_project_memory=False) in mock_del.call_args_list
        assert call(11, refresh_project_memory=False) in mock_del.call_args_list
        assert call(99, refresh_project_memory=False) not in mock_del.call_args_list
        mock_refresh.assert_called_once_with(1)


def test_no_old_doc_skips_cleanup():
    """기존 문서 없으면 _delete_document 호출 없음."""
    with patch("backend.api.documents.require_upload_user", return_value=1), \
         patch("backend.api.documents.reserve_document", return_value=_reservation()), \
         patch("backend.api.documents.write_reserved_file"), \
         patch("backend.api.documents.finalize_document", return_value=_finalized()), \
         patch("backend.api.documents.processing_owned", return_value=True), \
         patch("backend.api.documents.extract", return_value=[]), \
         patch("backend.api.documents.ingest"), \
         patch("backend.api.documents._delete_document") as mock_del:

        resp = _client.post(_URL, files={"file": _FILE}, data=_DATA)

        assert resp.status_code == 201
        assert resp.json()["status"] == "processing"
        mock_del.assert_not_called()


def test_upload_preserves_folder_relative_filename():
    """폴더 업로드 파일은 basename이 아니라 상대경로로 중복 판정한다."""
    with patch("backend.api.documents.require_upload_user", return_value=1), \
         patch("backend.api.documents.reserve_document", return_value=_reservation()) as reserve, \
         patch("backend.api.documents.write_reserved_file"), \
         patch("backend.api.documents.finalize_document", return_value=_finalized()) as finalize, \
         patch("backend.api.documents._process_upload"):

        resp = _client.post(
            _URL,
            files={"file": ("docs/README.md", b"test content here", "text/markdown")},
            data=_DATA,
        )

        assert resp.status_code == 201
        assert reserve.call_args.kwargs["filename"] == "docs/README.md"
        assert finalize.call_args.args[1] == "docs/README.md"


# ─── main 동기화 경계 회귀 (N1~N3) ──────────────────────────────────────────
# origin/main 의 ConvertedDocument·구조 청킹과 이 브랜치의 완료 판정이 upload→ingest
# 경계에서 자동 병합됐다. git 이 서로 다른 줄이라 합쳐준 것뿐이라, 결합이 의미상
# 맞는지는 별도로 고정해야 한다.


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
