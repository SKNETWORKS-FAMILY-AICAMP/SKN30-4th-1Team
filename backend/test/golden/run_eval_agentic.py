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
      context_precision/recall 채점용(골든 정답 텍스트와 매칭할 때 메타·마커가
      섞이면 노이즈가 된다, run_eval.py의 기존 관례와 동일).
    - rendered_contexts: 실제 LLM이 답변을 생성할 때 읽은 것과 같은 완성 라인
      (메타·이유·출처 포함). faithfulness/response_relevancy 채점용 — 실측으로
      확인: 순수 content만 주면 LLM이 메타데이터(예: "날짜: 2026-04-20")를 근거로
      정당하게 답한 문장도 판정기가 "컨텍스트에 없는 주장"으로 오판해 faithfulness가
      실제보다 낮게 나온다(qid C6/A10 사례).
    """

    def __init__(self):
        self.contexts: list[str] = []
        self.rendered_contexts: list[str] = []

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
            return memory

        def row_line_body(r):
            content = r.get("content")
            if content:
                self.contexts.append(content)
            rendered = self._orig_row_line_body(r)
            self.rendered_contexts.append(rendered)
            return rendered

        def build_context(*args, **kwargs):
            context, sources, debug = self._orig_build_context(*args, **kwargs)
            chunk_texts = [c["text_full"] for c in debug.get("chroma_chunks", []) if c.get("text_full")]
            self.contexts.extend(chunk_texts)
            self.rendered_contexts.extend(chunk_texts)  # 문서 청크는 메타 개념이 없어 원문 그대로 공유
            return context, sources, debug

        def fetch_overview_context(*args, **kwargs):
            import json as _json
            overview = self._orig_fetch_overview(*args, **kwargs)
            if overview.get("overview_summary"):
                self.contexts.append(overview["overview_summary"])
                self.rendered_contexts.append(overview["overview_summary"])
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
            for row in action_plan.get("items") or []:
                content = row.get("content")
                if content:
                    self.contexts.append(content)
                    # overview 도구는 LLM에게 행 dict를 JSON 그대로 넘긴다(get_project_overview
                    # 참고) — owner/date/completion_status가 실제로 거기 다 들어있다.
                    self.rendered_contexts.append(_json.dumps(row, ensure_ascii=False, default=str))
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
            row = {
                "qid": q["qid"], "tag": q["tag"], "question": q["question"],
                "reference": q["reference"], "response": result["answer"],
                "contexts": recorder.collected(),
                "rendered_contexts": recorder.collected_rendered(),
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(f"[{i}/{len(questions)}] {q['qid']} 컨텍스트 {len(row['contexts'])}개 수집")
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
    """context_precision/recall은 순수 content 컨텍스트로, faithfulness/response_relevancy는
    추가로 rendered_contexts(메타 포함, 실제 LLM이 본 것과 동일)로 한 번 더 채점해 나란히
    비교한다 — 순수 content만으로는 답변이 메타데이터(담당·날짜·완료상태)를 근거로 한 문장을
    판정기가 "컨텍스트에 없는 주장"으로 오판해 faithfulness가 실제보다 낮게 나오기 때문
    (qid C6/A10 실측). ragas_score는 run_eval.py의 공용 함수라 여기서 두 번 호출해 필요한
    지표만 골라 쓰고, 그 함수 자체는 손대지 않는다."""
    require_openai_key()
    in_path = Path(args.input)
    rows = _load_rows(in_path)
    for row in rows:
        row.setdefault("tag", "qa")

    scores = ragas_score(rows, args.judge, True, args.workers)
    print(f"[완료] score(순수 content 기준 — context_precision/recall은 이 값이 정본) "
          f"{in_path.name}: {scores}")

    has_rendered = all(row.get("rendered_contexts") for row in rows)
    if has_rendered:
        rendered_rows = [dict(row, contexts=row["rendered_contexts"]) for row in rows]
        rendered_scores = ragas_score(rendered_rows, args.judge, True, args.workers)
        for row, rendered_row in zip(rows, rendered_rows):
            row["faithfulness_rendered"] = rendered_row.get("faithfulness")
            row["response_relevancy_rendered"] = rendered_row.get("response_relevancy")
        print(f"[완료] score(메타 포함 rendered_contexts 기준 — faithfulness/relevancy는 "
              f"이 값이 정본): faithfulness={rendered_scores.get('faithfulness')} "
              f"response_relevancy={rendered_scores.get('response_relevancy')}")
    else:
        print("[안내] rendered_contexts 없음(구버전 jsonl) — faithfulness 비교 재채점 생략")

    detail_path = in_path.with_suffix(".scored.csv")
    import csv
    cols = ["qid", "question", "context_precision", "context_recall",
            "faithfulness", "response_relevancy"]
    if has_rendered:
        cols += ["faithfulness_rendered", "response_relevancy_rendered"]
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
