#!/usr/bin/env python3
"""골든셋 평가 파이프라인 (TASK-006, 계층 4).

설계 정본: backend/test/golden/EVAL_DESIGN.md — 6구성 매트릭스(R0-sql/vec/both
→ E0 → E1 → E2) × 측정 5축(RAGAS/라우팅 감사/체인 포함률/기권률/출처 추적성).
사용법: backend/test/golden/README.md (사전 조건·재실행 시나리오 포함).

상태 모델 요약:
  db-up → ingest(1회) → checkpoint(pre-pairs) → [R0×3·E0 측정] → pairs
  → [E1·E2 측정] → audit → report
- 한 프로세스 = 한 코퍼스 = 한 단계. `all`은 단계별 subprocess 순차 실행
  (Chroma/vectorstore 싱글톤 캐시 오염 차단).
- pairs 실패 시 pre-pairs 체크포인트로 자동 복구(보상 트랜잭션) 후 중단.
- 백엔드 서비스 코드는 읽기 전용으로 재사용하며, 구성 토글은 이 프로세스 안의
  모듈 속성 설정+복원으로만 수행한다.
"""
import argparse
import csv
import importlib.machinery
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
import types
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent          # backend/test/golden
REPO = HERE.parents[2]
STATE_DIR = HERE / ".eval_state"                 # gitignore — 체크포인트·덤프·마커
RESULTS_DIR = HERE / "results"

CORPORA = {
    "modu": {"dir": "Test_modu", "qa": "Test_modu/qa_set_Modu.json"},
    "csbot": {"dir": "Test_CS-Bot", "qa": "Test_CS-Bot/paim_qa_testset.json"},
}

DB_CONTAINER = "paim-eval-db"
DB_PORT = "3316"
DB_PASSWORD = "eval"
DB_NAME = "paim"                                 # 컨테이너 기본 DB(부트스트랩용)
# 코퍼스별 스키마 격리(리뷰 P1-A): modu·csbot이 한 DB를 공유하면 전체-DB
# 스냅샷/복원이 서로의 행을 덮어쓴다. 코퍼스마다 별도 스키마(paim_modu/paim_csbot)를
# 두면 mysqldump/restore가 자연히 그 코퍼스에만 국한된다.
def db_name(corpus: str) -> str:
    return f"paim_{corpus}"


# 스키마 파일은 DB명 비종속(순수 CREATE TABLE) — 각 코퍼스 스키마에 순서대로 적용.
INITDB_FILES = ["schema.sql"] + [f"migrate_v{i}.sql" for i in range(2, 9)]

# judge는 dev·final 모두 gpt-4.1-mini로 통일(사용자 결정 2026-07-20):
#  (1) gpt-4o-mini는 429 재시도 폭풍으로 일일 요청(RPD 10K) 버킷이 소진돼 교체.
#  (2) 4o 계열(멀티모달)은 텍스트 평가에 불필요 — 사용 금지 지시.
#  (3) "dev 승격 + 생성 지표만 final 증분" 방식이라 보고 수치가 한 judge를
#      공유해야 정합. gpt-4.1은 TPM 30K로 context_precision을 못 버텨(증분 NaN
#      실측) 부적합 — gpt-4.1-mini(TPM 200K)로 통일.
# 백엔드 본체와 같은 4.1-mini 버킷을 공유하므로 workers 기본값을 낮춰 포화 예방.
PHASE_JUDGE = {"dev": "gpt-4.1-mini", "final": "gpt-4.1-mini"}
WORKERS_DEFAULT = 3  # measure 병렬성 — METHODS as-run 기록과 공유(리뷰 R5-002)
# judge max_tokens 상향(실측 확인): ragas llm_factory 기본 1024는 E0(원본 생성
# 답변) faithfulness의 진술 분해 출력이 잘려 IncompleteOutputException→NaN을
# 유발한다(modu E0 final Job[62]). 4096으로 상향해 판정 출력 잘림을 방지.
JUDGE_MAX_TOKENS = 4096
MAIN_CONFIGS = ["R0-sql", "R0-vec", "R0-both", "E0", "E1", "E2-e2e"]
AUX_CONFIGS = ["E2-oracle"]
# 구성별 (recency 가중, DB 상태 전제): pre = pairs 적용 전, post = 적용 후
CONFIG_SPEC = {
    "R0-sql":    {"recency": 0.0, "state": "pre"},
    "R0-vec":    {"recency": 0.0, "state": "pre"},
    "R0-both":   {"recency": 0.0, "state": "pre"},
    "E0":        {"recency": 0.0, "state": "pre"},
    "E1":        {"recency": 0.0, "state": "post"},
    "E2-e2e":    {"recency": 0.2, "state": "post"},
    "E2-oracle": {"recency": 0.2, "state": "post"},
}

SUMMARY_COLUMNS = [
    "run_id", "date", "commit", "corpus", "config", "phase", "judge", "n",
    "context_precision", "context_recall", "faithfulness", "response_relevancy",
    "citation_grounding",
    "routing_accuracy", "history_detect_rate", "chain_inclusion_rate",
    "abstain_rate",
]

# 기권(환각 방지) 판정 패턴 — SYSTEM_QA가 지시하는 "기록에서 확인되지 않는다" 계열
ABSTAIN_PATTERNS = [
    "확인되지 않", "확인할 수 없", "기록에 없", "기록에서 찾을 수 없",
    "나타나 있지 않", "포함되어 있지 않", "언급되어 있지 않", "정보가 없",
    "제공된 컨텍스트에 없", "알 수 없",
]


# ── 환경 설정 (backend 모듈 import 전에 호출) ────────────────────────────────

def setup_env(corpus: str | None = None) -> None:
    # .env를 먼저 로드(OPENAI/LANGSMITH 키) — 그 다음 평가용 DB 설정을 명시
    # 대입으로 덮어써 개발용 DB(.env의 DB_*)와 절대 섞이지 않게 한다.
    try:
        from dotenv import load_dotenv
        load_dotenv(REPO / ".env")
        load_dotenv(REPO / "backend" / "test" / ".env")
    except ImportError:
        pass
    os.environ["DB_HOST"] = "127.0.0.1"
    os.environ["DB_PORT"] = DB_PORT
    os.environ["DB_USER"] = "root"
    os.environ["DB_PASSWORD"] = DB_PASSWORD
    # 코퍼스별 스키마로 격리(P1-A). 코퍼스 없이 호출되면 부트스트랩 DB.
    os.environ["DB_NAME"] = db_name(corpus) if corpus else DB_NAME
    os.environ["PAIM_AUTH_MODE"] = "dev"
    if corpus:
        os.environ["CHROMA_PERSIST_DIR"] = str(STATE_DIR / corpus / "chroma")


def require_openai_key() -> None:
    key = os.getenv("OPENAI_API_KEY", "")
    if not key or key.startswith("sk-placeholder"):
        sys.exit("[중단] OPENAI_API_KEY가 필요합니다 — 적재(추출 LLM)·임베딩·"
                 "RAGAS judge 전부 OpenAI 호출입니다. .env 또는 환경변수로 설정하세요.")


def disable_langsmith() -> None:
    """--no-langsmith: client·tracing 생성 자체를 우회한다(plan 리뷰 2-P3)."""
    for var in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2"):
        os.environ[var] = "false"
    os.environ.pop("LANGSMITH_API_KEY", None)
    os.environ.pop("LANGCHAIN_API_KEY", None)


def enable_langsmith(corpus: str, config: str, runid: str) -> bool:
    if not os.getenv("LANGSMITH_API_KEY"):
        return False
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_PROJECT"] = f"golden-{corpus}-{config}-{runid}"
    return True


# ── 골든 데이터 로더 (결정론 — 단위 테스트 대상) ─────────────────────────────

def normalize_tag(tag: str) -> str:
    """코퍼스 간 태그 표기 통일: csbot의 'hallu' → 'hallucination'(plan 리뷰 1-6)."""
    return "hallucination" if tag == "hallu" else tag


def load_golden(golden_dir: Path = HERE) -> list[dict]:
    """QA 60문항 + 라우팅 라벨 병합. 카운트 계약(코퍼스당 비환각 26·환각 4)을 단언."""
    routing = {(r["corpus"], r["id"]): r
               for r in json.loads((golden_dir / "routing_expected.json").read_text(encoding="utf-8"))}
    questions: list[dict] = []
    for corpus, spec in CORPORA.items():
        items = json.loads((golden_dir / spec["qa"]).read_text(encoding="utf-8"))
        assert len(items) == 30, f"{corpus}: 30문항이어야 함, {len(items)}"
        for item in items:
            label = routing.get((corpus, item["id"]))
            assert label is not None, f"라우팅 라벨 누락: {corpus}-{item['id']}"
            questions.append({
                "corpus": corpus,
                "qid": item["id"],
                "tag": normalize_tag(item["tag"]),
                "question": item["question"],
                "reference": item["answer"],
                "source": item.get("source", ""),
                "expected_route": label["expected_route"],
                "expected_history_mode": label["expected_history_mode"],
                "expected_chain_pairs": label.get("expected_chain_pairs", []),
            })
        n_hallu = sum(1 for q in questions
                      if q["corpus"] == corpus and q["tag"] == "hallucination")
        assert n_hallu == 4, f"{corpus}: 환각 4문항이어야 함, {n_hallu}"
    assert len(questions) == 60
    assert sum(1 for q in questions if q["tag"] != "hallucination") == 52
    return questions


def load_pairs(golden_dir: Path = HERE) -> list[dict]:
    return json.loads((golden_dir / "golden_supersede_pairs.json").read_text(encoding="utf-8"))["pairs"]


# ── pair 매칭·상태 검사 (결정론 — 단위 테스트 대상) ──────────────────────────

class PairMatchError(Exception):
    """pair 매칭 실패(0개/다중) — 후보 목록을 담아 조용히 넘어가지 않게 한다."""


def match_pairs(pairs: list[dict], rows: list[dict], corpus: str) -> dict[str, dict]:
    """활성 decision 행에서 각 pair의 old/new를 부분 문자열로 유일 매칭한다.

    반환: pair_id → {old_id, new_id(neg는 None)}. 0개/다중 매칭은 PairMatchError
    (후보 출력). negative pair는 old 존재만 검증하고 적용 대상에서 구조적 제외.
    """
    decisions = [r for r in rows if r.get("category") == "decision"
                 and r.get("superseded_by") is None]
    resolved: dict[str, dict] = {}
    for pair in pairs:
        if pair["corpus"] != corpus:
            continue

        def find_one(needle: str, role: str) -> int:
            hits = [r for r in decisions if needle in (r.get("content") or "")]
            if len(hits) != 1:
                cands = "\n".join(f"  - id={r['id']}: {r['content'][:80]}"
                                  for r in hits or decisions)
                raise PairMatchError(
                    f"[{pair['pair_id']}] {role} '{needle}' 매칭 {len(hits)}건"
                    f"(정확히 1건 필요). 후보:\n{cands}\n"
                    f"→ golden_supersede_pairs.json의 match 문구를 보정 후 재시도")
            return hits[0]["id"]

        old_id = find_one(pair["old_match"], "old")
        if pair["kind"] == "negative":
            resolved[pair["pair_id"]] = {"old_id": old_id, "new_id": None,
                                         "kind": "negative"}
            continue
        new_id = find_one(pair["new_match"], "new")
        if old_id == new_id:
            raise PairMatchError(f"[{pair['pair_id']}] old와 new가 같은 행({old_id})")
        old_row = next(r for r in decisions if r["id"] == old_id)
        new_row = next(r for r in decisions if r["id"] == new_id)
        if (old_row.get("date") and new_row.get("date")
                and str(old_row["date"]) > str(new_row["date"])):
            raise PairMatchError(
                f"[{pair['pair_id']}] 날짜 역전: old({old_row['date']}) > new({new_row['date']})")
        resolved[pair["pair_id"]] = {"old_id": old_id, "new_id": new_id,
                                     "kind": "positive"}
    return resolved


