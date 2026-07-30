"""골든셋 평가 결과를 하나의 엑셀 파일로 정리(export).

`results/summary.csv`를 읽어 최종 결과·계층 기여·관측 지표·인용 분석·한계를
시트별로 담은 `docs/archive/evaluation/golden-v1/EVAL_REPORT.xlsx`를 pandas ExcelWriter(openpyxl)로 쓴다.

사용: .venv/bin/python backend/test/golden/export_report.py [--runid RID]
"""
import argparse
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
SUMMARY = HERE / "results" / "summary.csv"
OUT = REPO / "docs" / "archive" / "evaluation" / "golden-v1" / "EVAL_REPORT.xlsx"

MAIN = ["R0-sql", "R0-vec", "R0-both", "E0", "E1", "E2-e2e"]
CORPORA = ["modu", "csbot"]


def _num(v):
    try:
        return round(float(v), 4)
    except (TypeError, ValueError):
        return None


def _tag_breakdown(runid: str) -> pd.DataFrame:
    """구성×코퍼스×tag별 검색 품질 지표(context_precision/recall)를 dev 상세
    CSV에서 집계. 생성 지표는 R0×3·E1엔 없으므로 이 표에는 넣지 않는다
    (검색 정확도 확인 목적 — 아래 주석 참조)."""
    tags = ["decision", "conflict", "conflict_negative", "action"]
    rows = []
    for corpus in CORPORA:
        for cfg in MAIN:
            path = HERE / "results" / f"ragas_{corpus}_{cfg}_dev_{runid}.csv"
            if not path.exists():
                continue
            df = pd.read_csv(path, encoding="utf-8-sig")
            for tag in tags:
                sub = df[df["tag"] == tag]
                if sub.empty:
                    continue
                cp = pd.to_numeric(sub["context_precision"], errors="coerce").mean()
                cr = pd.to_numeric(sub["context_recall"], errors="coerce").mean()
                rows.append({"corpus": corpus, "config": cfg, "tag": tag,
                             "context_precision": round(cp, 3),
                             "context_recall": round(cr, 3)})
    return pd.DataFrame(rows)


