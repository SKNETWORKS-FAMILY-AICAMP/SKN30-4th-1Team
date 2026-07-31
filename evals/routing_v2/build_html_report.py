#!/usr/bin/env python3
"""Build a self-contained HTML viewer for the current routing_v2 result."""

from __future__ import annotations

import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
RESULT_PATH = HERE / "results" / "current_scored.json"
OUTPUT_PATH = HERE / "CURRENT_BRANCH_REPORT.html"


HTML_TEMPLATE = r"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>routing_v2 실제 답변 확인</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4f5f7;
      --panel: #ffffff;
      --line: #dfe3e8;
      --text: #18202a;
      --muted: #66717f;
      --pass: #087a4b;
      --pass-bg: #e9f8f1;
      --partial: #a05a00;
      --partial-bg: #fff3df;
      --fail: #c52b35;
      --fail-bg: #fff0f1;
      --accent: #315efb;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    * { box-sizing: border-box; }
    body { margin: 0; background: var(--bg); color: var(--text); }
    .top {
      position: sticky; top: 0; z-index: 10;
      padding: 18px clamp(16px, 4vw, 48px);
      background: rgba(244, 245, 247, .96);
      border-bottom: 1px solid var(--line);
      backdrop-filter: blur(12px);
    }
    h1 { margin: 0 0 5px; font-size: 22px; }
    .meta { color: var(--muted); font-size: 13px; }
    .stats {
      display: grid;
      grid-template-columns: repeat(6, minmax(110px, 1fr));
      gap: 8px; margin-top: 14px;
    }
    .stat {
      padding: 10px 12px; background: var(--panel);
      border: 1px solid var(--line); border-radius: 9px;
    }
    .stat span { display: block; color: var(--muted); font-size: 11px; }
    .stat strong { display: block; margin-top: 3px; font-size: 18px; }
    .controls {
      display: grid;
      grid-template-columns: minmax(240px, 2fr) repeat(3, minmax(125px, 1fr));
      gap: 8px; margin-top: 12px;
    }
    input, select {
      width: 100%; min-height: 38px; padding: 8px 10px;
      border: 1px solid #cbd2da; border-radius: 7px;
      background: white; color: var(--text); font: inherit;
    }
    main { max-width: 1500px; margin: 0 auto; padding: 18px clamp(16px, 4vw, 48px) 80px; }
    .notice {
      margin-bottom: 12px; padding: 10px 12px;
      border: 1px solid #ffd38b; border-radius: 8px; background: #fff8ea;
      font-size: 13px; line-height: 1.45;
    }
    .result-count { margin: 10px 1px; color: var(--muted); font-size: 13px; }
    .card {
      margin: 10px 0; overflow: hidden;
      border: 1px solid var(--line); border-radius: 10px; background: var(--panel);
      box-shadow: 0 1px 2px rgba(20, 30, 45, .04);
    }
    .card-head {
      display: flex; align-items: center; flex-wrap: wrap; gap: 7px;
      padding: 11px 13px; border-bottom: 1px solid var(--line);
    }
    .id { font-weight: 750; }
    .question { flex: 1 1 420px; font-weight: 650; }
    .badge {
      display: inline-flex; align-items: center; min-height: 23px;
      padding: 2px 7px; border-radius: 999px; font-size: 11px; font-weight: 750;
    }
    .badge.pass { color: var(--pass); background: var(--pass-bg); }
    .badge.partial { color: var(--partial); background: var(--partial-bg); }
    .badge.fail { color: var(--fail); background: var(--fail-bg); }
    .badge.neutral { color: #4d5968; background: #eef1f4; }
    .badge.drift { color: #7a4300; background: #ffe7bd; }
    .compare { display: grid; grid-template-columns: 1fr 1fr; }
    .pane { min-width: 0; padding: 13px; }
    .pane + .pane { border-left: 1px solid var(--line); background: #fafbfc; }
    .pane h2, .detail h2 {
      margin: 0 0 8px; color: var(--muted);
      font-size: 11px; letter-spacing: .04em; text-transform: uppercase;
    }
    .answer { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.55; font-size: 14px; }
    .detail {
      display: grid; grid-template-columns: 1.2fr 1fr; gap: 14px;
      padding: 11px 13px; border-top: 1px solid var(--line); background: #fcfcfd;
    }
    .detail p { margin: 0; color: #46515e; font-size: 13px; line-height: 1.45; }
    .facts { display: flex; flex-wrap: wrap; gap: 5px; }
    .fact {
      padding: 3px 6px; border: 1px solid var(--line);
      border-radius: 5px; background: white; color: #46515e; font-size: 11px;
    }
    .empty { padding: 50px 16px; text-align: center; color: var(--muted); }
    @media (max-width: 950px) {
      .stats { grid-template-columns: repeat(3, 1fr); }
      .controls { grid-template-columns: 1fr 1fr; }
    }
    @media (max-width: 680px) {
      .top { position: static; }
      .stats { grid-template-columns: repeat(2, 1fr); }
      .controls, .compare, .detail { grid-template-columns: 1fr; }
      .pane + .pane { border-left: 0; border-top: 1px solid var(--line); }
    }
  </style>
</head>
<body>
  <header class="top">
    <h1>routing_v2 실제 답변 확인</h1>
    <div class="meta" id="meta"></div>
    <section class="stats" id="stats"></section>
    <section class="controls">
      <input id="search" type="search" placeholder="ID, 질문, 실제 답변, golden 검색">
      <select id="verdict">
        <option value="ISSUE">PARTIAL + FAIL 먼저 보기</option>
        <option value="ALL">전체 판정</option>
        <option value="PASS">PASS</option>
        <option value="PARTIAL">PARTIAL</option>
        <option value="FAIL">FAIL</option>
      </select>
      <select id="corpus"><option value="ALL">전체 코퍼스</option></select>
      <select id="family"><option value="ALL">전체 유형</option></select>
    </section>
  </header>
  <main>
    <div class="notice">
      공식 판정은 <b>golden.json 그대로</b> 채점한 결과입니다.
      V2-STR-05와 V2-STR-12는 현재 DB count와 실제 답변이 일치하지만 golden 수치가 달라
      FAIL로 남겨 두었습니다. 카드의 <b>STATE DRIFT</b> 표시를 함께 확인하세요.
    </div>
    <div class="result-count" id="resultCount"></div>
    <section id="cards"></section>
  </main>
  <script>
    const SUMMARY = __SUMMARY__;
    const RECORDS = __RECORDS__;
    const order = {FAIL: 0, PARTIAL: 1, PASS: 2};
    const $ = (id) => document.getElementById(id);

    function node(tag, className, text) {
      const element = document.createElement(tag);
      if (className) element.className = className;
      if (text !== undefined) element.textContent = text;
      return element;
    }

    function badge(text, kind = "neutral") {
      return node("span", `badge ${kind}`, text);
    }

    function addOptions(select, values) {
      [...new Set(values)].sort().forEach((value) => {
        const option = node("option", "", value);
        option.value = value;
        select.append(option);
      });
    }

    function renderStats() {
      const adjusted = SUMMARY.current_state_adjusted_diagnostic?.answer_verdicts;
      const values = [
        ["전체", `${SUMMARY.total}문항`],
        ["API", `${SUMMARY.api_success}/${SUMMARY.total}`],
        ["Tool 계약", `${SUMMARY.tool_contract_pass}/${SUMMARY.total}`],
        ["엄격 P/P/F", `${SUMMARY.answer_verdicts.PASS}/${SUMMARY.answer_verdicts.PARTIAL}/${SUMMARY.answer_verdicts.FAIL}`],
        ["상태 보정 P/P/F", adjusted ? `${adjusted.PASS}/${adjusted.PARTIAL}/${adjusted.FAIL}` : "-"],
        ["평균 / p95", `${(SUMMARY.latency_ms.average / 1000).toFixed(2)}s / ${(SUMMARY.latency_ms.p95 / 1000).toFixed(2)}s`],
      ];
      values.forEach(([label, value]) => {
        const item = node("div", "stat");
        item.append(node("span", "", label), node("strong", "", value));
        $("stats").append(item);
      });
    }

    function renderCard(record) {
      const card = node("article", "card");
      card.id = record.id;
      const head = node("header", "card-head");
      head.append(
        node("span", "id", record.id),
        badge(record.judgment.verdict, record.judgment.verdict.toLowerCase()),
        badge(record.corpus),
        badge(record.family),
        badge(`Tool ${record.tool_contract.passed ? "PASS" : "FAIL"}`,
          record.tool_contract.passed ? "pass" : "fail"),
        badge(`${(Number(record.latency_ms) / 1000).toFixed(2)}s`)
      );
      if (record.golden_state_drift.length) head.append(badge("STATE DRIFT", "drift"));
      head.append(node("div", "question", record.question));

      const compare = node("div", "compare");
      const actualPane = node("section", "pane");
      actualPane.append(node("h2", "", "실제 답변"), node("p", "answer", record.answer));
      const goldenPane = node("section", "pane");
      goldenPane.append(
        node("h2", "", "Golden 정답"),
        node("p", "answer", record.reference_answer)
      );
      compare.append(actualPane, goldenPane);

      const detail = node("section", "detail");
      const judge = node("div");
      judge.append(node("h2", "", "판정 이유"), node("p", "", record.judgment.rationale));
      if (record.golden_state_drift.length) {
        const driftText = record.golden_state_drift
          .map((item) => `${item.field}: golden ${item.golden} → 현재 DB ${item.current_state}`)
          .join(" / ");
        judge.append(node("p", "", `상태 확인: ${driftText}`));
      }
      const factsWrap = node("div");
      factsWrap.append(node("h2", "", "필수 사실"));
      const facts = node("div", "facts");
      (record.required_facts || []).forEach((fact) => facts.append(node("span", "fact", fact)));
      factsWrap.append(facts);
      detail.append(judge, factsWrap);

      card.append(head, compare, detail);
      return card;
    }

    function applyFilters() {
      const query = $("search").value.trim().toLowerCase();
      const verdict = $("verdict").value;
      const corpus = $("corpus").value;
      const family = $("family").value;
      const filtered = RECORDS.filter((record) => {
        const judgment = record.judgment.verdict;
        const verdictMatch = verdict === "ALL"
          || judgment === verdict
          || (verdict === "ISSUE" && judgment !== "PASS");
        const corpusMatch = corpus === "ALL" || record.corpus === corpus;
        const familyMatch = family === "ALL" || record.family === family;
        const text = [
          record.id, record.question, record.answer, record.reference_answer,
          record.judgment.rationale
        ].join(" ").toLowerCase();
        return verdictMatch && corpusMatch && familyMatch && (!query || text.includes(query));
      }).sort((a, b) => order[a.judgment.verdict] - order[b.judgment.verdict]
        || a.id.localeCompare(b.id));

      $("cards").replaceChildren(...filtered.map(renderCard));
      $("resultCount").textContent = `${filtered.length} / ${RECORDS.length}문항 표시`;
      if (!filtered.length) $("cards").append(node("div", "empty", "조건에 맞는 문항이 없습니다."));
    }

    $("meta").textContent =
      `${SUMMARY.branch} · ${SUMMARY.commit.slice(0, 8)} · ${SUMMARY.scored_at}`;
    renderStats();
    addOptions($("corpus"), RECORDS.map((item) => item.corpus));
    addOptions($("family"), RECORDS.map((item) => item.family));
    ["search", "verdict", "corpus", "family"].forEach((id) => {
      $(id).addEventListener(id === "search" ? "input" : "change", applyFilters);
    });
    applyFilters();
  </script>
</body>
</html>
"""


def main() -> int:
    payload = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    records = [
        {
            "id": item["id"],
            "corpus": item["corpus"],
            "family": item["family"],
            "question": item["question"],
            "latency_ms": item["latency_ms"],
            "answer": item["answer"],
            "reference_answer": item["reference_answer"],
            "required_facts": item["required_facts"],
            "actual_tools": item["actual_tools"],
            "tool_contract": item["tool_contract"],
            "judgment": item["judgment"],
            "golden_state_drift": item.get("golden_state_drift") or [],
        }
        for item in payload["records"]
    ]
    summary_json = json.dumps(
        payload["summary"], ensure_ascii=False, separators=(",", ":")
    ).replace("</", "<\\/")
    records_json = json.dumps(
        records, ensure_ascii=False, separators=(",", ":")
    ).replace("</", "<\\/")
    html = (
        HTML_TEMPLATE
        .replace("__SUMMARY__", summary_json)
        .replace("__RECORDS__", records_json)
    )
    OUTPUT_PATH.write_text(html, encoding="utf-8")
    print(f"wrote {OUTPUT_PATH} ({len(records)} records)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