def check_state(relations: set[tuple], expected: set[tuple],
                old_vector_present: dict[int, bool], expect: str) -> list[str]:
    """구성-상태 정밀 검사(plan 리뷰 2-P1d). 위반 목록을 반환(빈 목록 = 통과).

    relations: DB의 (old_id, new_id) supersede 관계 전체.
    expected: 골든 positive pair의 (old_id, new_id) 집합.
    old_vector_present: old_id → Chroma memory 벡터 존재 여부.
    expect: 'pre' = 관계 0건 + old 벡터 전부 존재 / 'post' = 관계가 expected와
    정확히 일치 + old 벡터 전부 부재.
    """
    problems = []
    if expect == "pre":
        if relations:
            problems.append(f"pre 상태인데 supersede 관계 {len(relations)}건 존재: {sorted(relations)}")
        for old_id, present in old_vector_present.items():
            if not present:
                problems.append(f"pre 상태인데 old 벡터 부재: memory:{old_id}")
    elif expect == "post":
        if relations != expected:
            problems.append(f"관계 불일치: DB={sorted(relations)} 기대={sorted(expected)}")
        for old_id, present in old_vector_present.items():
            if present:
                problems.append(f"post 상태인데 old 벡터 잔존: memory:{old_id}")
    else:
        raise ValueError(expect)
    return problems


def _suggestion_target(sugg: dict) -> int | None:
    """supersede 제안이 가리키는 new decision id(evidence.superseding_memory_id).
    문자열/딕셔너리 evidence 모두 방어적으로 파싱, 없으면 None(P2-E)."""
    ev = sugg.get("evidence")
    if isinstance(ev, str):
        try:
            ev = json.loads(ev)
        except (ValueError, TypeError):
            return None
    if isinstance(ev, dict):
        target = ev.get("superseding_memory_id")
        return int(target) if isinstance(target, (int, str)) and str(target).isdigit() \
            else None
    return None


def is_abstain(answer: str) -> bool:
    return any(p in answer for p in ABSTAIN_PATTERNS)


def _gen_context(debug: dict, contexts: list) -> str:
    """생성에 넘길 컨텍스트 — 서비스 렌더링 컨텍스트(출처 마커 포함) 우선, 없으면
    (R0 구성은 rendered_context를 만들지 않음) 수집된 원문 컨텍스트를 join한다.
    빈 컨텍스트로 답변·기권을 생성하지 않도록 폴백한다(리뷰 C5-002)."""
    return debug.get("rendered_context") or "\n".join(contexts)


def split_contexts(debug: dict) -> tuple[list, list]:
    """디버그 dict에서 SQL 구조화 기록과 벡터 원문 청크를 출처 라벨·렌더링
    메타데이터와 함께 분리 추출한다(오프라인 추적용 스냅샷 저장).

    R0 수집기는 mysql_rows/chroma_chunks에 리스트가 아니라 정수 카운트를 넣으므로
    비리스트 값은 빈 리스트로 처리한다(리뷰 C5-001). SQL 행은 실제 LLM 입력
    (_row_line_body)에 쓰이는 owner·date·due_date·완료 상태까지 보존한다(C5-003)."""
    mysql = debug.get("mysql_rows")
    chroma = debug.get("chroma_chunks")
    mysql = mysql if isinstance(mysql, list) else []
    chroma = chroma if isinstance(chroma, list) else []
    sql = [{"content": r.get("content"), "source_label": r.get("source_label"),
            "category": r.get("category"), "owner": r.get("owner"),
            "date": r.get("date"), "due_date": r.get("due_date"),
            "completed": r.get("completed")}
           for r in mysql]
    vec = [{"text": c.get("text_full") or c.get("text"),
            "source_label": c.get("source_label"), "date": c.get("date")}
           for c in chroma]
    return sql, vec


def citation_grounding(answer: str, source_labels: list[str]) -> float:
    """출처 추적성 — 답변이 실제 검색 출처를 인용했는지 판정(TASK-007).

    각 `(출처: …)` 마커를 **알려진 출처 라벨을 경계로 파싱**한다. 마커는
    `(출처: ` + 라벨(`, ` 구분으로 여럿) + `)` 구조로 보고, 현재 위치에서 검색
    출처 라벨 집합의 라벨을 리터럴로 소비하며 진행한다. 라벨을 경계로 쓰므로
    파일명·라벨에 `)`가 있어도(예: `README.md (repo#7)`) 안전하고(리뷰 R-003·
    R3-P2), `(출처: A, B)`처럼 여럿을 묶은 인용도 인정한다(스모크 확인).

    - 마커 안에서 알려진 라벨로 해석되지 않는 토큰(허위 출처·'구조화 기록' 등
      유형 라벨)이 하나라도 있으면 근거 없는 인용으로 보고 0점(리뷰 R-006).
    - 마커 밖 본문의 단순 파일명 언급·부분문자열 겹침은 인용으로 치지 않는다.

    반환: 1.0(근거 있는 인용이 있고 근거 없는 인용이 없음) / 0.0.
    """
    text = answer or ""
    # 접두 충돌(한 라벨이 다른 라벨의 접두)을 피하려 긴 라벨부터 매칭.
    labels = sorted({s for s in source_labels if s}, key=len, reverse=True)
    open_tok = "(출처:"
    grounded = 0
    ungrounded = 0
    i = 0
    while (start := text.find(open_tok, i)) != -1:
        pos = start + len(open_tok)
        while pos < len(text) and text[pos] == " ":
            pos += 1
        while True:
            matched = next((L for L in labels if text.startswith(L, pos)), None)
            if matched is None:                 # 알려진 출처가 아님 → 근거 없음
                ungrounded += 1
                end = text.find(")", pos)
                pos = end + 1 if end != -1 else len(text)
                break
            grounded += 1
            pos += len(matched)
            if text.startswith(", ", pos):      # 다중 출처 — 다음 라벨로
                pos += 2
                continue
            if pos < len(text) and text[pos] == ")":   # 마커 정상 종료
                pos += 1
                break
            ungrounded += 1                     # 라벨 뒤 예상 밖 텍스트
            end = text.find(")", pos)
            pos = end + 1 if end != -1 else len(text)
            break
        i = pos
    return 1.0 if grounded > 0 and ungrounded == 0 else 0.0


def chain_included(context_texts: list[str], pair: dict) -> bool:
    """체인 포함 판정(plan 리뷰 2-9): 기대 pair의 old/new 문구가 컨텍스트에 실제 존재."""
    joined = "\n".join(context_texts)
    return pair["old_match"] in joined and (
        pair.get("new_match") is None or pair["new_match"] in joined)


def chain_source_texts(debug: dict) -> list[str]:
    """체인 판정 원천(R2-001): 계층 3 이력 체인은 MySQL 이력 행으로만 컨텍스트에
    들어간다. 원문 Chroma 청크에 우연히 든 결정 문구가 판정을 통과시키지 않도록
    debug["mysql_rows"]의 content만 쓴다(RAGAS용 통합 contexts와 분리)."""
    rows = debug.get("mysql_rows")
    if not isinstance(rows, list):
        return []
    return [r.get("content", "") for r in rows if isinstance(r, dict)]


# ── summary writer (결정론 — 단위 테스트 대상) ───────────────────────────────

class SummaryWriter:
    """(run_id, corpus, config, phase) 키 upsert. judge 불일치는 거부(리뷰 3-P2)."""

    KEY = ("run_id", "corpus", "config", "phase")

    def __init__(self, path: Path):
        self.path = path

    def _load(self) -> list[dict]:
        if not self.path.exists():
            return []
        with open(self.path, newline="", encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))

    def upsert(self, row: dict, overwrite: bool = False) -> None:
        rows = self._load()
        key = tuple(str(row[k]) for k in self.KEY)
        merged = {c: row.get(c, "") for c in SUMMARY_COLUMNS}
        for existing in rows:
            if tuple(existing.get(k, "") for k in self.KEY) == key:
                if (existing.get("judge") and merged.get("judge")
                        and existing["judge"] != merged["judge"] and not overwrite):
                    raise RuntimeError(
                        f"summary judge 충돌: 기존 {existing['judge']} ↔ 신규 "
                        f"{merged['judge']} (키 {key}). --overwrite로만 교체 가능")
                for col in SUMMARY_COLUMNS:      # 빈 값은 기존 값 유지(병합)
                    if merged.get(col) in ("", None) and existing.get(col):
                        merged[col] = existing[col]
                existing.update(merged)
                break
        else:
            rows.append(merged)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=SUMMARY_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)

    def delete(self, key_row: dict) -> bool:
        """(run_id,corpus,config,phase) 키 행을 제거. 제거했으면 True(리뷰 R6-001)."""
        rows = self._load()
        key = tuple(str(key_row[k]) for k in self.KEY)
        kept = [r for r in rows if tuple(r.get(k, "") for k in self.KEY) != key]
        if len(kept) == len(rows):
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=SUMMARY_COLUMNS)
            writer.writeheader()
            writer.writerows(kept)
        return True


# ── 마커·공용 헬퍼 ───────────────────────────────────────────────────────────

def marker_path(runid: str, corpus: str, config: str, phase: str) -> Path:
    return STATE_DIR / "markers" / f"{runid}_{corpus}_{config}_{phase}.done"


def detail_path_for(corpus: str, config: str, phase: str, runid: str) -> Path:
    prefix = "oracle" if config == "E2-oracle" else "ragas"
    return RESULTS_DIR / f"{prefix}_{corpus}_{config}_{phase}_{runid}.csv"


def invalidate_measurement(runid: str, corpus: str, config: str,
                           phase: str) -> list[str]:
    """재측정 시작 전 기존 게시물 3종(완료 마커·상세 CSV·summary 행)을 제거해,
    재측정이 도중 실패해도 옛 결과가 '완료'로 남지 않게 한다(리뷰 R6-001).
    NaN 가드는 신규 게시만 막을 뿐, --overwrite 재측정이 또 실패하면 이전
    부분 평균·마커가 유효한 채 남아 이후 --resume이 건너뛰는 문제를 차단한다.
    제거한 항목 이름 목록을 반환한다."""
    removed = []
    marker = marker_path(runid, corpus, config, phase)
    if marker.exists():
        marker.unlink()
        removed.append(marker.name)
    detail = detail_path_for(corpus, config, phase, runid)
    if detail.exists():
        detail.unlink()
        removed.append(detail.name)
    if config != "E2-oracle":   # 보조 구성은 summary 계약 밖(상세 파일만)
        if SummaryWriter(RESULTS_DIR / "summary.csv").delete(
                {"run_id": runid, "corpus": corpus,
                 "config": config, "phase": phase}):
            removed.append("summary.csv 행")
    return removed


def invalid_marker(corpus: str) -> Path:
    return STATE_DIR / corpus / "INVALID"


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO,
                              capture_output=True, text=True).stdout.strip()
    except Exception:
        return "unknown"


def default_runid() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M")


def sh(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, **kw)


def run_step(args: list[str]) -> None:
    """단계를 subprocess로 실행(프로세스 격리) — 실패 시 즉시 중단."""
    result = subprocess.run([sys.executable, str(HERE / "run_eval.py")] + args)
    if result.returncode != 0:
        sys.exit(f"[중단] 단계 실패: {' '.join(args)}")


# ── 실행 로그: as-run trace (테스트가 어떻게 진행되었는지) ─────────────────────

