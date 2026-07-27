#!/usr/bin/env python3
"""새 tool-calling 오케스트레이터(agentic_graph.py)용 RAGAS 반복 측정 파이프라인.

run_eval.py(레거시 그래프의 R0/E0/E1/E2 recency-config 매트릭스 전용)는 agentic_graph를
보지 못한다 — 그쪽을 억지로 확장하는 대신, 골든 로더·RAGAS 채점기(load_golden/ragas_score,
수정 없이 재사용)만 가져오고 컨텍스트 수집만 에이전틱 그래프 실행으로 새로 구현했다.

전제 조건(run_eval.py와 동일): `db-up`/`ingest`/`checkpoint`로 코퍼스별 eval DB가
이미 적재돼 있어야 한다(README.md 참고). OPENAI_API_KEY 필요.

collect와 score를 분리한 이유: 에이전틱 실행(멀티턴 tool-calling, LLM 호출 다수)이
전체 소요 시간의 대부분을 차지하고 judge를 바꾸거나 채점만 다시 하고 싶을 때 이걸
반복하는 건 낭비다. collect가 만든 jsonl을 score가 재사용하면 재채점은 judge 호출만
다시 하면 된다.

사용법(리포 루트에서):
    python -m backend.test.golden.run_eval_agentic collect --corpus modu
    python -m backend.test.golden.run_eval_agentic score --in backend/test/golden/.eval_state/agentic_modu.jsonl
    python -m backend.test.golden.run_eval_agentic run --corpus modu   # collect + score
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .run_eval import (
    HERE,
    STATE_DIR,
    PHASE_JUDGE,
    WORKERS_DEFAULT,
    get_project_id,
    load_golden,
    ragas_score,
    require_openai_key,
    setup_env,
)


class _ContextRecorder:
    """에이전틱 실행 중 실제로 검색된 SQL 행·원문 청크를 행 단위 원문으로 수집.

    run_agentic_qa()의 반환 debug는 여러 도구 호출 중 마지막 것만 남기므로
    (agentic_graph._collect_result가 누적하지 않고 덮어씀) 거기서 재구성할 수
    없다 — qa_engine의 공통 저수준 함수를 감싸 호출마다 가로챈다.
    _row_line_body는 _format_mysql_row/_format_history_row가 공유하는 공통
    함수라 search_project_evidence·query_structured_memory 양쪽의 SQL 행을
    다 잡는다. _build_context는 search_project_evidence 경로에서만 원문 청크
    (chroma_chunks[].text_full)를 만든다. get_project_overview 도구는 별도
    조회 경로(query_intent._fetch_overview_context)라 qa_tools에 바인딩된
    이름을 직접 감싼다(qa_tools.py가 `from .query_intent import
    _fetch_overview_context`로 함수 자체를 복사해 와서, query_intent 모듈
    쪽을 패치해봐야 그 복사본엔 반영 안 됨 — 실측으로 발견: A1 "핵심 콘셉트가
    무엇인가" 질문이 overview 도구로만 답해져 컨텍스트 0개로 잡혔었음). 같은 이유로
    `get_project_memory`(search_project_evidence가 "[프로젝트 메모리]" 블록으로
    LLM에 넘기는 프로젝트 요약)도 `qa_tools.py`가 `from ..graph import
    get_project_memory`로 직접 복사해 와서 qa_tools 쪽 바인딩을 감싼다(블라인드
    코드 리뷰로 발견 — 이걸 안 잡으면 프로젝트 요약을 근거로 한 답변이 faithfulness
    채점에서 "근거 없음"으로 오판된다).

    두 종류의 컨텍스트 목록을 따로 모은다:
    - contexts: 메타(담당·날짜·마감·완료상태·이유)·출처 마커를 뺀 순수 원문.
      run_eval.py의 기존 관례와 맞춘 참고용 — 아래 이유로 정본이 아니다.
    - rendered_contexts: 실제 LLM이 답변을 생성할 때 읽은 것과 같은 완성 라인
      (메타·이유·출처 포함). **네 지표 모두 이쪽이 정본이다.**

    처음에는 contexts를 precision/recall 정본으로 썼으나 실측으로 뒤집혔다. 검색이
    실제로 꺼내오는 단위는 렌더링된 라인이지 content 문자열이 아닌데, content만 주면
    판정기가 볼 수 없는 필드가 정답인 질문에서 정답 행조차 무관 판정을 받는다:
      - "Flutter를 선택한 이유는?" → content는 "앱 개발 프레임워크를 Flutter로
        확정한다."뿐이고 정답인 reason 필드("iOS/Android 동시 개발로 일정 단축…")는
        rendered에만 있다(modu A2/A3/A4/A6).
      - "SDK 연동은 누가 담당했는가?" → 정답인 owner 필드가 rendered에만 있다(C1).
    같은 이유로 faithfulness도 실제보다 낮게 나왔었다(qid C6/A10 사례).
    26문항 실측: SQL 축 precision이 content 기준 0.47/0.43 → rendered 기준
    0.68/0.60(modu/CS-Bot)으로, 검색을 바꾸지 않아도 이만큼 차이가 났다.

    contexts를 출처별로도 나눠 sql_contexts(MySQL 구조화 기록 — SQL 행, 프로젝트
    조망 요약·집계, 프로젝트 메모리 요약)/vector_contexts(Chroma 원문 청크)에 같이
    담는다 — PM 분석 보고서(SQL_CONTEXT_RETRIEVAL_PRECISION_REPORT, P0 측정 분리
    권고)가 지적한 대로, 통합 context_precision만으로는 SQL 축과 vector 축 중
    어느 쪽이 노이즈의 원인인지 구분할 수 없기 때문이다.
    """

    def __init__(self):
        self.contexts: list[str] = []
        self.rendered_contexts: list[str] = []
        self.sql_contexts: list[str] = []
        self.vector_contexts: list[str] = []
        # 축별 목록도 rendered 기준으로 함께 모은다 — 순수 content 기준으로만 나누면
        # 담당·이유·날짜가 답인 질문("누가 담당?", "왜 그렇게 정했나?")에서 정답 행조차
        # 무관 판정을 받아 SQL 축 점수가 실제보다 낮게 나온다(아래 클래스 주석 참고).
        self.sql_rendered_contexts: list[str] = []
        self.vector_rendered_contexts: list[str] = []

    def __enter__(self):
        from backend.retriever import qa_engine, qa_tools
        self._qa = qa_engine
        self._qa_tools = qa_tools
        self._orig_row_line_body = qa_engine._row_line_body
        self._orig_build_context = qa_engine._build_context
        self._orig_fetch_overview = qa_tools._fetch_overview_context
        self._orig_get_project_memory = qa_tools.get_project_memory

        def get_project_memory(project_id):
            memory = self._orig_get_project_memory(project_id)
            if memory:
                self.contexts.append(memory)
                self.rendered_contexts.append(memory)
                self.sql_contexts.append(memory)  # project_memory 테이블 기반 요약 — MySQL 출처
                self.sql_rendered_contexts.append(memory)
            return memory

        def row_line_body(r):
            content = r.get("content")
            if content:
                self.contexts.append(content)
                self.sql_contexts.append(content)
            rendered = self._orig_row_line_body(r)
            self.rendered_contexts.append(rendered)
            self.sql_rendered_contexts.append(rendered)
            return rendered

        def build_context(*args, **kwargs):
            context, sources, debug = self._orig_build_context(*args, **kwargs)
            chunk_texts = [c["text_full"] for c in debug.get("chroma_chunks", []) if c.get("text_full")]
            self.contexts.extend(chunk_texts)
            self.rendered_contexts.extend(chunk_texts)  # 문서 청크는 메타 개념이 없어 원문 그대로 공유
            self.vector_contexts.extend(chunk_texts)
            self.vector_rendered_contexts.extend(chunk_texts)
            return context, sources, debug

        def fetch_overview_context(*args, **kwargs):
            import json as _json
            overview = self._orig_fetch_overview(*args, **kwargs)
            if overview.get("overview_summary"):
                self.contexts.append(overview["overview_summary"])
                self.rendered_contexts.append(overview["overview_summary"])
                self.sql_contexts.append(overview["overview_summary"])
                self.sql_rendered_contexts.append(overview["overview_summary"])
            action_plan = overview.get("action_plan") or {}
            # get_project_overview는 category_stats/action_plan.total/status_counts까지
            # 통째로 JSON에 넣어 LLM에 준다(qa_tools.get_project_overview 참고) — 시스템
            # 프롬프트가 이 집계 숫자를 "권위 있는 근거"로 쓰라고 명시하므로 답변이 이걸
            # 인용하면 채점용 컨텍스트에도 있어야 faithfulness가 정확히 나온다.
            stats_blob = _json.dumps({
                "category_stats": overview.get("category_stats"),
                "action_plan_total": action_plan.get("total"),
                "action_plan_status_counts": action_plan.get("status_counts"),
            }, ensure_ascii=False, default=str)
            self.contexts.append(stats_blob)
            self.rendered_contexts.append(stats_blob)
            self.sql_contexts.append(stats_blob)
            self.sql_rendered_contexts.append(stats_blob)
            for row in action_plan.get("items") or []:
                content = row.get("content")
                if content:
                    self.contexts.append(content)
                    self.sql_contexts.append(content)
                    # overview 도구는 LLM에게 행 dict를 JSON 그대로 넘긴다(get_project_overview
                    # 참고) — owner/date/completion_status가 실제로 거기 다 들어있다.
                    rendered_row = _json.dumps(row, ensure_ascii=False, default=str)
                    self.rendered_contexts.append(rendered_row)
                    self.sql_rendered_contexts.append(rendered_row)
            return overview

        qa_engine._row_line_body = row_line_body
        qa_engine._build_context = build_context
        qa_tools._fetch_overview_context = fetch_overview_context
        qa_tools.get_project_memory = get_project_memory
        return self

    def __exit__(self, *exc):
        self._qa._row_line_body = self._orig_row_line_body
        self._qa._build_context = self._orig_build_context
        self._qa_tools._fetch_overview_context = self._orig_fetch_overview
        self._qa_tools.get_project_memory = self._orig_get_project_memory
        return False

    @staticmethod
    def _dedupe(items: list[str]) -> list[str]:
        """중복 제거(멀티쿼리 재검색이 같은 행을 여러 라운드에 다시 뽑을 수 있음), 등장 순서 유지."""
        seen: set[str] = set()
        out = []
        for text in items:
            if text not in seen:
                seen.add(text)
                out.append(text)
        return out

    def collected(self) -> list[str]:
        return self._dedupe(self.contexts)

    def collected_rendered(self) -> list[str]:
        return self._dedupe(self.rendered_contexts)

    def collected_sql(self) -> list[str]:
        return self._dedupe(self.sql_contexts)

    def collected_vector(self) -> list[str]:
        return self._dedupe(self.vector_contexts)

    def collected_sql_rendered(self) -> list[str]:
        return self._dedupe(self.sql_rendered_contexts)

    def collected_vector_rendered(self) -> list[str]:
        return self._dedupe(self.vector_rendered_contexts)


def _default_jsonl_path(corpus: str) -> Path:
    # .eval_state는 gitignore 대상(run_eval.py의 로컬 전용 산출물과 동일 관례) —
    # 원문 컨텍스트·답변 전문 덤프라 커밋 대상인 results/*.csv와는 성격이 다르다.
    return STATE_DIR / f"agentic_{corpus}.jsonl"


def cmd_collect(args) -> None:
    from backend.agentic_graph import run_agentic_qa

    require_openai_key()
    project_id = get_project_id(args.corpus)
    questions = [q for q in load_golden(HERE) if q["corpus"] == args.corpus
                 and q["tag"] != "hallucination"]
    if args.limit:
        questions = questions[:args.limit]

    out_path = Path(args.out) if args.out else _default_jsonl_path(args.corpus)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for i, q in enumerate(questions, 1):
            with _ContextRecorder() as recorder:
                result = run_agentic_qa(project_id, q["question"])
            sql_ctx = recorder.collected_sql()
            vector_ctx = recorder.collected_vector()
            row = {
                "qid": q["qid"], "tag": q["tag"], "question": q["question"],
                "reference": q["reference"], "response": result["answer"],
                "contexts": recorder.collected(),
                "rendered_contexts": recorder.collected_rendered(),
                "sql_contexts": sql_ctx,
                "vector_contexts": vector_ctx,
                "sql_rendered_contexts": recorder.collected_sql_rendered(),
                "vector_rendered_contexts": recorder.collected_vector_rendered(),
                "n_sql_contexts": len(sql_ctx),
                "n_vector_contexts": len(vector_ctx),
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(f"[{i}/{len(questions)}] {q['qid']} 컨텍스트 {len(row['contexts'])}개 수집 "
                  f"(SQL {len(sql_ctx)} / vector {len(vector_ctx)})")
    print(f"[완료] collect {args.corpus}: {len(questions)}문항 -> {out_path}")


def _load_rows(path: Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def cmd_score(args) -> None:
    """네 지표 모두 rendered_contexts(메타 포함, 실제 LLM이 본 것과 동일) 기준이 정본이고,
    순수 content 기준 점수는 비교용으로 나란히 남긴다 — 검색이 실제로 꺼내오는 단위는
    렌더링된 라인이라, content만으로 채점하면 담당·이유·날짜가 정답인 질문에서 정답 행조차
    무관 판정을 받는다(_ContextRecorder 주석의 A2/C1 사례). faithfulness도 같은 이유로
    낮게 나왔었다(qid C6/A10 실측).

    SQL_CONTEXT_RETRIEVAL_PRECISION_REPORT(PM 분석, P0 측정 분리 권고)에 따라
    sql_contexts/vector_contexts로도 각각 precision/recall을 채점한다 — 통합
    context_precision만으로는 SQL 축(구조화 기록)과 vector 축(원문 청크) 중
    어느 쪽이 노이즈의 원인인지 구분할 수 없기 때문이다.

    ragas_score는 run_eval.py의 공용 함수라 여기서 여러 번 호출해 필요한 지표만
    골라 쓰고, 그 함수 자체는 손대지 않는다."""
    require_openai_key()
    in_path = Path(args.input)
    rows = _load_rows(in_path)
    for row in rows:
        row.setdefault("tag", "qa")

    scores = ragas_score(rows, args.judge, True, args.workers)
    print(f"[완료] score(순수 content 기준 — 비교용, 정본 아님) {in_path.name}: {scores}")

    # 키 존재 여부로 판별한다(아래 sql_contexts 분기와 같은 규칙). truthiness로 보면
    # 검색 근거가 없는 문항 하나만 rendered_contexts=[]여도 파일 전체가 구버전으로
    # 간주돼 rendered 기준 재채점이 통째로, 그것도 조용히 생략된다. 빈 목록은 신버전의
    # 유효한 값이다.
    has_rendered = all(row.get("rendered_contexts") is not None for row in rows)
    if has_rendered:
        rendered_rows = [dict(row, contexts=row["rendered_contexts"]) for row in rows]
        rendered_scores = ragas_score(rendered_rows, args.judge, True, args.workers)
        for row, rendered_row in zip(rows, rendered_rows):
            row["faithfulness_rendered"] = rendered_row.get("faithfulness")
            row["response_relevancy_rendered"] = rendered_row.get("response_relevancy")
            row["context_precision_rendered"] = rendered_row.get("context_precision")
            row["context_recall_rendered"] = rendered_row.get("context_recall")
            row["answer_correctness_rendered"] = rendered_row.get("answer_correctness")
        print(f"[완료] score(메타 포함 rendered_contexts 기준 — 네 지표 모두 이 값이 정본): "
              f"{rendered_scores}")
    else:
        print("[안내] rendered_contexts 없음(구버전 jsonl) — faithfulness 비교 재채점 생략")

    has_split = all(row.get("sql_contexts") is not None for row in rows)
    if has_split:
        # 축별 채점도 rendered 기준을 우선 쓴다 — 순수 content 기준으로 나누면 담당·이유가
        # 답인 질문에서 정답 행조차 무관 판정을 받아 SQL 축만 부당하게 낮게 나온다.
        # 구버전 jsonl에는 rendered 축별 목록이 없으므로 그때만 content 기준으로 내려간다.
        sql_field = ("sql_rendered_contexts"
                     if all(row.get("sql_rendered_contexts") is not None for row in rows)
                     else "sql_contexts")
        vector_field = ("vector_rendered_contexts"
                        if all(row.get("vector_rendered_contexts") is not None for row in rows)
                        else "vector_contexts")
        print(f"[안내] 축별 채점 기준: SQL={sql_field}, vector={vector_field}")
        sql_rows = [dict(row, contexts=row[sql_field]) for row in rows]
        sql_scores = ragas_score(sql_rows, args.judge, False, args.workers)
        vector_rows = [dict(row, contexts=row[vector_field]) for row in rows]
        vector_scores = ragas_score(vector_rows, args.judge, False, args.workers)
        for row, sql_row, vector_row in zip(rows, sql_rows, vector_rows):
            row["sql_context_precision"] = sql_row.get("context_precision")
            row["sql_context_recall"] = sql_row.get("context_recall")
            row["vector_context_precision"] = vector_row.get("context_precision")
            row["vector_context_recall"] = vector_row.get("context_recall")
        print(f"[완료] score(SQL-only): {sql_scores}")
        print(f"[완료] score(vector-only): {vector_scores}")
    else:
        print("[안내] sql_contexts/vector_contexts 없음(구버전 jsonl) — SQL/vector 분리 채점 생략")

    detail_path = in_path.with_suffix(".scored.csv")
    import csv
    cols = ["qid", "question", "context_precision", "context_recall",
            "faithfulness", "response_relevancy", "answer_correctness"]
    if has_rendered:
        cols += ["faithfulness_rendered", "response_relevancy_rendered",
                 "context_precision_rendered", "context_recall_rendered",
                 "answer_correctness_rendered"]
    if has_split:
        cols += ["n_sql_contexts", "n_vector_contexts",
                  "sql_context_precision", "sql_context_recall",
                  "vector_context_precision", "vector_context_recall"]
    with open(detail_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"[상세] {detail_path}")


def cmd_run(args) -> None:
    cmd_collect(args)
    args.input = str(Path(args.out) if args.out else _default_jsonl_path(args.corpus))
    cmd_score(args)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    collect_p = sub.add_parser("collect", help="골든 문항을 에이전틱 그래프로 실행해 컨텍스트·답변을 jsonl로 저장")
    collect_p.add_argument("--corpus", choices=["modu", "csbot"], required=True)
    collect_p.add_argument("--limit", type=int, default=None, help="빠른 점검용 문항 수 제한")
    collect_p.add_argument("--out", default=None, help="기본: .eval_state/agentic_<corpus>.jsonl")
    collect_p.set_defaults(fn=cmd_collect)

    score_p = sub.add_parser("score", help="jsonl을 RAGAS로 채점(에이전틱 실행 재수행 없음)")
    score_p.add_argument("--in", dest="input", required=True)
    score_p.add_argument("--judge", default=PHASE_JUDGE["dev"])
    score_p.add_argument("--workers", type=int, default=WORKERS_DEFAULT)
    score_p.set_defaults(fn=cmd_score)

    run_p = sub.add_parser("run", help="collect + score 한 번에")
    run_p.add_argument("--corpus", choices=["modu", "csbot"], required=True)
    run_p.add_argument("--limit", type=int, default=None)
    run_p.add_argument("--out", default=None)
    run_p.add_argument("--judge", default=PHASE_JUDGE["dev"])
    run_p.add_argument("--workers", type=int, default=WORKERS_DEFAULT)
    run_p.set_defaults(fn=cmd_run)

    args = parser.parse_args()
    setup_env(getattr(args, "corpus", None))
    args.fn(args)


if __name__ == "__main__":
    sys.path.insert(0, str(HERE.parents[2]))
    main()
