#!/usr/bin/env python3
"""Build human-reviewable reports for the agentic routing experiment.

The reports deliberately keep evaluation results separate from proposed fixes.
They compare the exact legacy and agentic JSONL rows produced from the same
ingested corpus and expose every golden answer, actual answer, source, verdict,
and review note.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path


VERDICT_KO = {"PASS": "일치", "PARTIAL": "부분일치", "FAIL": "불일치"}

LEGACY_NON_PASS = {
    "modu": {
        "B2": "PARTIAL", "B8": "FAIL", "B10": "FAIL", "C1": "PARTIAL",
        "C2": "FAIL", "C3": "PARTIAL", "C4": "FAIL", "C5": "FAIL",
        "C6": "FAIL", "C8": "FAIL", "C10": "PARTIAL",
    },
    "csbot": {
        "A4": "PARTIAL", "B1": "FAIL", "B3": "FAIL", "B4": "FAIL",
        "B5": "FAIL", "B6": "FAIL", "B7": "PARTIAL", "B9": "FAIL",
        "B10": "FAIL", "C1": "PARTIAL", "C2": "FAIL", "C3": "PARTIAL",
        "C6": "PARTIAL", "C8": "PARTIAL", "C10": "FAIL",
    },
}

AGENTIC_NON_PASS = {
    "modu": {"B4": "FAIL", "C1": "FAIL"},
    "csbot": {"B6": "FAIL", "B7": "PARTIAL", "B10": "PARTIAL", "C5": "PARTIAL"},
}

LEGACY_REVIEW = {
    ("modu", "B2"): "최초 5/11과 변경 5/18 행은 포함됐지만 최초→최종 관계와 변경 이유를 직접 종합하지 못했다.",
    ("modu", "B8"): "질문이 요구한 리텐션 64%가 답변에 없다.",
    ("modu", "B10"): "5/18 유지가 정답인데 조건에 맞는 기록이 없다고 잘못 기권했다.",
    ("modu", "C1"): "정답 행은 섞여 있으나 앱 SDK 세 종류의 담당자를 하나로 직접 답하지 못했다.",
    ("modu", "C2"): "SPF/DKIM 작업과 이수진의 관계를 만들지 못하고 관련 이슈 목록을 반환했다.",
    ("modu", "C3"): "한지민·베타 테스터 100명 행은 있으나 질문에 대한 직접 답으로 종합하지 않았다.",
    ("modu", "C4"): "예산 기록이 없다고 기권해야 하지만 관련 없는 결정을 반환했다.",
    ("modu", "C5"): "정식 출시 후 지표가 없다고 기권해야 하지만 관련 없는 전체 기록을 반환했다.",
    ("modu", "C6"): "박현우·이수진이라는 근거가 있는데도 기록이 없다고 잘못 기권했다.",
    ("modu", "C8"): "이수진과 푸시 큐 개선 근거가 있는데도 기록이 없다고 잘못 기권했다.",
    ("modu", "C10"): "이수진·5/19 착수 행을 반환했지만 질문의 직접 답으로 종합하지 않았다.",
    ("csbot", "A4"): "75%→88%, +13%p, +0.6초는 맞지만 2.3→2.5초라는 모순된 보충 수치를 덧붙였다.",
    ("csbot", "B1"): "최종 87%와 +32%p가 기록에 있는데도 확인할 수 없다고 잘못 기권했다.",
    ("csbot", "B3"): "결정 목록만 제시하고 6/16 입장의 유지와 6/27의 구체화 관계를 답하지 않았다.",
    ("csbot", "B4"): "조건부 보류→정식 도입인데 변경 이력이 없었다고 반대로 설명했다.",
    ("csbot", "B5"): "55%→90%→90% 근거가 있는데도 확인할 수 없다고 잘못 기권했다.",
    ("csbot", "B6"): "1.9초→2.5초(+0.6초) 근거가 있는데도 확인할 수 없다고 잘못 기권했다.",
    ("csbot", "B7"): "본문에는 미정→구체화가 있으나 결론은 처음부터 일관됐다고 과장했다.",
    ("csbot", "B9"): "전체 기록을 나열했지만 45%와 20건 중 9건을 답하지 않았다.",
    ("csbot", "B10"): "하루 340건, 전체 18%, 반품·교환 31%를 답하지 않았다.",
    ("csbot", "C1"): "박서연 담당 행은 포함됐지만 두 작업의 담당자라는 관계를 직접 답하지 않았다.",
    ("csbot", "C2"): "관련 항목은 섞여 있으나 우선순위가 높은 두 항목을 식별하지 않았다.",
    ("csbot", "C3"): "최민준·6/30 오후 2시 행을 반환했지만 직접 답으로 종합하지 않았다.",
    ("csbot", "C6"): "강다은·7/3 행을 반환했지만 직접 답으로 종합하지 않았다.",
    ("csbot", "C8"): "강다은·6/24 행을 반환했지만 직접 답으로 종합하지 않았다.",
    ("csbot", "C10"): "윤재혁·7/3 근거가 있는데도 조건에 맞는 기록이 없다고 잘못 기권했다.",
}

AGENTIC_REVIEW = {
    ("modu", "B4"): "게시판형 MVP 결정은 유지되고 실시간 채팅이 1.1에 추가됐는데, 이를 기존 결정의 번복으로 잘못 종합했다.",
    ("modu", "C1"): "앱 SDK 담당 박현우와 백엔드 OAuth 담당 이수진을 섞어 Apple 담당자를 잘못 배정했다.",
    ("csbot", "B6"): "정답 근거인 1.9초 청크를 회수하지 못하고 2.3초와 +0.6초를 결합해 2.9초로 답했다.",
    ("csbot", "B7"): "미정→구체화 흐름을 본문에 담았지만 첫 결론에서 방향이 일관됐다고 과장했다.",
    ("csbot", "B10"): "전체 18%는 답했지만 질문의 두 번째 값인 반품·교환 31%를 누락했다.",
    ("csbot", "C5"): "미확정 판단은 맞지만 7/3에 확정될 것이라고 말하고 7/1 협의를 이미 시작된 일처럼 바꿨다.",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--docs", type=Path, required=True)
    return parser.parse_args()


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def verdict(corpus: str, qid: str, mode: str) -> str:
    table = LEGACY_NON_PASS if mode == "legacy" else AGENTIC_NON_PASS
    return table[corpus].get(qid, "PASS")


def review(corpus: str, qid: str, mode: str) -> str:
    table = LEGACY_REVIEW if mode == "legacy" else AGENTIC_REVIEW
    return table.get((corpus, qid), "질문이 요구한 핵심 사실과 골든 답변이 일치한다.")


def fmt_sources(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) if value else "반환 없음"
    return str(value or "반환 없음")


def stats(rows: list[dict], corpus: str, mode: str) -> dict:
    selected = [row for row in rows if row["corpus"] == corpus]
    labels = Counter(verdict(corpus, row["qid"], mode) for row in selected)
    chars = [len(str(row.get("answer") or "")) for row in selected]
    latency = [float(row["latency_ms"]) for row in selected]
    return {
        "labels": labels,
        "chars_mean": statistics.mean(chars),
        "chars_median": statistics.median(chars),
        "chars_max": max(chars),
        "latency_mean": statistics.mean(latency),
        "latency_median": statistics.median(latency),
        "latency_max": max(latency),
        "over_1000": sum(value > 1000 for value in chars),
        "dump_phrase": sum("조건에 맞는 기록" in str(row.get("answer") or "") for row in selected),
    }


def badge(label: str) -> str:
    return f'<span class="badge {label.lower()}">{VERDICT_KO[label]}</span>'


def code_hashes(root: Path) -> str:
    paths = [
        root / "backend/agentic_graph.py",
        root / "backend/retriever/qa_tools.py",
        root / "backend/retriever/qa_engine.py",
        root / "backend/api/query.py",
    ]
    values = []
    for path in paths:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
        values.append(f"{path.relative_to(root)}={digest}")
    return " · ".join(values)


STYLE = """
:root{--bg:#f3f5f8;--paper:#fff;--ink:#182230;--muted:#667085;--line:#d9dee7;--pass:#16794c;--partial:#a76608;--fail:#b73535;--accent:#315be8}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Noto Sans KR",sans-serif;line-height:1.55}main{max-width:1540px;margin:auto;padding:32px}header,.panel,.item{background:var(--paper);border:1px solid var(--line);border-radius:14px;box-shadow:0 3px 18px #17243a0b}header,.panel{padding:24px;margin-bottom:16px}h1{margin:0 0 8px}h2{margin:0 0 12px}.muted,.meta{color:var(--muted)}.scores{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:20px}.score{padding:14px;border:1px solid var(--line);border-radius:10px}.score b{display:block;font-size:26px}.score.agent b{color:var(--accent)}table{width:100%;border-collapse:collapse}th,td{padding:9px 12px;text-align:left;border-bottom:1px solid var(--line)}.item{margin:12px 0;overflow:hidden}.item.pass{border-left:5px solid var(--pass)}.item.partial{border-left:5px solid var(--partial)}.item.fail{border-left:5px solid var(--fail)}summary{display:grid;grid-template-columns:auto auto auto 1fr;gap:10px;align-items:center;padding:16px;cursor:pointer}.badge{color:white;border-radius:99px;padding:3px 9px;font-size:12px}.badge.pass{background:var(--pass)}.badge.partial{background:var(--partial)}.badge.fail{background:var(--fail)}.gold{padding:18px;border-top:1px solid var(--line);background:#f8f9fb}.compare{display:grid;grid-template-columns:1fr 1fr}.answer{padding:18px;min-width:0}.answer+.answer{border-left:1px solid var(--line)}h3{margin-top:0}h4{margin:16px 0 5px;color:var(--muted)}pre{white-space:pre-wrap;word-break:break-word;background:#f8f9fb;border:1px solid var(--line);border-radius:9px;padding:13px;font:13px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace}.why{margin:0;padding:16px 18px;border-top:1px solid var(--line);background:#fffdf5}.tool{font-size:12px;color:var(--muted);word-break:break-word}.notice{border-left:5px solid var(--accent)}@media(max-width:900px){main{padding:14px}.scores{grid-template-columns:1fr 1fr}.compare{grid-template-columns:1fr}.answer+.answer{border-left:0;border-top:1px solid var(--line)}summary{grid-template-columns:auto auto auto 1fr}}
"""


def corpus_html(corpus: str, legacy: list[dict], agentic: list[dict], root: Path) -> str:
    label = "Modu" if corpus == "modu" else "CS-Bot"
    legacy_map = {row["qid"]: row for row in legacy if row["corpus"] == corpus}
    agentic_map = {row["qid"]: row for row in agentic if row["corpus"] == corpus}
    ls = stats(legacy, corpus, "legacy")
    ag = stats(agentic, corpus, "agentic")
    cards = []
    for qid, old in legacy_map.items():
        new = agentic_map[qid]
        lv = verdict(corpus, qid, "legacy")
        av = verdict(corpus, qid, "agentic")
        severity = "fail" if "FAIL" in (lv, av) else "partial" if "PARTIAL" in (lv, av) else "pass"
        tools = (new.get("debug") or {}).get("tools_used") or []
        calls = (new.get("debug") or {}).get("tool_calls") or []
        cards.append(f"""
<details class="item {severity}">
 <summary><strong>{html.escape(qid)}</strong>{badge(lv)}{badge(av)}<span>{html.escape(old['question'])}</span></summary>
 <div class="gold"><h3>골든</h3><p><strong>질문</strong> {html.escape(old['question'])}</p><pre>{html.escape(old['reference_answer'])}</pre><p class="meta"><strong>참고문항</strong> {html.escape(str(old.get('gold_source') or '없음'))}</p></div>
 <div class="compare">
  <article class="answer"><h3>기존 방식 {badge(lv)}</h3><pre>{html.escape(str(old.get('answer') or '(없음)'))}</pre><p class="meta"><strong>반환 출처</strong> {html.escape(fmt_sources(old.get('sources')))}</p><p class="meta">route={html.escape(str(old.get('route') or ''))} · {old['latency_ms']/1000:.2f}초</p><p><strong>판정 근거</strong> {html.escape(review(corpus,qid,'legacy'))}</p></article>
  <article class="answer"><h3>Agentic {badge(av)}</h3><pre>{html.escape(str(new.get('answer') or '(없음)'))}</pre><p class="meta"><strong>반환 출처</strong> {html.escape(fmt_sources(new.get('sources')))}</p><p class="meta">tools={html.escape(', '.join(tools) or '없음')} · {new['latency_ms']/1000:.2f}초</p><p class="tool">호출: {html.escape(json.dumps(calls, ensure_ascii=False, default=str))}</p><p><strong>판정 근거</strong> {html.escape(review(corpus,qid,'agentic'))}</p></article>
 </div>
</details>""")
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{label} Agentic Routing 평가</title><style>{STYLE}</style></head><body><main>
<header><h1>{label} Agentic Tool Routing 평가</h1><p class="muted">동일하게 적재한 코퍼스에 기존 방식과 agentic 방식을 순차 실행한 30문항 원문 비교 보고서입니다. 부분일치는 엄격 정답률에서 실패로 셉니다.</p>
<div class="scores"><div class="score"><span>기존 엄격 정답률</span><b>{ls['labels']['PASS']}/30</b><small>{ls['labels']['PASS']/30*100:.1f}%</small></div><div class="score agent"><span>Agentic 엄격 정답률</span><b>{ag['labels']['PASS']}/30</b><small>{ag['labels']['PASS']/30*100:.1f}%</small></div><div class="score"><span>기존 평균 길이</span><b>{ls['chars_mean']:.0f}자</b><small>1000자 초과 {ls['over_1000']}건</small></div><div class="score agent"><span>Agentic 평균 길이</span><b>{ag['chars_mean']:.0f}자</b><small>1000자 초과 {ag['over_1000']}건</small></div></div></header>
<section class="panel notice"><h2>읽는 법</h2><p>각 문항을 열면 <strong>골든 질문·답변·참고문항</strong>, <strong>기존 실제 답변</strong>, <strong>agentic 실제 답변</strong>, 반환 출처와 수동 판정 근거를 나란히 볼 수 있습니다. 이 파일은 결과 JSONL의 평가 당시 스냅샷이며, 아래 결과를 본 뒤 제안된 수정은 포함하지 않습니다.</p><p class="meta">평가 코드 기준: base HEAD eff0f3fd9229 + 실험 working tree · {html.escape(code_hashes(root))}</p></section>
<section class="panel"><h2>요약</h2><table><thead><tr><th>방식</th><th>일치</th><th>부분</th><th>불일치</th><th>평균/중앙 응답시간</th><th>평균/최대 길이</th><th>덤프 문구</th></tr></thead><tbody><tr><td>기존</td><td>{ls['labels']['PASS']}</td><td>{ls['labels']['PARTIAL']}</td><td>{ls['labels']['FAIL']}</td><td>{ls['latency_mean']/1000:.2f}/{ls['latency_median']/1000:.2f}초</td><td>{ls['chars_mean']:.0f}/{ls['chars_max']}자</td><td>{ls['dump_phrase']}</td></tr><tr><td>Agentic</td><td>{ag['labels']['PASS']}</td><td>{ag['labels']['PARTIAL']}</td><td>{ag['labels']['FAIL']}</td><td>{ag['latency_mean']/1000:.2f}/{ag['latency_median']/1000:.2f}초</td><td>{ag['chars_mean']:.0f}/{ag['chars_max']}자</td><td>{ag['dump_phrase']}</td></tr></tbody></table></section>
{''.join(cards)}</main></body></html>"""


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * fraction))]


