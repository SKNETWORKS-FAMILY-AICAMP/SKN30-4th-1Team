"""API 명세서 ↔ 코드(OpenAPI) manifest 대조 회귀 테스트 (TASK-010).

문서-코드 드리프트 재발 방지:
- `app.openapi()`의 (method, path) 집합과 Markdown 명세서 endpoint 제목 집합,
  HTML 명세서 endpoint 카드 집합이 모두 일치해야 한다(누락/유령 0).
- 추출 경계(P-004): md는 백틱으로 감싼 정식 endpoint 제목만, html은 endpoint
  카드(`.endpoint-header`)만. 구현현황표·폴링 흐름 축약·내비 링크는 제외.
- 정규화: path parameter 이름은 `{}`로 통일, trailing slash 제거. `/api/v1`
  prefix는 추론하지 않는다(문서 표기 그대로).
- 인증모드·갱신일은 구조화 표식으로 비교(R2-P2b·R3-2), 전역 권한은 구조화
  표식 + 옛 문장 부재로 비교(R2-P2c·R3-3).
- callback은 state 필수(R3-1).
"""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.main import app

_DOCS = Path(__file__).resolve().parent.parent / "docs"
_MD = _DOCS / "API_명세서.md"
_HTML = _DOCS / "API_명세서.html"

_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
_client = TestClient(app, raise_server_exceptions=False)


# ── 추출·정규화 헬퍼 ────────────────────────────────────────────────

def _norm(path: str) -> str:
    """path parameter 이름을 통일하고 trailing slash를 제거한다.
    `/api/v1` prefix는 추론하지 않는다(문서 표기 그대로 비교)."""
    path = re.sub(r"\{[^}]+\}", "{}", path.strip())
    if len(path) > 1:
        path = path.rstrip("/")
    return path


def openapi_ops() -> set[tuple[str, str]]:
    spec = app.openapi()
    ops = set()
    for path, methods in spec["paths"].items():
        for method in methods:
            if method.upper() in _METHODS:
                ops.add((method.upper(), _norm(path)))
    return ops


def md_ops(text: str) -> set[tuple[str, str]]:
    """백틱으로 감싼 정식 endpoint 제목(`### `METHOD /path``)만 추출한다.
    구현현황표(`| `GET /x` |`)·폴링 흐름 축약은 `### ` 접두가 없어 제외된다."""
    ops = set()
    pattern = re.compile(r"^### `(" + "|".join(_METHODS) + r") (\S+)`", re.M)
    for method, path in pattern.findall(text):
        ops.add((method, _norm(path)))
    return ops


def html_ops(text: str) -> set[tuple[str, str]]:
    """endpoint 카드(`.endpoint-header`)의 method·path만 추출한다.
    내비 링크(`<a>… :id`)·구현현황표(`<code>`)는 카드가 아니므로 제외된다."""
    ops = set()
    for header in re.findall(r'<div class="endpoint-header">(.*?)</div>', text, re.S):
        m_method = re.search(r'class="method [A-Z]+">([A-Z]+)<', header)
        m_path = re.search(r'class="path"[^>]*>([^<]+)<', header)
        if m_method and m_path:
            ops.add((m_method.group(1), _norm(m_path.group(1))))
    return ops


# ── 핵심 대조 테스트 ────────────────────────────────────────────────

def test_md_manifest_matches_openapi():
    code = openapi_ops()
    doc = md_ops(_MD.read_text(encoding="utf-8"))
    assert doc - code == set(), f"명세서에만 있는 유령 endpoint: {sorted(doc - code)}"
    assert code - doc == set(), f"명세서에서 누락된 endpoint: {sorted(code - doc)}"


def test_html_manifest_matches_openapi():
    code = openapi_ops()
    doc = html_ops(_HTML.read_text(encoding="utf-8"))
    assert doc - code == set(), f"HTML에만 있는 유령 endpoint: {sorted(doc - code)}"
    assert code - doc == set(), f"HTML에서 누락된 endpoint: {sorted(code - doc)}"