def run_log_path(corpus: str, phase: str, runid: str) -> Path:
    return RESULTS_DIR / f"run_{corpus}_{phase}_{runid}.log"


def _rel(path: Path):
    """로그 출력용 상대 경로(REPO 밖이면 절대 경로 그대로)."""
    try:
        return path.relative_to(REPO)
    except ValueError:
        return path


class tee_output:
    """fd 1/2를 가로채 모든 출력을 [시각] 접두어와 함께 콘솔+로그파일에 남긴다.

    자식 프로세스는 fd를 상속하므로 `all`의 단계별 출력(적재 행수·상태 검사·
    measure 진행·pair 매칭·감사 요약)이 한 파일에 시간순으로 모인다. 최상위
    진입점(cmd_all)에서만 설치한다 — 자식이 다시 설치하면 파이프가 중첩된다.
    """

    def __init__(self, path: Path):
        self.path = path

    def __enter__(self) -> "tee_output":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        sys.stdout.flush()
        sys.stderr.flush()
        self._sink_errors: dict[str, str] = {}   # sink 실패 기록(파이프는 계속 배출)
        self._saved = (os.dup(1), os.dup(2))     # 복원용 원본 fd
        self._console = os.dup(1)                 # pump가 콘솔에 되쓸 fd
        self._logfile = open(self.path, "a", encoding="utf-8")
        self._logfile.write(
            f"\n===== run start {datetime.now().isoformat(timespec='seconds')}"
            f" (commit {git_commit()}) =====\n")
        self._logfile.flush()
        read_fd, write_fd = os.pipe()
        os.dup2(write_fd, 1)                      # stdout/stderr → 파이프
        os.dup2(write_fd, 2)
        os.close(write_fd)
        try:                                      # 줄 단위로 pump가 즉시 받도록
            sys.stdout.reconfigure(line_buffering=True)
            sys.stderr.reconfigure(line_buffering=True)
        except Exception:
            pass
        self._thread = threading.Thread(target=self._pump, args=(read_fd,),
                                        daemon=True)
        self._thread.start()
        return self

    def _pump(self, read_fd: int) -> None:
        # sink(콘솔/로그)가 죽어도 파이프는 EOF까지 계속 읽는다(P2-F): 안 그러면
        # 파이프 버퍼가 차서 자식/부모의 다음 출력이 영구 블로킹된다.
        with os.fdopen(read_fd, "r", errors="replace") as reader:
            for line in reader:                   # EOF = 모든 write fd 폐쇄 시
                stamp = datetime.now().strftime("%H:%M:%S")
                text = f"[{stamp}] {line}" if line.strip() else line
                # OSError 한정이면 닫힌 파일류의 ValueError 등에 pump가 EOF 전
                # 죽어 파이프가 포화된다(R2-003) — sink 예외는 전부 격리.
                try:
                    os.write(self._console, text.encode("utf-8", "replace"))
                except Exception as exc:
                    self._sink_errors["console"] = repr(exc)
                try:
                    self._logfile.write(text)
                    self._logfile.flush()
                except Exception as exc:
                    self._sink_errors["logfile"] = repr(exc)

    def __exit__(self, *exc) -> bool:
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(self._saved[0], 1)                # fd1/2 원복 → 파이프 write end
        os.dup2(self._saved[1], 2)                #   완전 폐쇄 → pump가 EOF 수신
        os.close(self._saved[0])
        os.close(self._saved[1])
        self._thread.join(timeout=5)
        if self._thread.is_alive():
            # pump가 아직 배출 중 — 여기서 sink를 닫으면 EOF 전 종료·로그 절단이
            # 된다(R2-003). daemon thread라 프로세스 종료는 막지 않으므로 sink를
            # 열어 둔 채 경고만 남긴다.
            self._sink_errors["pump"] = "join 5s 초과 — 잔여 배출 유지(sink 미폐쇄)"
        else:
            os.close(self._console)
            try:
                self._logfile.write(
                    f"===== run end {datetime.now().isoformat(timespec='seconds')} =====\n")
                self._logfile.close()
            except Exception as exc:                  # sink 예외는 전부 격리(R2-003)
                self._sink_errors["logfile"] = repr(exc)
        # sink 실패는 fd 원복 후 부모 콘솔에 경고로 전달(P2-F)
        if self._sink_errors:
            print(f"[경고] 실행 로그 sink 오류(파이프는 정상 배출됨): {self._sink_errors}",
                  file=sys.stderr)
        return False


def mysql_exec(sql: str, db: str | None = "__env__") -> str:
    # TCP 강제(-h127.0.0.1): MySQL 이미지의 initdb 단계는 소켓 전용 임시 서버라,
    # 소켓 프로브는 초기화가 끝나기 전에 성공해 스키마 검증이 조기 실행된다(실측).
    # db: "__env__"=현재 코퍼스 컨텍스트(os.environ DB_NAME), None=DB 미지정,
    #     그 외=명시 DB. 코퍼스별 스키마 격리(P1-A)와 일관되게 동작.
    if db == "__env__":
        db = os.environ.get("DB_NAME", DB_NAME)
    cmd = ["docker", "exec", DB_CONTAINER, "mysql", "-h127.0.0.1", "--protocol=TCP",
           "-uroot", f"-p{DB_PASSWORD}", "-N", "-e", sql]
    if db:
        cmd.append(db)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"mysql 실패: {result.stderr.strip()}")
    return result.stdout


def get_project_id(corpus: str) -> int:
    pid_file = STATE_DIR / corpus / "project_id"
    if not pid_file.exists():
        sys.exit(f"[중단] {corpus} 미적재 — 먼저 ingest를 실행하세요")
    return int(pid_file.read_text().strip())


def fetch_memory_rows(project_id: int) -> list[dict]:
    from backend.db.mysql import get_connection
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, category, content, topic, reason, date, superseded_by"
                " FROM memory WHERE project_id = %s ORDER BY id", (project_id,))
            return cur.fetchall()
    finally:
        conn.close()


def resolve_positive_matches(corpus: str) -> tuple[dict[str, dict], set[tuple]]:
    """현재 DB 상태에서 pair를 해석해 (resolved, positive (old,new) 집합) 반환.

    post 상태에서도 old 행을 찾아야 하므로 superseded 포함 전 행에서 매칭하되,
    match_pairs의 활성 필터를 우회하기 위해 superseded_by를 잠시 무시한 사본 사용.
    """
    project_id = get_project_id(corpus)
    rows = fetch_memory_rows(project_id)
    rows_as_active = [dict(r, superseded_by=None) for r in rows]
    resolved = match_pairs(load_pairs(), rows_as_active, corpus)
    expected = {(v["old_id"], v["new_id"]) for v in resolved.values()
                if v["kind"] == "positive"}
    return resolved, expected


def db_state(corpus: str) -> tuple[set[tuple], dict[int, bool]]:
    """DB 관계 집합 + 골든 old 벡터 존재 여부(Chroma 조회)."""
    project_id = get_project_id(corpus)
    resolved, _ = resolve_positive_matches(corpus)
    from backend.db.mysql import get_connection
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, superseded_by FROM memory"
                        " WHERE project_id = %s AND superseded_by IS NOT NULL",
                        (project_id,))
            relations = {(r["id"], r["superseded_by"]) for r in cur.fetchall()}
    finally:
        conn.close()
    from backend.db.chroma import get_collection
    from backend.retriever.memory_vector import memory_vector_id
    collection = get_collection()
    presence: dict[int, bool] = {}
    for value in resolved.values():
        if value["kind"] != "positive":
            continue
        got = collection.get(ids=[memory_vector_id(value["old_id"])])
        presence[value["old_id"]] = bool(got.get("ids"))
    return relations, presence


# ── 구성 토글 (복원형 context manager — plan 리뷰 1-1) ───────────────────────

class config_overrides:
    """진입 시 recency 가중을 명시 설정, 종료 시 원값 복원."""

    def __init__(self, config: str):
        self.config = config

    def __enter__(self):
        import backend.retriever.qa_engine as qa_engine
        self._qa = qa_engine
        self._saved = qa_engine.CHUNK_RECENCY_WEIGHT
        qa_engine.CHUNK_RECENCY_WEIGHT = CONFIG_SPEC[self.config]["recency"]
        return self

    def __exit__(self, *exc):
        self._qa.CHUNK_RECENCY_WEIGHT = self._saved
        return False


# ── 컨텍스트 수집기 ──────────────────────────────────────────────────────────

def collect_r0_sql(project_id: int, question: str) -> tuple[list[str], dict]:
    from backend.retriever import mysql_search, qa_engine
    rows = mysql_search.search(project_id)
    return [qa_engine._format_mysql_row(r) for r in rows], {"mysql_rows": len(rows)}


def collect_r0_vec(project_id: int, question: str) -> tuple[list[str], dict]:
    """dense 코사인만 — memory 벡터는 제외(document 청크 한정, plan 리뷰 1-5)."""
    from backend.retriever import qa_engine
    scored = qa_engine._get_vectorstore().similarity_search_with_score(
        question, k=qa_engine.CHROMA_TOP_N,
        filter={"$and": [{"project_id": project_id}, {"item_type": "document"}]})
    return [d.page_content for d, _ in scored], {"chroma_chunks": len(scored)}


def collect_r0_both(project_id: int, question: str) -> tuple[list[str], dict]:
    sql_ctx, _ = collect_r0_sql(project_id, question)
    vec_ctx, _ = collect_r0_vec(project_id, question)
    return sql_ctx + vec_ctx, {"mysql_rows": len(sql_ctx), "chroma_chunks": len(vec_ctx)}


def _build_context_configured(project_id: int, question: str, *, history_mode,
                              history_scope=None, history_topic_tokens=None):
    from backend.retriever import qa_engine
    context, sources, debug = qa_engine._build_context(
        project_id, question, history_mode=history_mode,
        history_scope=history_scope, history_topic_tokens=history_topic_tokens)
    # RAGAS context 지표용: 출처 마커 없는 원문(검색 품질 측정 입력 불변).
    contexts = ([r["content"] for r in debug.get("mysql_rows", [])]
                + [c["text_full"] for c in debug.get("chroma_chunks", [])])
    # 답변 생성·인용 측정용: 서비스가 LLM에 넘기는 렌더링 컨텍스트(출처 마커
    # 포함)를 그대로 보존한다(리뷰 R-001). 원문 join으로 대체하면 출처 마커가
    # 사라져 인용 지표가 항상 0이 되고 생성 지표도 실서비스와 어긋난다.
    debug["rendered_context"] = context
    # 검색된 출처 라벨 집합 — 인용 근거성 판정 기준(구조화 기록 + 원문 청크).
    debug["source_labels"] = sorted({
        lbl for lbl in (
            [r.get("source_label") for r in debug.get("mysql_rows", [])]
            + [c.get("source_label") for c in debug.get("chroma_chunks", [])])
        if lbl})
    return contexts, debug


def collect_e0(project_id: int, question: str) -> tuple[list[str], dict]:
    return _build_context_configured(project_id, question, history_mode=False)


def collect_e2_e2e(project_id: int, question: str) -> tuple[list[str], dict]:
    """실서비스 그대로: 라우터 감지 → predicate 고정 → _build_context →
    graph.qa_node와 동일하게 [프로젝트 메모리] 접두 조립(리뷰 R-005)."""
    from backend.graph import _resolve_history_state, get_project_memory
    from backend.retriever.query_intent import classify_question
    decision = classify_question(question)
    mode, scope, tokens, effective = _resolve_history_state(
        question, None, decision.history_mode)
    contexts, debug = _build_context_configured(
        project_id, effective, history_mode=mode,
        history_scope=scope, history_topic_tokens=tokens)
    # 실서비스(graph.qa_node)는 프로젝트 메모리 요약을 컨텍스트 앞에 얹는다.
    # 프로젝트 메모리는 파일 출처가 없는 요약이라 source_labels(인용 근거 집합)는
    # 바꾸지 않고 생성 컨텍스트에만 영향을 준다.
    parts = []
    mem = get_project_memory(project_id)
    if mem:
        parts.append(f"[프로젝트 메모리]\n{mem}")
    if debug.get("rendered_context"):
        parts.append(debug["rendered_context"])
    debug["rendered_context"] = "\n\n".join(parts)
    debug["route"] = decision.route
    debug["router_stage"] = decision.router_stage
    return contexts, debug


