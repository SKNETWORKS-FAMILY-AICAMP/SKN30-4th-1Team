import base64
import io
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from backend.document_content import (
    INVALID_DOCUMENT_CODE,
    DocumentContentError,
    extract_document_text,
)
from backend.main import app


_client = TestClient(app, raise_server_exceptions=False)


def _blank_pdf() -> bytes:
    output = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(output)
    return output.getvalue()


def _pdf_with_sensitive_broken_cmap(sentinel: str) -> bytes:
    """파싱은 성공하지만 pypdf가 invalid CMap token을 warning에 넣는 PDF."""
    output = io.BytesIO()
    writer = PdfWriter()
    page = writer.add_blank_page(width=72, height=72)

    cmap = DecodedStreamObject()
    cmap.set_data(
        (
            "/CIDInit /ProcSet findresource begin\n"
            "12 dict begin\n"
            "begincmap\n"
            "/CMapType 2 def\n"
            "1 begincodespacerange\n<00> <FF>\nendcodespacerange\n"
            "2 beginbfchar\n"
            "<41> <0041>\n"
            f"<42> <{sentinel}>\n"
            "endbfchar\nendcmap\nend\nend\n"
        ).encode()
    )
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
        NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
        NameObject("/ToUnicode"): writer._add_object(cmap),
    })
    resources = DictionaryObject({
        NameObject("/Font"): DictionaryObject({
            NameObject("/F1"): writer._add_object(font),
        }),
    })
    content = DecodedStreamObject()
    content.set_data(b"BT /F1 12 Tf 10 10 Td <41> Tj ET")
    page[NameObject("/Resources")] = resources
    page[NameObject("/Contents")] = writer._add_object(content)
    writer.write(output)
    return output.getvalue()


DOCUMENT_CASES = [
    pytest.param("utf8.txt", "한글 문서".encode(), True, "한글 문서", id="utf8-korean"),
    pytest.param("bom.txt", b"\xef\xbb\xbfhello", True, "hello", id="utf8-bom"),
    pytest.param("crlf.md", b"line1\r\nline2", True, "line1\r\nline2", id="crlf"),
    pytest.param("empty.txt", b"", True, "", id="empty"),
    pytest.param("cp949.txt", "한글 문서".encode("cp949"), True, "한글 문서", id="cp949"),
    pytest.param("invalid.txt", b"\x81", False, None, id="undecodable"),
    pytest.param("nul.txt", b"hello\x00world", False, None, id="nul"),
    pytest.param("control-ok.txt", b"\x01\x02" + b"a" * 98, True, None, id="control-2pct"),
    pytest.param("control-bad.txt", b"\x01\x02\x03" + b"a" * 97, False, None, id="control-over-2pct"),
    pytest.param("normal.pdf", _blank_pdf(), True, "", id="normal-pdf"),
    pytest.param("fake.pdf", b"not-a-pdf", False, None, id="pdf-mismatch"),
    pytest.param("broken.pdf", b"%PDF-not-parseable", False, None, id="pdf-header-only"),
]


@pytest.mark.parametrize(("filename", "data", "valid", "expected"), DOCUMENT_CASES)
def test_shared_document_validator_fixture_matrix(filename, data, valid, expected):
    if not valid:
        with pytest.raises(DocumentContentError) as exc_info:
            extract_document_text(filename, data)
        assert exc_info.value.code == INVALID_DOCUMENT_CODE
        return

    actual = extract_document_text(filename, data)
    if expected is not None:
        assert actual == expected


def _project_conn():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = {"id": 1}
    cursor.fetchall.return_value = []
    cursor.lastrowid = 7
    return conn


@pytest.mark.parametrize(("filename", "data", "valid", "expected"), DOCUMENT_CASES)
def test_upload_applies_shared_fixture_before_db_and_storage(filename, data, valid, expected):
    conn = _project_conn()
    with patch("backend.api.upload.require_project_access"), patch(
        "backend.api.upload.get_connection", return_value=conn
    ) as get_connection, patch(
        "backend.api.upload.save_file", return_value="/tmp/document-fixture"
    ) as save_file, patch("backend.api.upload._process_upload") as process:
        response = _client.post(
            "/api/v1/projects/1/documents",
            files={"file": (filename, data, "application/octet-stream")},
        )

    if not valid:
        assert response.status_code == 415
        assert response.json()["detail"]["code"] == INVALID_DOCUMENT_CODE
        get_connection.assert_not_called()
        save_file.assert_not_called()
        process.assert_not_called()
    elif expected == "":
        # upload의 기존 empty semantics는 400이며 DB/storage보다 먼저 끝난다.
        assert response.status_code == 400
        get_connection.assert_not_called()
        save_file.assert_not_called()
        process.assert_not_called()
    else:
        assert response.status_code == 201
        assert get_connection.called
        save_file.assert_called_once()
        process.assert_called_once()


@pytest.mark.parametrize(("filename", "data", "valid", "expected"), DOCUMENT_CASES)
def test_query_applies_same_fixture_before_db_and_llm(filename, data, valid, expected):
    conn = _project_conn()
    payload = {
        "question": "fixture test",
        "attachments": [{
            "filename": filename,
            "content_base64": base64.b64encode(data).decode(),
        }],
    }
    with patch("backend.api.query.require_project_access"), patch(
        "backend.api.query.get_connection", return_value=conn
    ) as get_connection, patch(
        "backend.api.query.run_qa", return_value={"answer": "ok", "debug": {}}
    ) as run_qa:
        response = _client.post("/api/v1/projects/1/query", json=payload)

    if not valid:
        assert response.status_code == 415
        assert response.json()["detail"]["code"] == INVALID_DOCUMENT_CODE
        get_connection.assert_not_called()
        run_qa.assert_not_called()
    else:
        # query는 empty attachment를 명시적 placeholder로 유지하는 기존 계약이다.
        assert response.status_code == 200
        assert get_connection.called
        run_qa.assert_called_once()


def test_sensitive_pdf_parser_warning_is_absent_from_shared_and_endpoint_logs(caplog):
    sentinel = "SENSITIVE-SENTINEL"
    data = _pdf_with_sensitive_broken_cmap(sentinel)
    assert sentinel.encode() in data

    caplog.clear()
    assert extract_document_text("sensitive.pdf", data) == "A"

    upload_conn = _project_conn()
    with patch("backend.api.upload.require_project_access"), patch(
        "backend.api.upload.get_connection", return_value=upload_conn
    ), patch("backend.api.upload.save_file", return_value="/tmp/sensitive.pdf"), patch(
        "backend.api.upload._process_upload"
    ):
        upload_response = _client.post(
            "/api/v1/projects/1/documents",
            files={"file": ("sensitive.pdf", data, "application/pdf")},
        )

    query_conn = _project_conn()
    with patch("backend.api.query.require_project_access"), patch(
        "backend.api.query.get_connection", return_value=query_conn
    ), patch(
        "backend.api.query.run_qa", return_value={"answer": "ok", "debug": {}}
    ):
        query_response = _client.post(
            "/api/v1/projects/1/query",
            json={
                "question": "fixture test",
                "attachments": [{
                    "filename": "sensitive.pdf",
                    "content_base64": base64.b64encode(data).decode(),
                }],
            },
        )

    assert upload_response.status_code == 201
    assert query_response.status_code == 200
    assert sentinel not in upload_response.text
    assert sentinel not in query_response.text
    assert sentinel not in caplog.text