def _routing_audit(runid: str) -> pd.DataFrame:
    """질문별 라우팅 감사(기대 vs 실제 경로·이력모드) — routing_audit CSV 병합.
    라우팅이 문항별로 제대로 됐는지 확인용(불일치 행이 진단 핵심)."""
    frames = []
    for corpus in CORPORA:
        p = HERE / "results" / f"routing_audit_{corpus}_dev_{runid}.csv"
        if p.exists():
            frames.append(pd.read_csv(p, encoding="utf-8-sig"))
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    # 불일치 여부 컬럼(사람이 바로 필터링하도록)
    df["mismatch"] = ((df["route_match"].astype(str) != "True")
                      | (df["history_match"].astype(str) != "True"))
    return df


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runid", default=None)
    args = ap.parse_args()

    df = pd.read_csv(SUMMARY, dtype=str, encoding="utf-8-sig").fillna("")
    runid = args.runid or sorted(df["run_id"].unique())[-1]
    df = df[df["run_id"] == runid].copy()
    for col in ("context_precision", "context_recall", "faithfulness",
                "response_relevancy", "citation_grounding", "routing_accuracy",
                "chain_inclusion_rate", "abstain_rate"):
        if col in df.columns:
            df[col] = df[col].map(_num)

    def rows(phase, configs):
        out = []
        for corpus in CORPORA:
            for cfg in configs:
                m = df[(df.phase == phase) & (df.corpus == corpus)
                       & (df.config == cfg)]
                if len(m):
                    out.append(m.iloc[-1])
        return pd.DataFrame(out)

    # 시트 1: 최종 결과(final E0·E2-e2e)
    final = rows("final", ["E0", "E2-e2e"])[
        ["corpus", "config", "judge", "context_precision", "context_recall",
         "faithfulness", "response_relevancy", "citation_grounding"]]

    # 시트 2: 계층 기여(dev, context 지표)
    dev = rows("dev", MAIN)[
        ["corpus", "config", "context_precision", "context_recall"]]

    # 시트 3: 관측 지표(dev)
    obs = rows("dev", MAIN)[
        ["corpus", "config", "routing_accuracy", "chain_inclusion_rate",
         "abstain_rate"]]

    # 시트 4: 인용 분석(final)
    cite = rows("final", ["E0", "E2-e2e"])[
        ["corpus", "config", "citation_grounding"]].copy()
    cite["비고"] = ""
    mask = (cite.corpus == "csbot") & (cite.config == "E2-e2e")
    cite.loc[mask, "비고"] = ("경계 사례 A7: (출처: 파일.md, 파일.md 원문) — "
                              "올바른 파일 인용에 '원문' 접미가 붙어 엄격 파서가 "
                              "0점(추적성엔 지장 없음, 비재현)")

    # 시트 5: 한계·주석
    notes = pd.DataFrame({
        "항목": ["context_precision", "citation_grounding", "비결정성",
                 "라우팅 감사", "이력 감지(history_mode)",
                 "chain_inclusion"],
        "내용": [
            "recall 우선 검색 설계상 낮은 순도 지표. SQL 구조화 기록이 문항당 "
            "13~16행 반환(무관 행 포함) → precision 희석. 하이브리드가 naive 대비 "
            "3~4배 개선. recall은 0.96~1.0 유지.",
            "답변의 (출처: 라벨) 마커를 검색 출처 집합으로 엄격 판정. 마커 형식이 "
            "어긋나면(A7 '원문' 접미) 실제 파일 인용이어도 0점.",
            "답변 생성 비결정성으로 인용 수치 소폭 변동(직전 run modu C10 0.962→1.0).",
            "route(semantic/filter_lookup/overview)는 LLM 폴백이라 비결정 가능. "
            "단 history_mode는 정규식이라 결정론적.",
            "정규식(detect_history_intent)으로만 켜짐(LLM은 route만). conflict "
            "표현('바뀌었는가' 등)을 못 잡아 재현율 0% — 재현성 아닌 recall 문제. "
            "개선=TASK-008(선행), supersede correctness=TASK-009.",
            "이력 라우팅 작동 지표가 아님 — pair old/new 문구가 검색 컨텍스트에 "
            "있는지만 검사(일반 검색으로도 통과, csbot 1.0이 그 경우).",
        ],
    })

    # 시트 6: 컬럼 설명(데이터 사전) — 어떤 값이 어떤 지표인지 바로 확인
    legend = pd.DataFrame({
        "컬럼": ["context_precision", "context_recall", "faithfulness",
                 "response_relevancy", "citation_grounding", "routing_accuracy",
                 "history_detect_rate", "chain_inclusion_rate", "abstain_rate",
                 "config", "phase", "n / n_contexts", "tag"],
        "설명": [
            "검색된 컨텍스트 중 정답 관련 비율(검색 순도) — 높을수록 노이즈 적음",
            "정답에 필요한 근거가 검색된 비율(누락 없음) — 높을수록 좋음",
            "답변 주장이 컨텍스트에 근거한 비율(환각 반대) — 높을수록 좋음",
            "답변이 질문에 부합하는 정도 — 높을수록 좋음",
            "답변이 실제 검색 출처를 (출처: 파일명)으로 인용했는지(1.0/0.0 평균, "
            "출처 추적성) — final E0·E2-e2e만",
            "라우팅 감사 정확도 — 관측값(합격 조건 아님)",
            "이력 질문 감지율 — 관측값",
            "pair old/new 문구가 검색 컨텍스트에 포함됐는지 검사(E2) — 이력 "
            "라우팅 작동 여부가 아님(일반 검색으로도 통과)",
            "환각 문항 기권률(환각 방지) — 높을수록 좋음",
            "검색 구성: R0-sql/vec/both(초기 재현)·E0(하이브리드)·E1(+계층1·2)·"
            "E2-e2e(+계층3, 실서비스 경로)",
            "dev=개발 검증 / final=보고 수치(context는 dev 승격, 생성·인용은 증분)",
            "n=구성별 채점 문항 수 / n_contexts=문항별 검색 컨텍스트 수",
            "문항 유형: decision·action·conflict·conflict_negative·hallucination",
        ],
    })

    # 시트 7: 유형별 검색 품질(dev, context 지표만 — 생성 지표는 R0×3·E1엔 없어 제외)
    tagq = _tag_breakdown(runid)
    # 시트 8: 질문별 라우팅 감사(이력 라우팅 필요/불필요 확인 — mismatch 열로 필터)
    routing = _routing_audit(runid)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(OUT, engine="openpyxl") as xw:
        final.to_excel(xw, sheet_name="최종결과(final)", index=False)
        dev.to_excel(xw, sheet_name="계층기여(dev-context)", index=False)
        obs.to_excel(xw, sheet_name="관측지표(dev)", index=False)
        cite.to_excel(xw, sheet_name="인용분석", index=False)
        tagq.to_excel(xw, sheet_name="유형별검색품질", index=False)
        if not routing.empty:
            routing.to_excel(xw, sheet_name="라우팅감사", index=False)
        notes.to_excel(xw, sheet_name="한계·주석", index=False)
        legend.to_excel(xw, sheet_name="컬럼설명", index=False)
        # 열 폭 자동 조정
        for ws in xw.book.worksheets:
            for col in ws.columns:
                width = max((len(str(c.value)) for c in col if c.value), default=10)
                ws.column_dimensions[col[0].column_letter].width = min(width + 2, 80)

    print(f"[완료] 엑셀 리포트 → {OUT} (run_id={runid})")


if __name__ == "__main__":
    main()