def make_collect_e2_oracle(expected_history: bool):
    def collect(project_id: int, question: str) -> tuple[list[str], dict]:
        from backend.graph import _resolve_history_state
        mode, scope, tokens, effective = _resolve_history_state(
            question, None, expected_history)
        return _build_context_configured(
            project_id, effective, history_mode=mode,
            history_scope=scope, history_topic_tokens=tokens)
    return collect


def get_collector(config: str, question_meta: dict):
    if config == "R0-sql":
        return collect_r0_sql
    if config == "R0-vec":
        return collect_r0_vec
    if config == "R0-both":
        return collect_r0_both
    if config in ("E0", "E1"):
        return collect_e0
    if config == "E2-e2e":
        return collect_e2_e2e
    if config == "E2-oracle":
        return make_collect_e2_oracle(question_meta["expected_history_mode"])
    raise ValueError(config)


# ── 서브커맨드: db-up / db-down ──────────────────────────────────────────────

def _apply_sql_file(db: str, path: Path) -> None:
    """스키마 파일 하나를 지정 DB에 적용(TCP)."""
    result = subprocess.run(
        ["docker", "exec", "-i", DB_CONTAINER, "mysql", "-h127.0.0.1",
         "--protocol=TCP", "-uroot", f"-p{DB_PASSWORD}", db],
        input=path.read_text(), capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"[중단] 스키마 적용 실패({db}, {path.name}): {result.stderr[:300]}")


def _schema_selfcheck(db: str) -> None:
    """스키마 자가 검증(plan 리뷰 1-4): 통과해야 ingest 허용."""
    checks = {
        "memory_suggestions 테이블":
            "SELECT COUNT(*) FROM information_schema.tables"
            f" WHERE table_schema='{db}' AND table_name='memory_suggestions'",
        "memory.superseded_by 컬럼":
            "SELECT COUNT(*) FROM information_schema.columns"
            f" WHERE table_schema='{db}' AND table_name='memory'"
            " AND column_name='superseded_by'",
        "active_memory 뷰":
            "SELECT COUNT(*) FROM information_schema.views"
            f" WHERE table_schema='{db}' AND table_name='active_memory'",
        "self-FK fk_memory_superseded_by":
            "SELECT COUNT(*) FROM information_schema.table_constraints"
            f" WHERE table_schema='{db}'"
            " AND constraint_name='fk_memory_superseded_by'",
    }
    for label, sql in checks.items():
        if mysql_exec(sql, db=None).strip() != "1":
            sys.exit(f"[중단] 스키마 자가 검증 실패({db}): {label}")


def cmd_db_up(args) -> None:
    existing = subprocess.run(["docker", "ps", "-aq", "-f", f"name=^{DB_CONTAINER}$"],
                              capture_output=True, text=True).stdout.strip()
    if existing:
        sys.exit(f"[중단] 컨테이너 {DB_CONTAINER} 이미 존재 — db-down 후 재시도")
    # 루프백 전용 바인딩(리뷰 P2-A): 약한 root pw의 일회용 DB가 LAN에 노출되지
    # 않게 127.0.0.1에만 게시. 스키마는 기동 후 코퍼스별로 직접 적용(P1-A)한다.
    sh(["docker", "run", "-d", "--name", DB_CONTAINER,
        "-e", f"MYSQL_ROOT_PASSWORD={DB_PASSWORD}",
        "-p", f"127.0.0.1:{DB_PORT}:3306", "mysql:8.0"], check=True)

    print("MySQL 초기화 대기(최대 180초)...")
    for _ in range(90):
        time.sleep(2)
        try:
            mysql_exec("SELECT 1", db=None)
            break
        except RuntimeError:
            continue
    else:
        sys.exit("[중단] MySQL 기동 실패 — docker logs 확인")

    # 코퍼스마다 별도 스키마를 만들고 파일을 순서대로 적용 → 전체-DB 스냅샷/복원이
    # 그 코퍼스에만 국한(P1-A). 스키마 파일은 DB명 비종속이라 동일 파일 재사용.
    for corpus in CORPORA:
        db = db_name(corpus)
        mysql_exec(f"CREATE DATABASE IF NOT EXISTS `{db}`"
                   " CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci", db=None)
        for name in INITDB_FILES:
            _apply_sql_file(db, REPO / "backend" / "db" / name)
        _schema_selfcheck(db)
    (STATE_DIR).mkdir(exist_ok=True)
    (STATE_DIR / "db-ready").write_text(datetime.now().isoformat())
    print(f"[완료] db-up + 코퍼스별 스키마({', '.join(db_name(c) for c in CORPORA)}) "
          "자가 검증 통과")


def cmd_db_down(args) -> None:
    sh(["docker", "rm", "-f", DB_CONTAINER])
    (STATE_DIR / "db-ready").unlink(missing_ok=True)
    print("[완료] db-down")


# ── 서브커맨드: ingest ───────────────────────────────────────────────────────

def corpus_transcripts(corpus: str) -> list[Path]:
    """코퍼스 회의록 목록(oldest-first). 날짜 접두(YYYY-MM-DD) .md만 적재한다 —
    QA 테스트셋·타임라인 등 참고 문서가 코퍼스에 섞이면 gold 답변이 검색
    대상이 되어 평가가 오염된다(실측 1회차에서 발견: modu의 QA·타임라인 .md가
    적재돼 중복 결정 행 생성 + 정답 유출)."""
    files = []
    for p in sorted((HERE / CORPORA[corpus]["dir"]).glob("*.md")):
        try:
            datetime.strptime(p.name[:10], "%Y-%m-%d")
        except ValueError:
            print(f"  [제외] 회의록 아님(날짜 접두 없음): {p.name}")
            continue
        files.append(p)
    return files


def cmd_ingest(args) -> None:
    corpus = args.corpus
    setup_env(corpus)
    require_openai_key()
    if not (STATE_DIR / "db-ready").exists():
        sys.exit("[중단] db-up 먼저 실행")
    cstate = STATE_DIR / corpus
    if (cstate / "project_id").exists():
        if not args.force:
            sys.exit(f"[중단] {corpus} 이미 적재됨 — 적재 1회 원칙. 재적재는 --force"
                     "(코퍼스 상태 완전 삭제 후 재생성)")
        # --force: 부분 정리 금지 — 프로젝트 행·Chroma dir 완전 삭제
        old_pid = int((cstate / "project_id").read_text())
        for table in ("memory_suggestions", "memory_sources"):
            mysql_exec(f"DELETE FROM {table} WHERE memory_id IN"
                       f" (SELECT id FROM (SELECT id FROM memory WHERE project_id={old_pid}) t)"
                       if table == "memory_sources" else
                       f"DELETE FROM {table} WHERE project_id={old_pid}")
        mysql_exec(f"UPDATE memory SET superseded_by=NULL WHERE project_id={old_pid}")
        mysql_exec(f"DELETE FROM memory WHERE project_id={old_pid}")
        mysql_exec(f"DELETE FROM documents WHERE project_id={old_pid}")
        mysql_exec(f"DELETE FROM project_memory WHERE project_id={old_pid}")
        mysql_exec(f"DELETE FROM projects WHERE id={old_pid}")
        shutil.rmtree(cstate, ignore_errors=True)
    cstate.mkdir(parents=True, exist_ok=True)

    # 프로젝트 생성
    mysql_exec(f"INSERT INTO projects (name) VALUES ('golden-{corpus}')")
    project_id = int(mysql_exec(
        f"SELECT id FROM projects WHERE name='golden-{corpus}' ORDER BY id DESC LIMIT 1"
    ).strip())
    (cstate / "project_id").write_text(str(project_id))

    # 훅 recorder(plan 리뷰 2-8·3-P3): 문서 레코드 선생성 + detect_supersede 원천
    # 모듈 패치(ingestor는 함수 내부 지역 import라 원천을 패치해야 잡힌다).
    import backend.reconciler.supersede as supersede_mod
    from backend.pipeline.extractor import extract
    from backend.pipeline.ingestor import ingest
    from backend.db.mysql import get_connection

    hook_log: list[dict] = []
    original_detect = supersede_mod.detect_supersede

    def recorded_detect(project_id_, new_decisions):
        record = hook_log[-1]
        try:
            result = original_detect(project_id_, new_decisions)
            record.update(status="called", **result)
            return result
        except Exception as exc:
            record.update(status="error", error=f"{type(exc).__name__}: {exc}")
            raise    # ingest가 현행대로 삼키지만 recorder에는 error로 남는다

    supersede_mod.detect_supersede = recorded_detect
    try:
        md_files = corpus_transcripts(corpus)                            # oldest-first
        for md in md_files:
            date = md.name[:10]
            print(f"  적재: {md.name} (date={date})")
            hook_log.append({"doc": md.name, "status": "no_new_decisions"})
            conn = get_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO documents (project_id, filename, doc_type)"
                        " VALUES (%s, %s, 'meeting')", (project_id, md.name))
                    doc_id = cur.lastrowid
                conn.commit()
            finally:
                conn.close()
            items = extract(md.read_text(encoding="utf-8"), default_source=md.name)
            ingest(project_id=project_id, doc_id=doc_id, items=items,
                   raw_text=md.read_text(encoding="utf-8"), source=md.name,
                   date=date, doc_type="meeting")
    finally:
        supersede_mod.detect_supersede = original_detect

    # 실서비스는 적재 후 프로젝트 메모리 요약을 만들어 QA 컨텍스트 최상단에
    # 얹는다(graph.qa_node). E2-e2e가 그 경로를 충실히 재현하도록 eval도 동일
    # 생성한다(리뷰 R-005). checkpoint(mysqldump)에 포함돼 final restore 시 복원.
    from backend.graph import regenerate_project_memory
    regenerate_project_memory(project_id)

    # 적재 결과 덤프(runid 무관 — 코퍼스 상태에 귀속)
    rows = fetch_memory_rows(project_id)
    suggestions = []
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, memory_id, kind, confidence, status, evidence"
                        " FROM memory_suggestions WHERE project_id = %s", (project_id,))
            suggestions = cur.fetchall()
    finally:
        conn.close()
    (cstate / "ingest_dump.json").write_text(json.dumps(
        {"project_id": project_id, "memory_rows": rows, "suggestions": suggestions,
         "hook_log": hook_log},
        ensure_ascii=False, indent=1, default=str))
    print(f"[완료] ingest {corpus}: memory {len(rows)}행, 제안 {len(suggestions)}건, "
          f"훅 로그 {len(hook_log)}건 → {cstate/'ingest_dump.json'}")


# ── 서브커맨드: checkpoint / restore / _state-check ──────────────────────────

def checkpoint_paths(corpus: str) -> tuple[Path, Path]:
    return (STATE_DIR / corpus / "checkpoint.sql",
            STATE_DIR / corpus / "checkpoint_chroma")


def checkpoint_ok(corpus: str) -> Path:
    """체크포인트 완성 표식(P1-D): sql+chroma가 모두 게시된 뒤에만 존재.
    소비자(pairs·restore)는 이 표식으로만 '유효한 체크포인트'를 판정한다."""
    return STATE_DIR / corpus / "checkpoint.ok"