def test_html_and_md_endpoint_sets_equal():
    md = md_ops(_MD.read_text(encoding="utf-8"))
    html = html_ops(_HTML.read_text(encoding="utf-8"))
    assert md == html, f"md↔html 불일치: md-html={sorted(md - html)} html-md={sorted(html - md)}"


# ── P-004 / R2-P2a: 추출·정규화 규칙 fixture ───────────────────────

def test_extract_backtick_title():
    """R2-P2a: 백틱으로 감싼 제목을 인식해야 한다(기존 26개 형식)."""
    assert md_ops("### `GET /api/v1/projects`\n본문") == {("GET", "/api/v1/projects")}


def test_ignore_shortened_polling_flow():
    """폴링 흐름 축약 표기(`POST /documents`)를 유령으로 잡지 않는다."""
    text = "폴링 흐름:\n```\nPOST /documents → { status }\n```\n"
    assert md_ops(text) == set()


def test_ignore_impl_status_table_rows():
    """구현현황표 행(`| `GET /x` |`)은 endpoint 제목이 아니다."""
    text = "| `GET /api/v1/projects` | ✅ 완료 |\n"
    assert md_ops(text) == set()


def test_param_name_normalization():
    """`{id}`와 `{project_id}`는 같은 endpoint로 정규화된다."""
    assert _norm("/api/v1/projects/{id}") == _norm("/api/v1/projects/{project_id}")


def test_trailing_slash_normalization():
    assert _norm("/api/v1/projects/") == _norm("/api/v1/projects")
    assert _norm("/") == "/"


def test_github_prefix_not_inferred():
    """GitHub App 경로는 `/api/v1` prefix 없이 그대로 유지된다."""
    assert md_ops("### `GET /github/app/callback`") == {("GET", "/github/app/callback")}
    assert ("GET", "/github/app/callback") in openapi_ops()


def test_html_ignores_nav_and_status_table():
    """HTML 내비 링크·구현현황표는 카드가 아니므로 추출 대상이 아니다."""
    text = (
        '<nav><a href="#x">GET /projects/:id</a></nav>'
        '<table><tr><td><code>GET /api/v1/projects</code></td></tr></table>'
        '<div class="endpoint-header">'
        '<span class="method GET">GET</span>'
        '<span class="path">/api/v1/projects/{project_id}</span>'
        '</div>'
    )
    assert html_ops(text) == {("GET", "/api/v1/projects/{}")}


# ── R2-P2b / R3-2: 인증모드·갱신일 구조화 표식 ─────────────────────

def _find_all(text: str, marker: str) -> list[str]:
    return re.findall(r"<!--\s*" + marker + r":\s*([^>]*?)\s*-->", text)


def test_auth_mode_marker_matches():
    md_vals = _find_all(_MD.read_text(encoding="utf-8"), "auth-mode")
    html_vals = _find_all(_HTML.read_text(encoding="utf-8"), "auth-mode")
    assert md_vals == ["jwt-fail-closed"], md_vals
    assert html_vals == ["jwt-fail-closed"], html_vals


def test_updated_marker_cardinality_and_match():
    """갱신일 표식은 문서당 정확히 1개이며 양 문서 값이 같다(자유서술 무관)."""
    md_vals = _find_all(_MD.read_text(encoding="utf-8"), "updated")
    html_vals = _find_all(_HTML.read_text(encoding="utf-8"), "updated")
    assert len(md_vals) == 1, f"md updated 표식이 {len(md_vals)}개"
    assert len(html_vals) == 1, f"html updated 표식이 {len(html_vals)}개"
    assert md_vals == html_vals, (md_vals, html_vals)


@pytest.mark.parametrize("doc", [_MD, _HTML])
def test_displayed_updated_dates_match_marker(doc):
    """RI-7: 표시되는 '갱신: YYYY-MM-DD' 값이 모두 updated 표식과 일치해야 한다.
    (구현현황 섹션에 옛 날짜가 남는 단일-출처 위반을 잡는다. '경로 확정
    (2026-07-02)' 같은 역사적 주석은 '갱신:' 접두가 없어 대상이 아니다.)"""
    text = doc.read_text(encoding="utf-8")
    marker = _find_all(text, "updated")[0]
    shown = re.findall(r"갱신:\s*(\d{4}-\d{2}-\d{2})", text)
    assert shown, "표시 갱신일이 없음"
    stale = sorted({d for d in shown if d != marker})
    assert not stale, f"표식({marker})과 다른 갱신일 잔존: {stale}"