def system_html(legacy: list[dict], agentic: list[dict], root: Path) -> str:
    legacy_by_key = {(row["corpus"], row["qid"]): row for row in legacy}
    agentic_by_key = {(row["corpus"], row["qid"]): row for row in agentic}
    legacy_chars = [len(str(row.get("answer") or "")) for row in legacy]
    agentic_chars = [len(str(row.get("answer") or "")) for row in agentic]
    legacy_lat = [float(row["latency_ms"]) for row in legacy]
    agentic_lat = [float(row["latency_ms"]) for row in agentic]
    route_groups: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for key, old in legacy_by_key.items():
        route_groups[str(old.get("route") or "unknown")].append((float(old["latency_ms"]), float(agentic_by_key[key]["latency_ms"])))
    route_rows = []
    for route, pairs in sorted(route_groups.items()):
        old_mean = statistics.mean(old for old, _ in pairs)
        new_mean = statistics.mean(new for _, new in pairs)
        route_rows.append(f"<tr><td>{html.escape(route)}</td><td>{len(pairs)}</td><td>{old_mean/1000:.2f}초</td><td>{new_mean/1000:.2f}초</td><td>{new_mean/old_mean:.2f}×</td><td>{sum(new < old for old,new in pairs)}/{len(pairs)}</td></tr>")
    tool_counts = Counter()
    call_count = 0
    for row in agentic:
        debug = row.get("debug") or {}
        combo = "+".join(debug.get("tools_used") or ["none"])
        tool_counts[combo] += 1
        call_count += len(debug.get("tool_calls") or [])
    expected = Counter(str(row.get("expected_route") or "unknown") for row in agentic)
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Agentic Routing 시스템 평가</title><style>{STYLE}</style></head><body><main>
<header><h1>Agentic Tool Routing 시스템 평가</h1><p class="muted">정답률과 별개로 출력 폭주, 도구 선택, 지연시간, API 안전성, 별도 forward 질문을 검증한 보고서입니다.</p><div class="scores"><div class="score agent"><span>Agentic 엄격 정답률</span><b>54/60</b><small>90.0%</small></div><div class="score"><span>기존 엄격 정답률</span><b>34/60</b><small>56.7%</small></div><div class="score agent"><span>답변 길이 감소</span><b>{(1-sum(agentic_chars)/sum(legacy_chars))*100:.1f}%</b><small>{sum(legacy_chars):,} → {sum(agentic_chars):,}자</small></div><div class="score agent"><span>HTTP 성공</span><b>60/60</b><small>fallback 0</small></div></div></header>
<section class="panel notice"><h2>평가 범위</h2><p>네 JSONL은 corpus/qid/question/reference/source/project_id가 모두 일치하고, 동일한 격리 DB를 agentic 후 legacy 순서로 읽기 전용 조회했습니다. 골든 60문항의 기대 경로는 {html.escape(str(dict(expected)))}로 모두 semantic이므로, 60문항만으로 목록·개수·overview 도구 선택을 평가할 수는 없습니다.</p><p class="meta">평가 코드 기준: base HEAD eff0f3fd9229 + 실험 working tree · {html.escape(code_hashes(root))}</p></section>
<section class="panel"><h2>출력 안전성</h2><table><thead><tr><th>방식</th><th>총 문자</th><th>평균/중앙/최대</th><th>1000자 초과</th><th>“조건에 맞는 기록”</th></tr></thead><tbody><tr><td>기존</td><td>{sum(legacy_chars):,}</td><td>{statistics.mean(legacy_chars):.0f}/{statistics.median(legacy_chars):.0f}/{max(legacy_chars):,}</td><td>{sum(v>1000 for v in legacy_chars)}</td><td>{sum('조건에 맞는 기록' in str(r.get('answer') or '') for r in legacy)}</td></tr><tr><td>Agentic</td><td>{sum(agentic_chars):,}</td><td>{statistics.mean(agentic_chars):.0f}/{statistics.median(agentic_chars):.0f}/{max(agentic_chars):,}</td><td>{sum(v>1000 for v in agentic_chars)}</td><td>{sum('조건에 맞는 기록' in str(r.get('answer') or '') for r in agentic)}</td></tr></tbody></table><p>사용자에게 보이는 답변 폭주는 제거됐습니다. 다만 agentic API raw payload에는 평균 약 8.2KB의 debug 근거가 남으므로 운영 응답에서는 debug 비노출 또는 opt-in이 필요합니다.</p></section>
<section class="panel"><h2>지연시간</h2><p>전체 평균은 {statistics.mean(legacy_lat)/1000:.2f}초 → {statistics.mean(agentic_lat)/1000:.2f}초, 중앙값은 {statistics.median(legacy_lat)/1000:.2f}초 → {statistics.median(agentic_lat)/1000:.2f}초, p95는 {percentile(legacy_lat,.95)/1000:.2f}초 → {percentile(agentic_lat,.95)/1000:.2f}초입니다. 1회 실행이며 agentic을 먼저 실행했으므로 확정적인 벤치마크로 보지 않습니다.</p><table><thead><tr><th>기존 route 묶음</th><th>문항</th><th>기존 평균</th><th>Agentic 평균</th><th>배율</th><th>Agentic이 빠름</th></tr></thead><tbody>{''.join(route_rows)}</tbody></table><p>semantic 문항에서는 빨라졌지만 단순 SQL/overview에서는 오케스트레이터 호출 비용 때문에 느려졌습니다.</p></section>
<section class="panel"><h2>도구 선택</h2><p>골든 60문항에서는 {html.escape(str(dict(tool_counts)))} 조합으로 총 {call_count}회 호출됐습니다. 이는 모든 문항이 특정 사실·수치·담당자·이력 질문이라는 데이터 구성과 일치합니다.</p><p>별도 실제 API 스모크에서는 다음처럼 도구 종류가 분리됐습니다.</p><table><thead><tr><th>질문</th><th>선택 도구</th><th>판정</th></tr></thead><tbody><tr><td>박현우가 담당한 미완료 액션 목록을 5개만</td><td>query_structured_memory(list)</td><td>도구 종류는 적절</td></tr><tr><td>현재 미완료 액션은 총 몇 개인가?</td><td>query_structured_memory(count)</td><td>도구는 적절, category 누락으로 오답</td></tr><tr><td>프로젝트 전체 현황 브리핑</td><td>get_project_overview</td><td>적절</td></tr><tr><td>김태호가 담당한 결정 목록</td><td>query_structured_memory(list)</td><td>간헐적 category 누락</td></tr></tbody></table></section>
<section class="panel"><h2>평가 후 발견된 P0 — 아직 수정하지 않음</h2><ol><li><strong>도구 인자 누락:</strong> “미완료 액션”에서 <code>category=action</code>을 빼 전체 memory 103건을 액션으로 답했다. DB 실측 action은 55건이다. “김태호 결정”에서도 category 누락이 비결정적으로 발생했다.</li><li><strong>완료 상태 데이터:</strong> 적재된 action의 <code>completed_at</code>이 전부 NULL이라 내용에 “완료”라고 쓰인 항목도 <code>completed=false</code> 목록에 나온다. 라우팅 변경만으로 해결할 수 없는 추출·정규화 문제다.</li><li><strong>0건 단정:</strong> 구조화 필드가 비어 0건일 때 원문에 완료 표현이 있어도 “없다”고 단정할 수 있다.</li></ol><p>권장 순서는 보고서 문항 검토 → 원인 분류 합의 → category를 필수 enum으로 만드는 도구 계약 → 완료 상태 적재 보정 → 0건 semantic 확인 → 같은 60문항과 별도 forward 세트를 재실행하는 것입니다.</p></section>
<section class="panel"><h2>현재 결론</h2><p><strong>agentic 구조 자체는 유지할 가치가 있습니다.</strong> 엄격 정답률과 출력 제어가 크게 좋아졌고 도구 종류도 forward 스모크에서 분리됐습니다. 하지만 구조화 count/list는 인자·데이터 정합성 때문에 현재 상태로 release하면 안 됩니다. feature flag로 격리한 채 P0를 고친 뒤 재평가하는 것이 맞습니다.</p></section>
</main></body></html>"""


def main() -> None:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    legacy = load_jsonl(args.results / "legacy_modu.jsonl") + load_jsonl(args.results / "legacy_csbot.jsonl")
    agentic = load_jsonl(args.results / "agentic_modu.jsonl") + load_jsonl(args.results / "agentic_csbot.jsonl")
    if len(legacy) != 60 or len(agentic) != 60:
        raise RuntimeError(f"expected 60+60 rows, got {len(legacy)}+{len(agentic)}")
    legacy_keys = [(row["corpus"], row["qid"], row["question"], row["reference_answer"], row.get("gold_source")) for row in legacy]
    agentic_keys = [(row["corpus"], row["qid"], row["question"], row["reference_answer"], row.get("gold_source")) for row in agentic]
    if legacy_keys != agentic_keys:
        raise RuntimeError("legacy and agentic rows do not describe the same evaluation set")
    args.docs.mkdir(parents=True, exist_ok=True)
    (args.docs / "AGENTIC_TOOL_ROUTING_MODU_EVAL_20260722.html").write_text(corpus_html("modu", legacy, agentic, root), encoding="utf-8")
    (args.docs / "AGENTIC_TOOL_ROUTING_CSBOT_EVAL_20260722.html").write_text(corpus_html("csbot", legacy, agentic, root), encoding="utf-8")
    (args.docs / "AGENTIC_TOOL_ROUTING_SYSTEM_EVAL_20260722.html").write_text(system_html(legacy, agentic, root), encoding="utf-8")


if __name__ == "__main__":
    main()