def cmd_checkpoint(args) -> None:
    corpus = args.corpus
    # 생성 가드(plan 리뷰 3-P1a): pre-state 검증 통과 시에만 생성/덮어쓰기
    check = subprocess.run(
        [sys.executable, str(HERE / "run_eval.py"), "_state-check",
         "--corpus", corpus, "--expect", "pre"])
    if check.returncode != 0:
        sys.exit("[중단] 현재 상태가 pre-pairs가 아님 — 오염 상태를 체크포인트로 "
                 "확정할 수 없습니다. restore 또는 ingest --force로 정리 후 재시도")
    sql_path, chroma_path = checkpoint_paths(corpus)
    ok_path = checkpoint_ok(corpus)
    chroma_src = STATE_DIR / corpus / "chroma"
    sql_tmp = Path(str(sql_path) + ".tmp")
    chroma_tmp = Path(str(chroma_path) + ".tmp")

    # 원자적 게시(P1-D): 두 산출물을 임시 위치에 완성한 뒤 함께 교체하고, 완성
    # 표식은 맨 마지막에 쓴다. 중단되면 .ok가 없어 소비자가 무효로 취급한다.
    ok_path.unlink(missing_ok=True)          # 게시 시작 → 기존 유효 표식 무효화
    try:
        dump = subprocess.run(
            ["docker", "exec", DB_CONTAINER, "mysqldump", "-h127.0.0.1",
             "--protocol=TCP", "-uroot", f"-p{DB_PASSWORD}", db_name(corpus)],
            capture_output=True, text=True)
        if dump.returncode != 0:
            sys.exit(f"[중단] mysqldump 실패: {dump.stderr[:300]}")
        sql_tmp.write_text(dump.stdout)
        if chroma_tmp.exists():
            shutil.rmtree(chroma_tmp)
        shutil.copytree(chroma_src, chroma_tmp)
        # 둘 다 완성 → 교체
        os.replace(sql_tmp, sql_path)
        if chroma_path.exists():
            shutil.rmtree(chroma_path)
        os.rename(chroma_tmp, chroma_path)
    finally:
        sql_tmp.unlink(missing_ok=True)
        if chroma_tmp.exists():
            shutil.rmtree(chroma_tmp, ignore_errors=True)
    ok_path.write_text(datetime.now().isoformat())
    print(f"[완료] checkpoint {corpus} (pre-pairs 상태 저장)")


def cmd_restore(args) -> None:
    corpus = args.corpus
    sql_path, chroma_path = checkpoint_paths(corpus)
    if not checkpoint_ok(corpus).exists():
        sys.exit(f"[중단] {corpus} 유효한 체크포인트 없음(미완성/부재)")
    restore = subprocess.run(
        ["docker", "exec", "-i", DB_CONTAINER, "mysql", "-h127.0.0.1",
         "--protocol=TCP", "-uroot", f"-p{DB_PASSWORD}", db_name(corpus)],
        input=sql_path.read_text(), capture_output=True, text=True)
    if restore.returncode != 0:
        invalid_marker(corpus).write_text("restore 실패(MySQL)")
        sys.exit(f"[중단] restore 실패 — run을 invalid로 봉인: {restore.stderr[:300]}")
    # Chroma 복원 실패도 반쪽 상태이므로 INVALID로 봉인(P1-F): 부분 복사본이 남으면
    # pre 검사가 다른 누락 벡터를 못 잡아 오염 상태로 측정될 수 있다.
    chroma_dst = STATE_DIR / corpus / "chroma"
    try:
        shutil.rmtree(chroma_dst, ignore_errors=True)
        shutil.copytree(chroma_path, chroma_dst)
    except Exception as exc:
        invalid_marker(corpus).write_text(f"restore 실패(Chroma): {exc}")
        sys.exit(f"[중단] Chroma 복원 실패 — run을 invalid로 봉인: {exc}")
    invalid_marker(corpus).unlink(missing_ok=True)
    print(f"[완료] restore {corpus} (pre-pairs 상태 복원)")


def cmd_pmem(args) -> None:
    """현재 코퍼스 DB의 memory 행에서 프로젝트 메모리 요약을 (재)생성한다(R-005).

    코퍼스를 재적재(비결정적 LLM extract)하지 않고 프로젝트 메모리만 채우므로,
    프로젝트 메모리 도입 이전에 만든 checkpoint에 이 보강을 적용할 때 쓴다:
    restore → pmem → checkpoint 로 코퍼스를 보존한 채 checkpoint에 포함시킨다.
    (dev context 승격분을 지키려면 재적재 대신 이 경로를 사용한다.)"""
    setup_env(args.corpus)
    require_openai_key()
    from backend.graph import regenerate_project_memory, get_project_memory
    project_id = get_project_id(args.corpus)
    regenerate_project_memory(project_id)
    mem = get_project_memory(project_id) or ""
    print(f"[완료] pmem {args.corpus}: 프로젝트 메모리 {len(mem)}자 생성")


def cmd_state_check(args) -> None:
    """내부용: 현재 DB·Chroma가 기대 상태인지 검증(별도 프로세스에서 실행)."""
    corpus = args.corpus
    setup_env(corpus)
    require_openai_key()
    resolved, expected = resolve_positive_matches(corpus)
    relations, presence = db_state(corpus)
    problems = check_state(relations, expected, presence, args.expect)
    if problems:
        for p in problems:
            print(f"  [상태 위반] {p}")
        sys.exit(1)
    print(f"  [상태 OK] {corpus} = {args.expect}")


# ── 서브커맨드: pairs ────────────────────────────────────────────────────────

def cmd_pairs(args) -> None:
    corpus = args.corpus
    if invalid_marker(corpus).exists():
        sys.exit(f"[중단] {corpus} run이 invalid 봉인 상태 — restore로 해소 필요")

    # 멱등(P1-C): 이미 post 상태면(중단된 dev의 --resume 등) 재적용하지 않는다.
    # pre 검사로 재적용을 강제하면 pairs가 항상 중단돼 resume이 깨진다.
    if subprocess.run(
            [sys.executable, str(HERE / "run_eval.py"), "_state-check",
             "--corpus", corpus, "--expect", "post"]).returncode == 0:
        # 전환 완료 직후 coverage 기록 전에 중단된 재개(R2-005): 이 run의
        # coverage가 없으면 상태 변경 없이 재생성한다(기록은 원자적 — 부분
        # 파일은 존재할 수 없으므로 존재 확인으로 충분).
        cov_path = (RESULTS_DIR /
                    f"pair_coverage_{corpus}_{args.phase}_{args.runid}.csv")
        if not cov_path.exists():
            cov_run = subprocess.run(
                [sys.executable, str(HERE / "run_eval.py"), "_pairs-worker",
                 "--corpus", corpus, "--phase", args.phase,
                 "--runid", args.runid, "--coverage-only"])
            if cov_run.returncode != 0:
                sys.exit(f"[중단] post 상태 coverage 복구 실패({cov_path.name})")
        # 재개 시에도 post 상태 프로젝트 메모리를 보장(C-001) — pairs 이전 캐시가
        # 남아 있으면 대체된 결정이 요약에 계속 노출된다.
        run_step(["pmem", "--corpus", corpus])
        print(f"[건너뜀] pairs {corpus} — 이미 E1(post) 상태(coverage 확인 완료)")
        return

    # 0. 체크포인트: 완성 표식이 없으면 pre-state 검증 통과 시에만 생성,
    #    있으면 현재 상태가 pre인지 검증
    if not checkpoint_ok(corpus).exists():
        run_step(["checkpoint", "--corpus", corpus])
    else:
        check = subprocess.run(
            [sys.executable, str(HERE / "run_eval.py"), "_state-check",
             "--corpus", corpus, "--expect", "pre"])
        if check.returncode != 0:
            sys.exit("[중단] 현재 상태가 pre-pairs가 아님(이전 실행 잔재) — "
                     "restore 후 재시도")

    # 1·2. 검증+적용은 worker subprocess(부모는 Chroma 미개방 — plan 리뷰 3-P1b).
    #       phase·runid를 전달해야 커버리지 CSV가 이 실행에 귀속된다(P1-E).
    worker = subprocess.run(
        [sys.executable, str(HERE / "run_eval.py"), "_pairs-worker",
         "--corpus", corpus, "--phase", args.phase, "--runid", args.runid])
    if worker.returncode != 0:
        # 3. 보상 복구: 부모가 파일 수준 복원 → 새 프로세스로 pre-state 재검증
        print("[보상 복구] pairs 실패 — 체크포인트 복원 시도")
        restore = subprocess.run(
            [sys.executable, str(HERE / "run_eval.py"), "restore",
             "--corpus", corpus])
        if restore.returncode != 0:
            sys.exit("[중단] 복구 실패 — run invalid 봉인됨")
        recheck = subprocess.run(
            [sys.executable, str(HERE / "run_eval.py"), "_state-check",
             "--corpus", corpus, "--expect", "pre"])
        if recheck.returncode != 0:
            invalid_marker(corpus).write_text("복구 후 pre-state 재검증 실패")
            sys.exit("[중단] 복구 후 재검증 실패 — run invalid 봉인")
        sys.exit("[중단] pairs 실패 — pre-pairs 상태로 복구 완료(원인 수정 후 재시도)")

    # 4. post-state 검증
    run_step(["_state-check", "--corpus", corpus, "--expect", "post"])
    # 5. supersede 반영 후 프로젝트 메모리 재생성(C-001) — 실서비스의
    #    refresh_project_memory_after_delete와 동일 취지. E2-e2e가 대체된 결정이
    #    빠진 최신 요약을 컨텍스트로 쓰도록 한다(active_memory 기준 재생성).
    run_step(["pmem", "--corpus", corpus])
    print(f"[완료] pairs {corpus} (E1 상태 전환 + post 검증 + 프로젝트 메모리 갱신)")


def write_pair_coverage(cov_path: Path, resolved: dict, dump: dict) -> dict:
    """커버리지 CSV를 임시 파일 완성 후 교체로 원자적 기록(R2-005 — 부분 파일
    금지). 전역 hook 상태 분포는 pair 판정을 오염시키지 않되, gitignore되는 실행
    로그가 아니라 커밋되는 CSV 자체에 남긴다(R2-004). 분포 dict를 반환."""
    sugg_by_memory: dict[int, list] = {}
    for s in dump["suggestions"]:
        sugg_by_memory.setdefault(s["memory_id"], []).append(s)
    # 훅 상태 분포(전역 관측용) — 특정 pair 판정을 오염시키지 않는 별도 컬럼.
    hook_status: dict[str, int] = {}
    for h in dump["hook_log"]:
        st = h.get("status", "?")
        hook_status[st] = hook_status.get(st, 0) + 1
    hook_note = json.dumps(hook_status, ensure_ascii=False, sort_keys=True)
    tmp = cov_path.with_name(cov_path.name + ".tmp")
    try:
        with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["pair_id", "kind", "old_id", "new_id",
                            "detector_result", "note", "global_hook_status"])
            for pid, value in resolved.items():
                sugg = sugg_by_memory.get(value["old_id"], [])
                supersede_sugg = [s for s in sugg if s.get("kind") == "supersede"]
                # 제안이 실제로 이 pair의 new decision을 target하는지 확인(P2-E):
                # 같은 old를 다른 대상으로 대체 제안한 경우를 hit로 세지 않는다.
                targeted = [s for s in supersede_sugg
                            if _suggestion_target(s) == value["new_id"]]
                if value["kind"] == "negative":
                    result = "false_positive" if supersede_sugg else "correct_reject"
                elif targeted:
                    result = "hit"
                elif supersede_sugg:
                    result = "hit_wrong_target"     # 제안은 있으나 대상 불일치
                else:
                    result = "miss"
                writer.writerow([pid, value["kind"], value["old_id"],
                                 value.get("new_id") or "", result,
                                 f"supersede제안={len(supersede_sugg)} 정타={len(targeted)}",
                                 hook_note])
        os.replace(tmp, cov_path)
    except BaseException:
        # 실패 시 최종 경로는 무손상, tmp 잔재도 남기지 않는다(R3-002 —
        # results/는 추적 디렉터리라 잔재가 커밋 후보로 노출됨).
        tmp.unlink(missing_ok=True)
        raise
    return hook_status