def test_perms_marker_matches():
    """R3-3: 전역 권한 요약이 구조화 표식으로 양 문서에 연결된다."""
    md_vals = _find_all(_MD.read_text(encoding="utf-8"), "perms")
    html_vals = _find_all(_HTML.read_text(encoding="utf-8"), "perms")
    assert md_vals == ["see role-matrix"], md_vals
    assert html_vals == ["see role-matrix"], html_vals


# RI-8 / RI3-2: 표식만이 아니라 실제 조건부 역할 사실을 **권한 노드 범위 안에서**
# 단언한다. 문서 전체 검색은 개별 endpoint 카드 문구로 통과해 전역 권한 노드
# 퇴행("멤버 관리=owner"로 뭉뚱그리기)을 놓치므로, perms 노드만 잘라 검사한다.
_PERM_FACTS = (
    ("멤버 목록 조회", "viewer"),  # GET 멤버 목록 = viewer
    ("멤버 초대", "owner"),        # POST 멤버 = owner
    ("역할 변경", "owner"),        # PATCH 멤버 역할 = owner
    ("본인 탈퇴", "member"),       # DELETE 멤버(자기): member
    ("타인 제거", "owner"),        # DELETE 멤버(타인): owner
)


def _perms_node(doc: Path) -> str:
    """구조화 권한 노드의 표시 텍스트만 반환한다.
    HTML: `data-perms="role-matrix"` div 내부. MD: `<!-- perms: ... -->` 표식
    다음부터 역할 표(첫 `| ...` 행) 직전까지의 문단."""
    raw = doc.read_text(encoding="utf-8")
    if doc.suffix.lower() in (".html", ".htm"):
        m = re.search(r'data-perms="role-matrix"[^>]*>(.*?)</div>', raw, re.S)
        assert m, "HTML perms 노드를 찾지 못함"
        node = m.group(1)
    else:
        m = re.search(r"<!--\s*perms:.*?-->(.*?)(?:\n\|)", raw, re.S)
        assert m, "MD perms 노드를 찾지 못함"
        node = m.group(1)
    node = re.sub(r"<[^>]+>", " ", node)
    return re.sub(r"\s+", " ", node)


@pytest.mark.parametrize("doc", [_MD, _HTML])
def test_perms_node_asserts_conditional_roles(doc):
    node = _perms_node(doc)
    for subject, role in _PERM_FACTS:
        # 주체와 역할을 같은 절 안에서만 대조한다 — 절 구분자(쉼표·마침표·
        # 가운뎃점·슬래시)를 건너뛰면 옆 절의 역할을 잘못 매칭해(예: "목록
        # 조회=owner, 초대=viewer") 회귀를 놓친다.
        window = re.search(re.escape(subject) + r"[^,.·/]{0,15}" + role, node)
        assert window is not None, f"권한 노드에 사실 누락(같은 절): {subject}=…{role}"


def test_perms_node_guard_catches_swapped_roles():
    """가드 동작 증명: 역할이 뒤섞인 노드는 같은-절 대조에서 실패한다."""
    bad = "멤버 목록 조회=owner, 멤버 초대=viewer, 역할 변경=owner, 본인 탈퇴=member, 타인 제거=owner"
    ok_count = sum(
        1 for subject, role in _PERM_FACTS
        if re.search(re.escape(subject) + r"[^,.·/]{0,15}" + role, bad)
    )
    assert ok_count < len(_PERM_FACTS), "역할이 뒤섞였는데 전부 통과하면 안 됨"


# ── R3-2 / RI-9: 옛 인증 자유서술 부재(의미 기반 가드) ──────────────

