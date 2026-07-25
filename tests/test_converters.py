"""멀티포맷 변환기(DOCX·텍스트 PDF·평문)와 구조 기반 청킹 회귀 테스트.

실제 파일 바이트를 만들어 검증한다 — 파서를 mock하면 "라이브러리가 실제로
무엇을 돌려주는가"라는 이 계층의 유일한 위험이 검증되지 않는다.
"""
import io

import pytest

from backend.pipeline.converters import (
    ConversionError,
    ErrorCode,
    WarningCode,
    chunk_document,
    convert,
    is_supported,
    supported_suffixes,
)
from backend.pipeline.converters.chunker import DEFAULT_CHUNK_SIZE


# ─── 픽스처 빌더 ────────────────────────────────────────────────────────────

def _make_docx(build) -> bytes:
    """build(document) 콜백으로 DOCX를 만들고 바이트로 돌려준다."""
    import docx

    document = docx.Document()
    build(document)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _make_pdf(pages: list[list[str]]) -> bytes:
    """텍스트 레이어가 있는 최소 PDF를 직접 조립한다(외부 렌더러 의존 없이)."""
    font_obj = 3 + 2 * len(pages)
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(len(pages)))
    objects: list[tuple[int, str]] = [
        (1, "<< /Type /Catalog /Pages 2 0 R >>"),
        (2, f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>"),
    ]
    for index, lines in enumerate(pages):
        page_id, content_id = 3 + 2 * index, 4 + 2 * index
        objects.append((page_id, (
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]"
            f" /Resources << /Font << /F1 {font_obj} 0 R >> >>"
            f" /Contents {content_id} 0 R >>"
        )))
        drawn = "\n".join(f"({line}) Tj T*" for line in lines)
        stream = f"BT /F1 12 Tf 72 720 Td 16 TL\n{drawn}\nET"
        objects.append((content_id, f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream"))
    objects.append((font_obj, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"))

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for number, content in objects:
        offsets[number] = out.tell()
        out.write(f"{number} 0 obj\n{content}\nendobj\n".encode("latin-1"))
    xref_offset = out.tell()
    last = max(offsets)
    out.write(f"xref\n0 {last + 1}\n0000000000 65535 f \n".encode())
    for number in range(1, last + 1):
        out.write(f"{offsets.get(number, 0):010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {last + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode()
    )
    return out.getvalue()


# ─── 레지스트리 ─────────────────────────────────────────────────────────────

def test_required_formats_are_supported():
    """필수 포맷(DOCX·PDF)과 기존 평문 포맷이 모두 열려 있어야 한다."""
    assert {".docx", ".pdf", ".md", ".txt"} <= supported_suffixes()
    assert is_supported("회의록.DOCX")  # 확장자 대소문자 무관


def test_unsupported_format_raises_explicit_error():
    with pytest.raises(ConversionError) as exc:
        convert("보고서.hwp", b"whatever")
    assert exc.value.code == ErrorCode.UNSUPPORTED_FORMAT


# ─── DOCX ───────────────────────────────────────────────────────────────────

def test_docx_preserves_heading_list_and_table_order():
    """본문 순서·제목 레벨·목록·표가 모두 Block으로 보존된다."""
    def build(document):
        document.add_heading("주간 회의", level=1)
        document.add_paragraph("FastAPI로 백엔드를 구성하기로 했다.")
        document.add_heading("액션 아이템", level=2)
        document.add_paragraph("API 명세서 작성", style="List Bullet")
        table = document.add_table(rows=2, cols=2)
        table.cell(0, 0).text = "담당"
        table.cell(0, 1).text = "기한"
        table.cell(1, 0).text = "김동휘"
        table.cell(1, 1).text = "7/25"

    doc = convert("회의록.docx", _make_docx(build))

    assert doc.format == "docx"
    kinds = [b.kind for b in doc.blocks]
    assert kinds == ["heading", "paragraph", "heading", "list_item", "table_row", "table_row"]
    # 문단 번호는 0부터 빈틈없이 매겨진다 — 출처 추적의 기준 좌표다.
    assert [b.order for b in doc.blocks] == list(range(len(doc.blocks)))
    assert doc.blocks[0].level == 1 and doc.blocks[2].level == 2
    # 하위 제목 아래 블록은 상위 제목 경로를 물려받는다.
    assert doc.blocks[3].heading_path == ("주간 회의", "액션 아이템")
    assert "김동휘 | 7/25" in doc.blocks[5].text


def test_docx_table_emits_flatten_warning():
    """표는 열 구조가 유실되므로 조용히 넘기지 않고 경고를 남긴다."""
    def build(document):
        document.add_paragraph("본문")
        table = document.add_table(rows=1, cols=2)
        table.cell(0, 0).text = "A"
        table.cell(0, 1).text = "B"

    doc = convert("표.docx", _make_docx(build))
    assert WarningCode.TABLE_FLATTENED in {w.code for w in doc.warnings}


def test_docx_has_no_page_numbers():
    """DOCX는 페이지가 렌더링 시점에 정해지므로 page를 지어내지 않는다."""
    doc = convert("x.docx", _make_docx(lambda d: d.add_paragraph("내용")))
    assert all(b.page is None for b in doc.blocks)
    assert doc.page_count is None


def test_docx_empty_document_raises():
    """빈 문서는 성공으로 위장하지 않고 명시적 오류를 낸다."""
    with pytest.raises(ConversionError) as exc:
        convert("빈.docx", _make_docx(lambda d: d.add_paragraph("   ")))
    assert exc.value.code == ErrorCode.EMPTY_DOCUMENT


def test_docx_corrupt_file_raises():
    with pytest.raises(ConversionError) as exc:
        convert("깨진.docx", b"not a real docx")
    assert exc.value.code == ErrorCode.CORRUPT_FILE


# ─── PDF ────────────────────────────────────────────────────────────────────

def test_pdf_assigns_page_numbers_to_blocks():
    data = _make_pdf([
        ["Team decided to use FastAPI."],
        ["Deployment gate is on 2026-07-25."],
    ])
    doc = convert("보고서.pdf", data)

    assert doc.format == "pdf"
    assert doc.page_count == 2
    pages = {b.page for b in doc.blocks}
    assert pages == {1, 2}
    assert any("FastAPI" in b.text and b.page == 1 for b in doc.blocks)
    assert any("2026-07-25" in b.text and b.page == 2 for b in doc.blocks)


def test_pdf_drops_repeated_header_and_page_numbers():
    """모든 페이지에 반복되는 머리말과 페이지 번호는 본문에서 제외된다."""
    data = _make_pdf([
        ["PaiM Confidential", f"Body line number {i}.", str(i)]
        for i in range(1, 5)
    ])
    doc = convert("정책.pdf", data)

    text = doc.text
    assert "PaiM Confidential" not in text
    assert "Body line number 1." in text and "Body line number 4." in text
    assert WarningCode.REPEATED_LINE_DROPPED in {w.code for w in doc.warnings}


def test_pdf_without_text_layer_raises_no_text_layer():
    """스캔 PDF는 범위 밖 — 빈 결과 대신 이유가 담긴 오류를 낸다."""
    with pytest.raises(ConversionError) as exc:
        convert("스캔본.pdf", _make_pdf([[], []]))
    assert exc.value.code == ErrorCode.NO_TEXT_LAYER


def test_pdf_corrupt_file_raises():
    with pytest.raises(ConversionError) as exc:
        convert("깨진.pdf", b"%PDF-1.4 garbage")
    assert exc.value.code == ErrorCode.CORRUPT_FILE


# ─── 평문 / Markdown ────────────────────────────────────────────────────────

def test_markdown_classifies_headings_and_lists():
    source = (
        "# 프로젝트 계획\n\n"
        "본문 첫 문단입니다.\n\n"
        "## 세부 항목\n\n"
        "- 첫 번째 항목\n"
        "- 두 번째 항목\n"
    ).encode("utf-8")
    doc = convert("plan.md", source)

    assert doc.format == "text"
    assert [b.kind for b in doc.blocks] == [
        "heading", "paragraph", "heading", "list_item", "list_item",
    ]
    assert doc.blocks[3].heading_path == ("프로젝트 계획", "세부 항목")


def test_text_cp949_falls_back_with_warning():
    """UTF-8이 아닌 국내 문서를 깨진 채 넘기지 않고, 폴백 사실을 알린다."""
    doc = convert("메모.txt", "결정 사항 정리".encode("cp949"))
    assert "결정 사항 정리" in doc.text
    assert WarningCode.DECODE_FALLBACK in {w.code for w in doc.warnings}


def test_text_empty_document_raises():
    with pytest.raises(ConversionError) as exc:
        convert("빈.txt", b"\n\n   \n")
    assert exc.value.code == ErrorCode.EMPTY_DOCUMENT


# ─── 청킹 ───────────────────────────────────────────────────────────────────

def _long_text_doc(paragraphs: int = 40):
    body = "\n\n".join(
        f"{i}번째 문단입니다. " + ("내용을 채우는 문장입니다. " * 4)
        for i in range(paragraphs)
    )
    return convert("long.md", body.encode("utf-8"))


def test_chunks_never_exceed_chunk_size():
    """청크 크기 불변식 — 오버랩을 붙인 뒤에도 초과하지 않는다."""
    chunks = chunk_document(_long_text_doc())
    assert chunks
    assert all(len(c.text) <= DEFAULT_CHUNK_SIZE for c in chunks)


def test_oversized_single_block_is_split_within_limit():
    doc = convert("huge.md", ("가" * 2000).encode("utf-8"))
    chunks = chunk_document(doc)
    assert len(chunks) > 1
    assert all(len(c.text) <= DEFAULT_CHUNK_SIZE for c in chunks)


def test_chunk_indexes_are_contiguous():
    chunks = chunk_document(_long_text_doc())
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_chunk_carries_page_range_from_pdf():
    """PDF 청크는 원본 페이지 범위를 유지한다 — 출처를 페이지까지 되짚기 위함."""
    data = _make_pdf([
        [f"Page one sentence number {i}." for i in range(1, 6)],
        [f"Page two sentence number {i}." for i in range(1, 6)],
    ])
    chunks = chunk_document(convert("p.pdf", data))

    assert chunks
    for chunk in chunks:
        assert chunk.page_start is not None and chunk.page_start >= 1
        assert chunk.page_end >= chunk.page_start
    assert {c.page_start for c in chunks} >= {1}


def test_chunk_metadata_is_chroma_scalar_safe():
    """ChromaDB metadata는 str/int/float/bool만 허용한다."""
    doc = convert("x.docx", _make_docx(lambda d: d.add_paragraph("본문 내용")))
    metadata = chunk_document(doc)[0].to_metadata()

    assert all(isinstance(v, (str, int, float, bool)) for v in metadata.values())
    # 페이지가 없는 포맷은 None이 아니라 -1로 표현된다.
    assert metadata["page_start"] == -1
    assert metadata["block_start"] == 0


def test_chunk_keeps_heading_context():
    source = "# 배포 계획\n\n" + ("배포 절차를 정리한 문단입니다. " * 10)
    chunks = chunk_document(convert("d.md", source.encode("utf-8")))
    assert any("배포 계획" in c.heading for c in chunks)


def test_chunk_text_covers_document_content():
    """청킹 과정에서 본문이 통째로 사라지지 않는다."""
    doc = _long_text_doc(paragraphs=10)
    joined = " ".join(c.text for c in chunk_document(doc))
    for index in range(10):
        assert f"{index}번째 문단입니다." in joined


# ─── ingestor 연결 ──────────────────────────────────────────────────────────

def test_ingest_chunk_metadata_carries_provenance():
    """구조 정보를 넘기면 청크 metadata에 페이지·문단 좌표가 담긴다."""
    from backend.pipeline.ingestor import _build_chunks

    doc = convert("보고서.pdf", _make_pdf([
        [f"Page one sentence number {i}." for i in range(1, 6)],
        [f"Page two sentence number {i}." for i in range(1, 6)],
    ]))
    chunks = _build_chunks(doc.text, doc)

    assert chunks
    for _, metadata in chunks:
        assert metadata["page_start"] >= 1
        assert metadata["block_start"] >= 0


def test_ingest_falls_back_to_plain_split_without_converted_document():
    """리포지토리 동기화처럼 변환을 거치지 않는 경로는 기존 평문 분할로 동작한다."""
    from backend.pipeline.ingestor import _build_chunks

    chunks = _build_chunks("문장 하나. " * 200, None)

    assert chunks
    # metadata 키 집합은 두 경로가 같아야 한다 (ChromaDB where 필터 일관성).
    structured = _build_chunks("", convert("x.md", "# 제목\n\n본문".encode("utf-8")))
    assert set(chunks[0][1]) == set(structured[0][1])
    assert chunks[0][1]["page_start"] == -1


# ─── 업로드 경로 통합 ────────────────────────────────────────────────────────

def test_upload_accepts_docx_and_passes_structure_to_ingest():
    """DOCX 업로드 → 변환 → ingest에 구조가 전달된다 (핵심 완료 조건)."""
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from backend.main import app
    from tests.test_upload_and_chunking import _conn_seq

    data = _make_docx(lambda d: (
        d.add_heading("주간 회의", level=1),
        d.add_paragraph("FastAPI를 사용하기로 결정했다."),
    ))
    client = TestClient(app, raise_server_exceptions=False)

    with patch("backend.api.upload.get_connection", side_effect=_conn_seq()), \
         patch("backend.api.upload.save_file", return_value="data/1/회의록.docx"), \
         patch("backend.api.upload.extract", return_value=[]), \
         patch("backend.api.upload.ingest") as mock_ingest, \
         patch("backend.api.upload.update_project_memory"), \
         patch("backend.api.upload._set_doc_status"):

        response = client.post(
            "/api/v1/projects/1/documents",
            files={"file": ("회의록.docx", data,
                            "application/vnd.openxmlformats-officedocument."
                            "wordprocessingml.document")},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["format"] == "docx"
    assert body["blocks"] == 2
    assert body["warnings"] == []

    converted = mock_ingest.call_args.kwargs["converted"]
    assert converted.format == "docx"
    assert "FastAPI" in converted.text


def test_upload_rejects_unsupported_format_with_reason():
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app, raise_server_exceptions=False)
    with patch("backend.api.upload.require_project_access"):
        response = client.post(
            "/api/v1/projects/1/documents",
            files={"file": ("보고서.hwp", b"data", "application/octet-stream")},
        )

    assert response.status_code == 400
    assert ".docx" in response.json()["detail"]


def test_upload_rejects_scanned_pdf_with_explicit_code():
    """실패 파일은 명시적 오류를 돌려준다 (완료 조건)."""
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app, raise_server_exceptions=False)
    with patch("backend.api.upload.require_project_access"):
        response = client.post(
            "/api/v1/projects/1/documents",
            files={"file": ("스캔본.pdf", _make_pdf([[], []]), "application/pdf")},
        )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == ErrorCode.NO_TEXT_LAYER