def cmd_pairs_worker(args) -> None:
    """내부용: pair 검증 → 단일 트랜잭션 적용 → 벡터 삭제 → 커버리지 CSV.
    --coverage-only(R2-005)면 상태 변경 없이 커버리지 CSV만 재생성한다."""
    corpus = args.corpus
    setup_env(corpus)
    if getattr(args, "coverage_only", False):
        # DB·Chroma·OpenAI 키 완전 무접촉(R4-001): 적재 시점 덤프의 memory_rows로
        # 매칭한다. 덤프는 ingest마다 재작성되고 행 id·content는 이후 불변
        # (pairs는 superseded_by만 갱신 — rows_as_active 중화로 post 상태 무관)
        # 이라 라이브 DB 조회와 동치다.
        dump = json.loads((STATE_DIR / corpus / "ingest_dump.json").read_text())
        rows_as_active = [dict(r, superseded_by=None) for r in dump["memory_rows"]]
        resolved = match_pairs(load_pairs(), rows_as_active, corpus)
        RESULTS_DIR.mkdir(exist_ok=True)
        cov_path = RESULTS_DIR / f"pair_coverage_{corpus}_{args.phase}_{args.runid}.csv"
        hook_status = write_pair_coverage(cov_path, resolved, dump)
        print(f"  커버리지 복구 → {cov_path.name} (훅 상태 {hook_status})")
        return
    require_openai_key()
    project_id = get_project_id(corpus)
    rows = fetch_memory_rows(project_id)
    pairs = load_pairs()
    resolved = match_pairs(pairs, rows, corpus)   # PairMatchError → 비정상 종료
    positives = {pid: v for pid, v in resolved.items() if v["kind"] == "positive"}

    from backend.db.mysql import get_connection
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            for value in positives.values():
                cur.execute(
                    "UPDATE memory SET superseded_by=%s, superseded_at=NOW()"
                    " WHERE id=%s AND project_id=%s AND superseded_by IS NULL",
                    (value["new_id"], value["old_id"], project_id))
                if cur.rowcount != 1:
                    raise RuntimeError(f"UPDATE 실패: old={value['old_id']}")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    # 승인 경로와 검색 상태 동등(plan 리뷰 2-2): old 벡터 삭제, 실패는 hard failure
    from backend.retriever.memory_vector import delete_memory_vector
    for value in positives.values():
        delete_memory_vector(value["old_id"])
        # 삭제 확인(조용한 실패 방지)
        from backend.db.chroma import get_collection
        from backend.retriever.memory_vector import memory_vector_id
        got = get_collection().get(ids=[memory_vector_id(value["old_id"])])
        if got.get("ids"):
            raise RuntimeError(f"벡터 삭제 실패: memory:{value['old_id']}")

    # 판별기 커버리지(부산물): recorder 덤프 + suggestions vs 골든 pair
    dump = json.loads((STATE_DIR / corpus / "ingest_dump.json").read_text())
    RESULTS_DIR.mkdir(exist_ok=True)
    cov_path = RESULTS_DIR / f"pair_coverage_{corpus}_{args.phase}_{args.runid}.csv"
    hook_status = write_pair_coverage(cov_path, resolved, dump)
    print(f"  커버리지 → {cov_path.name} (훅 상태 {hook_status})")


# ── 서브커맨드: measure ──────────────────────────────────────────────────────

def cmd_measure(args) -> None:
    corpus, config, phase = args.corpus, args.config, args.phase
    runid = args.runid
    judge = args.judge or PHASE_JUDGE[phase]
    if invalid_marker(corpus).exists():
        sys.exit(f"[중단] {corpus} invalid 봉인 상태")
    marker = marker_path(runid, corpus, config, phase)
    if args.resume and marker.exists():
        # judge 불일치면 건너뛰지 않는다(P2-D): 다른 judge로 재측정하려는데 마커
        # 때문에 조용히 옛 결과를 유지하는 것을 막는다. 마커에 judge를 기록해 둠.
        # --overwrite면 건너뛰기가 아니라 재측정으로 진행해야 한다(R2-002).
        prev_judge = marker.read_text().strip()
        if prev_judge and prev_judge != judge:
            if not args.overwrite:
                sys.exit(f"[중단] {marker.name} judge 불일치: 기존 {prev_judge} ↔ "
                         f"요청 {judge}. 같은 키 재측정은 --overwrite 필요(또는 judge 일치)")
            print(f"[재측정] {marker.name} judge 교체: {prev_judge} → {judge} (--overwrite)")
        else:
            print(f"[건너뜀] {marker.name} 완료 마커 존재")
            return
    # 재측정(overwrite)은 측정 시작 전에 기존 게시물을 무효화한다(R6-001) — 이
    # 재측정이 도중 실패해도 옛 부분 평균·마커가 '완료'로 남지 않는다.
    if args.overwrite:
        stale = invalidate_measurement(runid, corpus, config, phase)
        if stale:
            print(f"  [무효화] 재측정 전 기존 게시물 제거: {', '.join(stale)}")
    setup_env(corpus)
    require_openai_key()
    if args.no_langsmith:
        disable_langsmith()
    else:
        enable_langsmith(corpus, config, runid)

    # 구성-상태 정밀 검사(in-process — 이 프로세스는 이 구성 측정 전용)
    resolved, expected = resolve_positive_matches(corpus)
    relations, presence = db_state(corpus)
    problems = check_state(relations, expected, presence,
                           CONFIG_SPEC[config]["state"])
    if problems:
        for p in problems:
            print(f"  [상태 위반] {p}")
        sys.exit(f"[중단] {config}는 {CONFIG_SPEC[config]['state']} 상태 전제 — "
                 "현재 DB 상태와 불일치")

    project_id = get_project_id(corpus)
    questions = [q for q in load_golden() if q["corpus"] == corpus]
    non_hallu = [q for q in questions if q["tag"] != "hallucination"]
    hallu = [q for q in questions if q["tag"] == "hallucination"]
    pairs_by_id = {p["pair_id"]: p for p in load_pairs()}

    rows_out: list[dict] = []
    chain_hits, chain_total = 0, 0
    with config_overrides(config):
        for q in non_hallu:
            collector = get_collector(config, q)
            contexts, debug = collector(project_id, q["question"])
            sql_ctx, vec_ctx = split_contexts(debug)
            row = {"qid": q["qid"], "tag": q["tag"], "question": q["question"],
                   "reference": q["reference"], "contexts": contexts,
                   "n_contexts": len(contexts),
                   "rendered_context": _gen_context(debug, contexts),
                   "source_labels": debug.get("source_labels", []),
                   "sql_contexts": sql_ctx, "vector_contexts": vec_ctx,
                   "history_mode": debug.get("history_mode", ""),
                   "history_rows_added": debug.get("history_rows_added", ""),
                   "history_truncated": debug.get("history_truncated", "")}
            if config.startswith("E2") and q["expected_history_mode"]:
                chain_total += 1
                chain_ctx = chain_source_texts(debug)
                ok = all(chain_included(chain_ctx, pairs_by_id[pid])
                         for pid in q["expected_chain_pairs"])
                row["chain_included"] = ok
                chain_hits += int(ok)
            rows_out.append(row)

        # 환각 기권률 — dev·final 동일 수행(plan 리뷰 3-P2d)
        from backend.retriever import qa_engine
        abstains = 0
        for q in hallu:
            collector = get_collector(config, q)
            contexts, debug = collector(project_id, q["question"])
            # 서비스 렌더링 컨텍스트로 생성(출처 마커 포함, R-001). R0는 렌더링
            # 컨텍스트가 없으므로 수집 원문으로 폴백한다(빈 컨텍스트 생성 방지, C5-002).
            gen_ctx = _gen_context(debug, contexts)
            answer = qa_engine._get_chain().invoke(
                {"history": [], "context": gen_ctx,
                 "question": q["question"]})
            ok = is_abstain(answer)
            abstains += int(ok)
            sql_ctx, vec_ctx = split_contexts(debug)
            rows_out.append({"qid": q["qid"], "tag": q["tag"],
                             "question": q["question"], "response": answer,
                             "abstained": ok, "contexts": contexts,
                             "n_contexts": len(contexts),
                             "rendered_context": gen_ctx,
                             "source_labels": debug.get("source_labels", []),
                             "sql_contexts": sql_ctx, "vector_contexts": vec_ctx})

        # final은 생성 지표를 E0·E2-e2e 한정 추가(전 구성 context 지표는 공통)
        need_generation = phase == "final" and config in ("E0", "E2-e2e")
        if need_generation:
            for row in rows_out:
                if row["tag"] != "hallucination":
                    row["response"] = qa_engine._get_chain().invoke(
                        {"history": [], "context": row.get("rendered_context", ""),
                         "question": row["question"]})
                    # 출처 추적성 — 답변이 실제 검색 출처를 마커로 인용했는지
                    # (환각 문항은 기권이 정답이라 인용 대상 아님, TASK-007)
                    row["citation_grounding"] = citation_grounding(
                        row["response"], row.get("source_labels") or [])

    # RAGAS 채점 (비환각 문항)
    scores = ragas_score(rows_out, judge, need_generation, args.workers)

    # 산출물 기록
    RESULTS_DIR.mkdir(exist_ok=True)
    detail_path = detail_path_for(corpus, config, phase, runid)
    detail_cols = ["qid", "tag", "question", "n_contexts", "context_precision",
                   "context_recall", "faithfulness", "response_relevancy",
                   "citation_grounding",
                   "history_mode", "history_rows_added", "history_truncated",
                   "chain_included", "abstained"]
    with open(detail_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=detail_cols, extrasaction="ignore")
        writer.writeheader()
        for row in rows_out:
            writer.writerow(row)
    # 추적용 전문 스냅샷(로컬 전용, .eval_state는 gitignore): 답변을 채점 후
    # 버리지 않고, SQL 구조화 기록·벡터 원문 청크를 출처 라벨과 함께 분리 저장해
    # LangSmith 없이도 문항별 답변·검색 근거·인용 점수를 오프라인에서 확인한다.
    ctx_path = STATE_DIR / f"contexts_{corpus}_{config}_{phase}_{runid}.jsonl"
    with open(ctx_path, "w", encoding="utf-8") as f:
        for row in rows_out:
            f.write(json.dumps({
                "qid": row["qid"], "tag": row.get("tag"),
                "question": row.get("question"),
                "response": row.get("response", ""),
                "citation_grounding": row.get("citation_grounding", ""),
                "source_labels": row.get("source_labels", []),
                "sql_contexts": row.get("sql_contexts", []),
                "vector_contexts": row.get("vector_contexts", []),
                # 실제 LLM 입력 전문(출처 마커·메타 포함, R0는 원문 join 폴백).
                "rendered_context": row.get("rendered_context", ""),
            }, ensure_ascii=False) + "\n")

    summary_row = {
        "run_id": runid, "date": datetime.now().strftime("%Y-%m-%d"),
        "commit": git_commit(), "corpus": corpus, "config": config,
        "phase": phase, "judge": judge, "n": len(non_hallu),
        "context_precision": scores.get("context_precision", ""),
        "context_recall": scores.get("context_recall", ""),
        "faithfulness": scores.get("faithfulness", ""),
        "response_relevancy": scores.get("response_relevancy", ""),
        "abstain_rate": round(abstains / len(hallu), 3) if hallu else "",
    }
    cited = [r["citation_grounding"] for r in rows_out
             if "citation_grounding" in r]
    if cited:   # 생성 지표를 측정한 구성(final E0·E2-e2e)에서만 채워진다
        summary_row["citation_grounding"] = round(sum(cited) / len(cited), 3)
    if chain_total:
        summary_row["chain_inclusion_rate"] = round(chain_hits / chain_total, 3)
    if config != "E2-oracle":   # 보조 구성은 summary 12행 계약 밖 — 상세 파일만
        SummaryWriter(RESULTS_DIR / "summary.csv").upsert(
            summary_row, overwrite=args.overwrite)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(judge)
    print(f"[완료] measure {corpus}/{config}/{phase}: {scores} "
          f"기권 {abstains}/{len(hallu)}"
          + (f" 체인 {chain_hits}/{chain_total}" if chain_total else ""))