# "인증을 미래로 미룬다"는 의미를 잡는다. 단순 근접이 아니라 (a) 인증 주체
# 근처에 (b) 도입/적용/전환/추가 같은 '채택 동작'과 (c) 향후/추후/나중/예정/
# 다음 릴리스 같은 '지연 시점'이 함께 있을 때만 옛(fail-closed 이전) 서술로
# 본다. 채택 동작에 '교체/회전'은 넣지 않는다 — "JWT 키는 정기 교체 예정"처럼
# 현재 인증을 유지한 채 키만 회전하는 문장을 오탐하지 않기 위해서다.
_AUTH_SUBJECT = re.compile(r"(?:인증|토큰|Authorization|Bearer|JWT)")
_AUTH_ADOPT = re.compile(r"(?:도입|적용|전환|추가)")
_AUTH_DEFER = re.compile(r"(?:향후|추후|나중|예정|다음\s*(?:릴리스|버전|배포))")
# 문장 경계로 분리(마침표·물음표·느낌표·구두점 + 공백, 또는 개행). 근접-창이
# 아니라 같은 문장 안에 (주체+채택+지연)이 함께 있을 때만 지연 서술로 본다 —
# 서로 다른 문장에 흩어진 키워드(예: "인증은 이미 적용됐다. 향후 로그 추가
# 예정")의 과탐과, 창(40자)을 벗어난 실제 지연 서술의 미탐을 모두 없앤다.
_SENT_SPLIT = re.compile(r"(?<=[.!?。])\s+|\n+")


def _has_stale_auth(text: str) -> bool:
    """인증 채택을 미래로 미루는 서술이 한 문장 안에 있으면 True."""
    for sent in _SENT_SPLIT.split(text):
        if _AUTH_SUBJECT.search(sent) and _AUTH_ADOPT.search(sent) and _AUTH_DEFER.search(sent):
            return True
    return False


def _visible_text_keeplines(doc: Path) -> str:
    """표시 텍스트를 남기되 **블록 경계(개행)를 보존**한다. 인증 지연 가드가
    문장 단위로 검사하려면 서로 다른 문단·표 셀·리스트 항목이 한 문장으로
    합쳐지면 안 되기 때문이다(마침표 없이 개행으로만 나뉜 항목 포함). HTML
    태그는 개행으로 치환해 요소 경계를 살린다."""
    text = doc.read_text(encoding="utf-8")
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    if doc.suffix.lower() in (".html", ".htm"):
        text = re.sub(r"<[^>]+>", "\n", text)
    return re.sub(r"[ \t]+", " ", text)  # 개행은 보존, 가로 공백만 축약


@pytest.mark.parametrize("doc", [_MD, _HTML])
def test_no_stale_auth_free_text(doc):
    # 개행(블록 경계) 보존본으로 검사 — 서로 다른 항목이 한 문장으로 합쳐져
    # 과탐하지 않도록(RI4-3).
    assert not _has_stale_auth(_visible_text_keeplines(doc)), "옛 인증 지연 서술 발견"


@pytest.mark.parametrize(
    "fixture",
    [
        "인증: 현재 DEV_USER_ID env 기반 fallback. 운영 도입 시 토큰 헤더 추가 예정",
        "운영 도입 시 Authorization 헤더 토큰으로 교체 예정",
        "토큰은 향후 도입 예정입니다.",
        "JWT 인증은 추후 도입한다.",
        "인증은 나중에 도입할 헤더로 교체한다.",
        # RI2-7 미탐 사례: 지연어(향후/추후/…)를 안 써도 '다음 릴리스+적용'이면 지연.
        "Bearer 인증은 다음 릴리스에서 적용한다.",
        # RI3-5 미탐 사례: 주체와 '다음 릴리스에서 적용' 사이가 40자를 넘어도
        # 같은 문장이면 검출돼야 한다.
        "Bearer 인증은 초기 MVP 안정화와 운영 준비가 모두 끝난 뒤 다음 릴리스에서 적용한다.",
    ],
)
def test_stale_auth_guard_detects_variants(fixture):
    """가드가 완전일치가 아닌 동의 변형·다른 지연 표현까지 검출함을 증명."""
    assert _has_stale_auth(fixture) is True