def _install_vertexai_shim() -> None:
    """ragas(0.4.3 실측)가 langchain-community 0.4에서 제거된
    `langchain_community.chat_models.vertexai`를 임포트해 ModuleNotFoundError로
    죽는 문제 우회 — rag_eval.py의 동일 shim을 재사용한 것."""
    name = "langchain_community.chat_models.vertexai"
    if name in sys.modules:
        return
    mod = types.ModuleType(name)
    mod.__spec__ = importlib.machinery.ModuleSpec(name, None)

    class ChatVertexAI:
        def __init__(self, *args, **kwargs):
            raise ImportError("ChatVertexAI is not installed.")

    mod.ChatVertexAI = ChatVertexAI
    sys.modules[name] = mod


def reject_partial_ragas(df, col_map: dict) -> None:
    """실패 job의 NaN이 남은 채 점수가 게시되는 것을 차단(리뷰 R5-001).
    ragas evaluate는 기본 raise_exceptions=False라 재시도 소진·타임아웃이 NaN
    으로 남고, mean(skipna)이 조용히 건너뛰어 일부 문항만의 부분 평균이
    summary·완료 마커로 기록된다. 게시 로직은 ragas_score 반환 이후에 있으므로
    여기서 예외를 던지면 summary·마커·상세 CSV 모두 기록되지 않는다."""
    bad = {}
    for col in df.columns:
        if any(match in col for match in col_map):
            n = int(df[col].isna().sum())
            if n:
                bad[col] = n
    if bad:
        raise RuntimeError(
            f"[중단] ragas 지표에 NaN 잔존 {bad} — 부분 평균 게시 금지. "
            "레이트리밋/타임아웃/판정출력 절단(max_tokens) 의심: 로그의 "
            "예외 종류 확인 후 원인 해소하고 같은 명령으로 재실행")


def ragas_score(rows_out: list[dict], judge: str, with_generation: bool,
                workers: int) -> dict:
    """RAGAS context 지표(+ final의 생성 지표) 평균 점수."""
    _install_vertexai_shim()
    # ragas 텔레메트리 차단(실측 확인): LLM 호출마다 track()이 분석 서버로
    # 블로킹 POST를 보내 호출당 ~6초를 추가한다(0.7s→6.5s). 평가 결과와 무관.
    os.environ.setdefault("RAGAS_DO_NOT_TRACK", "true")
    # AsyncOpenAI 필수(실측 확인): 동기 클라이언트를 주면 ragas 0.4의 async
    # 평가 루프가 호출을 직렬화해 R0류(컨텍스트 다량) 측정이 수 시간으로 늘어남.
    from openai import AsyncOpenAI
    from ragas import EvaluationDataset, evaluate
    from ragas.llms import llm_factory
    from ragas.run_config import RunConfig
    from ragas.metrics import LLMContextPrecisionWithReference, LLMContextRecall

    samples = []
    for row in rows_out:
        if row["tag"] == "hallucination":
            continue
        samples.append({
            "user_input": row["question"],
            "retrieved_contexts": row["contexts"] or [""],
            "response": row.get("response", ""),
            "reference": row["reference"],
        })
    # max_retries 상향(실측 확인): 병렬 judge 호출이 TPM(200K)을 포화시키면
    # 429가 나는데, 기본 재시도(SDK 2회 + instructor 1회)로는 포화 구간을 못
    # 넘겨 해당 문항 점수가 NaN이 된다. SDK 재시도는 Retry-After를 준수하는
    # 백오프라 자체 감속 효과가 있다(대기 중 다른 worker가 budget 소진 → 자연
    # 스로틀링). modu dev 1차에서 R0-sql·R0-both precision NaN으로 실측 확인.
    ragas_llm = llm_factory(judge, client=AsyncOpenAI(max_retries=10),
                            max_tokens=JUDGE_MAX_TOKENS)
    metrics = [LLMContextPrecisionWithReference(llm=ragas_llm),
               LLMContextRecall(llm=ragas_llm)]
    if with_generation:
        from ragas.metrics import Faithfulness, ResponseRelevancy
        from ragas.embeddings import embedding_factory
        emb = embedding_factory(model="text-embedding-3-small")
        metrics += [Faithfulness(llm=ragas_llm),
                    ResponseRelevancy(llm=ragas_llm, embeddings=emb)]
    # timeout 상향(실측 확인): 기본 180s는 TPM 포화 시 Retry-After 백오프 대기
    # 중인 정상 job을 TimeoutError로 죽여 NaN을 만든다(modu dev E0에서 발생).
    result = evaluate(dataset=EvaluationDataset.from_list(samples),
                      metrics=metrics,
                      run_config=RunConfig(max_workers=workers, timeout=600))
    df = result.to_pandas()
    col_map = {"llm_context_precision_with_reference": "context_precision",
               "context_recall": "context_recall",
               "faithfulness": "faithfulness",
               "answer_relevancy": "response_relevancy"}
    reject_partial_ragas(df, col_map)
    scores = {}
    for col in df.columns:
        for match, name in col_map.items():
            if match in col:
                scores[name] = round(float(df[col].mean()), 4)
    # 문항별 점수를 rows_out에 합류(상세 CSV용)
    for row, (_, df_row) in zip(
            [r for r in rows_out if r["tag"] != "hallucination"], df.iterrows()):
        for col in df.columns:
            for match, name in col_map.items():
                if match in col:
                    row[name] = round(float(df_row[col]), 4)
    return scores


# ── 서브커맨드: audit / report ───────────────────────────────────────────────

def cmd_audit(args) -> None:
    corpus, phase, runid = args.corpus, args.phase, args.runid
    setup_env(corpus)
    if args.no_langsmith:
        disable_langsmith()
    questions = [q for q in load_golden() if q["corpus"] == corpus]  # 30문항
    from backend.retriever.query_intent import classify_question

    RESULTS_DIR.mkdir(exist_ok=True)
    audit_path = RESULTS_DIR / f"routing_audit_{corpus}_{phase}_{runid}.csv"
    route_match = 0
    hist_expected = [q for q in questions if q["expected_history_mode"]]
    hist_detected = 0
    with open(audit_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["corpus", "qid", "tag", "question", "expected_route",
                         "actual_route", "router_stage", "expected_history",
                         "actual_history", "route_match", "history_match"])
        for q in questions:
            decision = classify_question(q["question"])
            r_ok = decision.route == q["expected_route"]
            h_ok = decision.history_mode == q["expected_history_mode"]
            route_match += int(r_ok)
            if q["expected_history_mode"] and decision.history_mode:
                hist_detected += 1
            writer.writerow([corpus, q["qid"], q["tag"], q["question"],
                             q["expected_route"], decision.route,
                             decision.router_stage, q["expected_history_mode"],
                             decision.history_mode, r_ok, h_ok])
    routing_accuracy = round(route_match / len(questions), 3)
    detect_rate = (round(hist_detected / len(hist_expected), 3)
                   if hist_expected else "")
    # summary의 해당 코퍼스 행들에 병합(upsert)
    writer_obj = SummaryWriter(RESULTS_DIR / "summary.csv")
    for config in MAIN_CONFIGS:
        writer_obj.upsert({
            "run_id": runid, "corpus": corpus, "config": config, "phase": phase,
            "routing_accuracy": routing_accuracy,
            "history_detect_rate": detect_rate,
        })
    print(f"[완료] audit {corpus}: 라우팅 정확도 {routing_accuracy}, "
          f"이력 감지율 {detect_rate} → {audit_path.name}")


def cmd_report(args) -> None:
    path = RESULTS_DIR / "summary.csv"
    if not path.exists():
        sys.exit("[중단] summary.csv 없음")
    rows = SummaryWriter(path)._load()
    # run_id 필터(P2-C): 지정 없으면 가장 최근 run_id로 한정한다. 여러 run이
    # summary에 누적됐을 때 서로 다른 실행의 수치가 한 표에 섞이지 않게 한다.
    runid = getattr(args, "runid", None)
    if not runid:
        runid = max((r["run_id"] for r in rows), default=None)
    if runid:
        rows = [r for r in rows if r["run_id"] == runid]
        print(f"\n# 골든셋 평가 리포트 (run_id={runid})")
    phases = sorted({r["phase"] for r in rows})
    for phase in phases:
        print(f"\n## phase={phase}\n")
        print("| corpus | config | judge | ctx_precision | ctx_recall | "
              "faithfulness | citation | routing_acc | hist_detect | chain_incl "
              "| abstain |")
        print("|---|---|---|---|---|---|---|---|---|---|---|")
        for corpus in CORPORA:
            for config in MAIN_CONFIGS:
                match = [r for r in rows if r["phase"] == phase
                         and r["corpus"] == corpus and r["config"] == config]
                if not match:
                    continue
                r = match[-1]
                print(f"| {corpus} | {config} | {r['judge']} "
                      f"| {r['context_precision']} | {r['context_recall']} "
                      f"| {r['faithfulness']} | {r.get('citation_grounding', '')} "
                      f"| {r['routing_accuracy']} "
                      f"| {r['history_detect_rate']} | {r['chain_inclusion_rate']} "
                      f"| {r['abstain_rate']} |")


# ── 서브커맨드: methods (Materials & Methods 기록) ───────────────────────────

# 재현·인용에 필요한 as-run 사실을 기록. 설계 *의도*는 EVAL_DESIGN.md가 담으므로
# 여기서는 실행 시점에만 알 수 있는 값(버전·모델·추출 행수·표본 크기)에 집중한다.
_METHODS_PKGS = ["ragas", "datasets", "pandas", "langchain-core",
                 "langchain-openai", "langgraph", "openai", "chromadb",
                 "kiwipiepy", "PyMySQL"]


def _pkg_versions() -> dict[str, str]:
    out = {}
    for name in _METHODS_PKGS:
        try:
            out[name] = importlib.metadata.version(name)
        except Exception:
            out[name] = "미설치"
    return out


def _git_describe() -> str:
    commit = git_commit()
    try:
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=REPO,
                               capture_output=True, text=True).stdout.strip()
    except Exception:
        dirty = ""
    return commit + (" (dirty)" if dirty else "")


def _ingest_summary(corpus: str) -> dict | None:
    """적재 덤프에서 as-run 수치를 읽는다(DB 불필요). 미적재면 None."""
    path = STATE_DIR / corpus / "ingest_dump.json"
    if not path.exists():
        return None
    dump = json.loads(path.read_text())
    hook: dict[str, int] = {}
    for h in dump.get("hook_log", []):
        status = h.get("status", "?")
        hook[status] = hook.get(status, 0) + 1
    return {"project_id": dump.get("project_id"),
            "memory_rows": len(dump.get("memory_rows", [])),
            "suggestions": len(dump.get("suggestions", [])),
            "hook": hook}