@pytest.mark.parametrize(
    "fixture",
    [
        # 현재 정책 서술(fail-closed jwt) — 채택 동작이 없음.
        "서버는 기본 jwt 모드(fail-closed)로 동작하며 Bearer 토큰이 필요하다.",
        # RI2-7 과탐 사례: 현재 인증 유지 + 키만 회전('교체'는 채택 동작 아님).
        "JWT 키는 정기 교체 예정.",
        # RI3-5 과탐 사례: 인증은 이미 적용, 지연되는 건 별개(감사 로그). 서로
        # 다른 문장이므로 결합 판정에서 통과해야 한다.
        "JWT 인증은 이미 적용되어 있다. 향후 감사 로그를 추가할 예정이다.",
        # RI4-3 과탐 사례: 마침표 없이 개행으로만 나뉜 두 항목 — 블록 경계가
        # 보존되면 한 문장으로 합쳐지지 않아 통과해야 한다.
        "JWT 인증은 이미 적용됨\n감사 로그는 향후 추가 예정",
    ],
)
def test_stale_auth_guard_ignores_non_deferral(fixture):
    """현재 정책·키 회전·별개 지연 등 인증 지연이 아닌 문장은 오검출하지 않는다."""
    assert _has_stale_auth(fixture) is False


# ── R3-3: 옛 전역 권한 문장 부재 ────────────────────────────────────

_STALE_PERMS_PHRASES = (
    "member</code> 이상 필요. DEV 모드에서는 권한 체크 no-op",
    "member 이상 필요. DEV 모드에서는 권한 체크 no-op",
)


def test_no_stale_global_perms_text():
    html = _HTML.read_text(encoding="utf-8")
    for phrase in _STALE_PERMS_PHRASES:
        assert phrase not in html, phrase


def test_stale_perms_guard_detects_old_text():
    """가드 동작 증명: 옛 전역 권한 문장 fixture는 검출된다."""
    fixture = "write 작업은 <code>member</code> 이상 필요. DEV 모드에서는 권한 체크 no-op"
    assert any(p in fixture for p in _STALE_PERMS_PHRASES)


# ── R3-1: callback state 필수 계약 ─────────────────────────────────

def test_callback_requires_state():
    """문서 계약(state 필수)이 코드와 일치: state 없이 호출하면 400."""
    resp = _client.get("/github/app/callback?installation_id=123")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "state is required"


# ── R302: 업로드 성공 응답 예시의 필드 드리프트 ─────────────────────
#
# 위 manifest 대조는 endpoint의 method/path 집합만 본다. 응답 예시의 JSON 구조는
# 비교하지 않으므로, 성공 응답 필드가 바뀌고 문서가 뒤처져도(또는 문서 수정을
# 통째로 되돌려도) 전부 통과한다. 실제로 구형 HTML이 그대로 통과하는 것이 확인됐다.
# 여기서는 endpoint 대조 로직은 건드리지 않고 **필드 집합 검사만** 추가한다.

# POST /documents 201 응답의 실제 계약 (backend/api/documents.py)
_UPLOAD_SUCCESS_FIELDS = {"doc_id", "status", "format", "blocks", "pages", "warnings"}


def _json_field_names(snippet: str) -> set[str]:
    """JSON 예시 문자열에서 최상위로 등장하는 키 이름을 뽑는다.

    중첩 객체(warnings 항목의 code/message/location)까지 포함되지만, 비교 대상인
    최상위 계약 필드가 모두 들어 있는지 확인하는 용도로는 충분하다.
    """
    return set(re.findall(r'"([A-Za-z_][A-Za-z0-9_]*)"\s*:', snippet))


def upload_success_example_md(text: str) -> str:
    """md의 `POST /documents` 절에서 201 응답 JSON 예시를 뽑는다."""
    section = text.split("### `POST /api/v1/projects/{project_id}/documents`", 1)[1]
    section = section.split("### `", 1)[0]
    match = re.search(r"\*\*응답 `201`\*\*\s*```json\s*(.*?)```", section, re.S)
    assert match, "md에서 201 응답 예시를 찾지 못했다"
    return match.group(1)