def _asrun_judges(runid: str) -> dict[str, set]:
    """summary.csv에서 이 run이 실제 기록한 judge를 phase별로 수집(P2-B).
    --judge override나 부분 재측정을 반영해 as-run 문서가 실제와 어긋나지 않게 한다."""
    path = RESULTS_DIR / "summary.csv"
    out: dict[str, set] = {}
    if path.exists():
        for r in SummaryWriter(path)._load():
            if r.get("run_id") == runid and r.get("judge"):
                out.setdefault(r.get("phase", "?"), set()).add(r["judge"])
    return out


def render_methods(runid: str, phase: str) -> str:
    """DB·OPENAI 키 없이도 렌더 가능(골든 파일 + 적재 덤프 + 패키지 버전)."""
    questions = load_golden()
    pairs = load_pairs()
    L: list[str] = []
    L.append("# Materials & Methods — 골든셋 계층 4 평가 (as-run)")
    L.append("")
    L.append(f"- 기록 시각: {datetime.now().isoformat(timespec='seconds')}")
    L.append(f"- run_id: `{runid}` / 측정 phase: `{phase}`")
    L.append(f"- git commit: `{_git_describe()}`")
    L.append(f"- Python: {platform.python_version()} / {platform.platform()}")
    L.append("- 설계 근거(의도)는 `EVAL_DESIGN.md`, 결과 해석은 "
             "`docs/EVAL_REPORT.md` 참조. 이 문서는 *실제로 어떻게 돌렸는가*만 담는다.")
    L.append("")

    L.append("## 1. 소프트웨어 환경 (재현용 버전)")
    L.append("")
    L.append("| 패키지 | 버전 |")
    L.append("|---|---|")
    for name, ver in _pkg_versions().items():
        L.append(f"| {name} | {ver} |")
    L.append("")

    L.append("## 2. 모델 (as-run)")
    L.append("")
    asrun = _asrun_judges(runid)
    search_embed = os.environ.get("EMBED_MODEL", "text-embedding-3-small")
    L.append("| 역할 | 모델 | 비고 |")
    L.append("|---|---|---|")
    for ph in ("dev", "final"):
        used = asrun.get(ph)
        model = ", ".join(sorted(used)) if used else PHASE_JUDGE[ph]
        note = "summary 실측" if used else "기본값(이 run 미측정)"
        L.append(f"| RAGAS judge ({ph}) | {model} | {note} |")
    L.append(f"| 검색·chroma 임베딩 | {search_embed} | EMBED_MODEL 환경변수 반영 |")
    L.append("| ResponseRelevancy 임베딩 | text-embedding-3-small | ragas 채점 고정 |")
    L.append("| 추출·답변 생성 | 백엔드 서비스 설정에 따름 | qa_engine/extractor 재사용 |")
    L.append("")

    L.append("## 3. 재료 (Materials) — 코퍼스·표본")
    L.append("")
    L.append("| 코퍼스 | 회의록(md) | 추출 memory행 | 제안 | 비환각 | 환각 | "
             "이력(history) | conflict_negative |")
    L.append("|---|---|---|---|---|---|---|---|")
    for corpus, spec in CORPORA.items():
        cq = [q for q in questions if q["corpus"] == corpus]
        n_md = len(sorted((HERE / spec["dir"]).glob("*.md")))
        n_nonhallu = sum(1 for q in cq if q["tag"] != "hallucination")
        n_hallu = sum(1 for q in cq if q["tag"] == "hallucination")
        n_hist = sum(1 for q in cq if q["expected_history_mode"])
        n_confneg = sum(1 for q in cq if q["tag"] == "conflict_negative")
        ing = _ingest_summary(corpus)
        rows = ing["memory_rows"] if ing else "미적재"
        sugg = ing["suggestions"] if ing else "-"
        L.append(f"| {corpus} | {n_md} | {rows} | {sugg} | {n_nonhallu} | "
                 f"{n_hallu} | {n_hist} | {n_confneg} |")
    L.append("")
    L.append("- 표본 크기(비환각/환각/history/conflict_negative)는 골든셋 라벨 "
             "확정본(`routing_expected.json` + QA JSON)에서 집계한 값이다.")
    for corpus in CORPORA:
        ing = _ingest_summary(corpus)
        if ing and ing["hook"]:
            L.append(f"- {corpus} supersede 훅 로그: {ing['hook']} "
                     "(detect_supersede 호출/무결정/오류 분포)")
    L.append("")

    L.append("## 4. 골든 supersede pair (계층 4 정답 관계)")
    L.append("")
    L.append("| pair_id | corpus | kind | old 앵커 | new 앵커 |")
    L.append("|---|---|---|---|---|")
    for p in pairs:
        L.append(f"| {p['pair_id']} | {p['corpus']} | {p['kind']} | "
                 f"`{p.get('old_match','')}` | `{p.get('new_match') or '—'}` |")
    L.append("")
    L.append("- positive는 `superseded_by` 설정 + 구 벡터 삭제(승인 경로와 검색 "
             "상태 동등)로 적용, negative는 old 존재만 검증하고 적용 제외.")
    L.append("")

    L.append("## 5. 방법 (Methods)")
    L.append("")
    L.append(f"- 구성 매트릭스: {' → '.join(MAIN_CONFIGS)} (+ 보조 {AUX_CONFIGS[0]}). "
             "선형 비교는 R0-both→E0→E1→E2-e2e.")
    L.append("- recency 가중(구성별): "
             + ", ".join(f"{c}={CONFIG_SPEC[c]['recency']}" for c in MAIN_CONFIGS)
             + ".")
    L.append("- 측정 5축: RAGAS context_precision/recall(비환각), 라우팅 감사"
             "(classify_question 직접 호출), 체인 포함률(기대 pair 문구 포함), "
             "환각 기권률(패턴 매칭), 출처 추적성(citation_grounding — final "
             "E0·E2-e2e, 서비스 렌더링 컨텍스트로 생성한 답변의 출처 마커 인용).")
    L.append("- 상태 모델: 적재 1회 → checkpoint(pre-pairs) → [R0×3·E0] → pairs "
             "→ [E1·E2] → audit. 구성마다 pre/post 상태 정밀 검사 후 측정.")
    L.append(f"- 결정론: 측정 병렬성 workers 기본 {WORKERS_DEFAULT}, summary 키 "
             "(run_id,corpus,config,phase)로 dev/final 분리 기록.")
    L.append(f"- judge 호출: max_tokens={JUDGE_MAX_TOKENS}(ragas 기본 1024는 "
             "E0 faithfulness 진술 분해 출력이 잘려 NaN 유발), max_retries=10, "
             "RunConfig timeout=600s.")
    L.append("")

    L.append("## 6. 실행 커맨드 (이 run 재현)")
    L.append("")
    L.append("```bash")
    L.append(f"RUNID={runid}")
    for corpus in CORPORA:
        L.append(f".venv/bin/python backend/test/golden/run_eval.py all "
                 f"--corpus {corpus} --phase {phase} --runid $RUNID")
    L.append("```")
    L.append("")
    return "\n".join(L)


def cmd_methods(args) -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"METHODS_{args.runid}.md"
    out.write_text(render_methods(args.runid, args.phase), encoding="utf-8")
    print(f"[완료] methods → {_rel(out)}")


# ── 서브커맨드: all ──────────────────────────────────────────────────────────

def cmd_all(args) -> None:
    corpus, phase, runid = args.corpus, args.phase, args.runid
    common = ["--runid", runid, "--phase", phase]
    if args.no_langsmith:
        common.append("--no-langsmith")
    resume = ["--resume"] if args.resume else []
    log_path = run_log_path(corpus, phase, runid)

    # tee_output: 이 실행의 부모+자식 출력 전체를 실행 로그로 남긴다(as-run trace).
    with tee_output(log_path):
        print(f"### all 시작: corpus={corpus} phase={phase} runid={runid}")

        if not (STATE_DIR / "db-ready").exists():
            run_step(["db-up"])
        if not (STATE_DIR / corpus / "project_id").exists():
            run_step(["ingest", "--corpus", corpus])
            run_step(["checkpoint", "--corpus", corpus])
        if phase == "final":
            # final 순서(plan 리뷰 3): restore(pre) → pre 구성 → pairs 재적용 → post
            run_step(["restore", "--corpus", corpus])

        for config in ("R0-sql", "R0-vec", "R0-both", "E0"):
            print(f"### 측정: {config}")
            run_step(["measure", "--corpus", corpus, "--config", config,
                      *common, *resume])
        print("### pairs 적용(E1 전환)")
        run_step(["pairs", "--corpus", corpus, "--runid", runid, "--phase", phase])
        for config in ("E1", "E2-e2e", "E2-oracle"):
            print(f"### 측정: {config}")
            run_step(["measure", "--corpus", corpus, "--config", config,
                      *common, *resume])
        print("### 라우팅 감사")
        run_step(["audit", "--corpus", corpus, *common])
        run_step(["report", "--runid", runid])
        # Materials & Methods 기록(as-run 방법론) — DB·키 불필요
        run_step(["methods", "--phase", phase, "--runid", runid])
        print(f"[완료] all {corpus}/{phase} (runid={runid})")
        print(f"  실행 로그 → {_rel(log_path)}")


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add(name, fn, corpus=False, phase=False, runid=False, extra=None):
        p = sub.add_parser(name)
        if corpus:
            p.add_argument("--corpus", choices=list(CORPORA), required=True)
        if phase:
            p.add_argument("--phase", choices=["dev", "final"], default="dev")
        if runid:
            p.add_argument("--runid", default=default_runid())
        if extra:
            extra(p)
        p.set_defaults(fn=fn)
        return p

    add("db-up", cmd_db_up)
    add("db-down", cmd_db_down)
    add("ingest", cmd_ingest, corpus=True,
        extra=lambda p: p.add_argument("--force", action="store_true"))
    add("checkpoint", cmd_checkpoint, corpus=True)
    add("restore", cmd_restore, corpus=True)
    add("pmem", cmd_pmem, corpus=True)
    add("_state-check", cmd_state_check, corpus=True,
        extra=lambda p: p.add_argument("--expect", choices=["pre", "post"],
                                       required=True))
    add("pairs", cmd_pairs, corpus=True, phase=True, runid=True)
    add("_pairs-worker", cmd_pairs_worker, corpus=True, phase=True, runid=True,
        extra=lambda p: p.add_argument("--coverage-only", action="store_true"))
    add("measure", cmd_measure, corpus=True, phase=True, runid=True,
        extra=lambda p: (
            p.add_argument("--config", choices=MAIN_CONFIGS + AUX_CONFIGS,
                           required=True),
            p.add_argument("--judge", default=None),
            p.add_argument("--workers", type=int, default=WORKERS_DEFAULT),
            p.add_argument("--no-langsmith", action="store_true"),
            p.add_argument("--resume", action="store_true"),
            p.add_argument("--overwrite", action="store_true")))
    add("audit", cmd_audit, corpus=True, phase=True, runid=True,
        extra=lambda p: p.add_argument("--no-langsmith", action="store_true"))
    add("report", cmd_report,
        extra=lambda p: p.add_argument("--runid", default=None))
    add("methods", cmd_methods, phase=True, runid=True)
    add("all", cmd_all, corpus=True, phase=True, runid=True,
        extra=lambda p: (
            p.add_argument("--no-langsmith", action="store_true"),
            p.add_argument("--resume", action="store_true")))

    args = parser.parse_args()
    setup_env(getattr(args, "corpus", None))
    args.fn(args)


if __name__ == "__main__":
    sys.path.insert(0, str(REPO))
    main()