def upload_success_example_html(text: str) -> str:
    """html의 **업로드 카드**에서 201 응답 예시를 뽑는다.

    파일 전체에서 첫 201을 찾으면 회원가입 응답을 잡으므로, POST /documents 카드
    이후 구간으로 범위를 좁힌 뒤 검색한다.
    """
    marker = re.search(
        r'<span class="method POST">POST</span>\s*'
        r'<span class="path">/api/v1/projects/\{project_id\}/documents</span>',
        text,
    )
    assert marker, "html에서 POST /documents 카드를 찾지 못했다"
    section = text[marker.end():]
    match = re.search(
        r'<span class="s201">201</span> Created</div>\s*<pre><code>(.*?)</code></pre>',
        section,
        re.S,
    )
    assert match, "html에서 업로드 201 응답 예시를 찾지 못했다"
    return match.group(1)


def test_upload_success_example_fields_match_contract():
    """md·html의 201 예시가 실제 응답 계약 필드를 모두 담고 있어야 한다."""
    md_fields = _json_field_names(upload_success_example_md(_MD.read_text(encoding="utf-8")))
    html_fields = _json_field_names(upload_success_example_html(_HTML.read_text(encoding="utf-8")))

    missing_md = _UPLOAD_SUCCESS_FIELDS - md_fields
    missing_html = _UPLOAD_SUCCESS_FIELDS - html_fields
    assert not missing_md, f"md 201 예시에서 누락된 필드: {sorted(missing_md)}"
    assert not missing_html, f"html 201 예시에서 누락된 필드: {sorted(missing_html)}"


def test_upload_success_example_md_and_html_agree():
    """md와 html의 201 예시 필드 집합이 서로 일치해야 한다."""
    md_fields = _json_field_names(upload_success_example_md(_MD.read_text(encoding="utf-8")))
    html_fields = _json_field_names(upload_success_example_html(_HTML.read_text(encoding="utf-8")))
    assert md_fields == html_fields, (
        f"md↔html 201 예시 필드 불일치: "
        f"md-html={sorted(md_fields - html_fields)} html-md={sorted(html_fields - md_fields)}"
    )


def test_upload_field_guard_detects_stale_example():
    """가드 동작 증명: 구형 예시(doc_id·status만)는 반드시 검출된다.

    aed4695 시점의 html이 이 형태였고, endpoint manifest 검사만으로는 통과했다.
    """
    stale = '{ "doc_id": 12, "status": "processing" }'
    assert _UPLOAD_SUCCESS_FIELDS - _json_field_names(stale), (
        "구형 예시를 검출하지 못하면 이 가드는 무의미하다"
    )


def test_upload_success_response_matches_openapi_contract():
    """계약 상수가 실제 코드와 어긋나지 않는지 확인한다."""
    import inspect

    from backend.api import documents

    source = inspect.getsource(documents.upload_document)
    for field in _UPLOAD_SUCCESS_FIELDS:
        assert f'"{field}"' in source, f"업로드 응답에 {field}가 없다(계약 상수가 낡음)"


# ── 변환 경고 코드 명세 (PR-001-R402) ──────────────────────────────────────

def test_warning_codes_documented_in_both_specs():
    """R402: 경고 코드 전체가 md·html 양쪽 명세에 기술돼야 한다.

    이전에는 `table_flattened` 하나만 예시로 있고 나머지는 정책서 링크로 넘겨서,
    API 명세만 보는 소비자가 7종 중 1종만 알 수 있었다.
    """
    from backend.pipeline.converters.base import WarningCode

    codes = [
        v for k, v in vars(WarningCode).items()
        if not k.startswith("_") and isinstance(v, str)
    ]
    assert len(codes) >= 7, "WarningCode 목록이 예상보다 적다"

    md = _MD.read_text(encoding="utf-8")
    html = _HTML.read_text(encoding="utf-8")
    for code in codes:
        assert code in md, f"Markdown 명세에 {code} 없음"
        assert code in html, f"HTML 명세에 {code} 없음"


def test_nullable_warning_location_documented():
    """R402: location이 null일 수 있다는 계약이 명세에 드러나야 한다."""
    md = _MD.read_text(encoding="utf-8")
    html = _HTML.read_text(encoding="utf-8")
    assert "null" in md and "location" in md
    assert "null" in html and "location" in html
    # 개수 요약 1건으로 바뀐 경고는 그 사실이 적혀 있어야 한다.
    assert "개수 요약" in md
    assert "개수 요약" in html
