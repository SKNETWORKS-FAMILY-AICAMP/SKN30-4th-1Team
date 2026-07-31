"""TASK-006 — 골든셋 평가 파이프라인(run_eval.py)의 결정론 단위 테스트.

LLM·DB·Docker 무접촉: 로더/pair 매칭/상태 검사/summary upsert/구성 토글/기권
판정/체인 판정/보상 복구 오케스트레이션을 가짜 객체로 검증한다.
"""
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "run_eval", _REPO / "backend" / "test" / "golden" / "run_eval.py")
run_eval = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("run_eval", run_eval)
_spec.loader.exec_module(run_eval)


# ── 로더 ─────────────────────────────────────────────────────────────────────

def test_loader_counts_and_tag_normalization():
    """60문항, 태그 정규화(hallu→hallucination), 코퍼스당 비환각 26·환각 4."""
    questions = run_eval.load_golden()
    assert len(questions) == 60
    assert all(q["tag"] != "hallu" for q in questions)  # 정규화 완료
    for corpus in ("modu", "csbot"):
        subset = [q for q in questions if q["corpus"] == corpus]
        assert len(subset) == 30
        assert sum(1 for q in subset if q["tag"] == "hallucination") == 4
        assert sum(1 for q in subset if q["tag"] != "hallucination") == 26
    # history=True 5문항에는 기대 체인 pair 매핑이 있다
    hist = [q for q in questions if q["expected_history_mode"]]
    assert len(hist) == 5
    assert all(q["expected_chain_pairs"] for q in hist)


def test_loader_pairs_reference_existing_pair_ids():
    pair_ids = {p["pair_id"] for p in run_eval.load_pairs()}
    for q in run_eval.load_golden():
        for pid in q["expected_chain_pairs"]:
            assert pid in pair_ids, f"{q['qid']}의 기대 pair {pid} 미정의"


# ── pair 매칭 ────────────────────────────────────────────────────────────────

def _rows(*contents, category="decision"):
    return [{"id": i + 1, "category": category, "content": c,
             "superseded_by": None, "date": f"2026-01-{i+1:02d}"}
            for i, c in enumerate(contents)]


_PAIR = {"pair_id": "P-T1", "corpus": "modu", "kind": "positive",
         "old_match": "이메일", "new_match": "소셜"}


def test_match_pairs_unique_success():
    rows = _rows("이메일 로그인 확정", "소셜 로그인 추가")
    resolved = run_eval.match_pairs([_PAIR], rows, "modu")
    assert resolved["P-T1"] == {"old_id": 1, "new_id": 2, "kind": "positive"}


@pytest.mark.parametrize("contents", [
    ("무관 내용", "소셜 로그인 추가"),                      # old 0건
    ("이메일 A", "이메일 B", "소셜 로그인 추가"),           # old 2건
])
def test_match_pairs_nonunique_hard_failure(contents):
    with pytest.raises(run_eval.PairMatchError) as exc:
        run_eval.match_pairs([_PAIR], _rows(*contents), "modu")
    assert "후보" in str(exc.value)  # 조용히 넘어가지 않고 후보를 출력


def test_match_pairs_negative_requires_only_old():
    pair = {"pair_id": "N-T1", "corpus": "modu", "kind": "negative",
            "old_match": "게시판형", "new_match": None}
    rows = _rows("게시판형 댓글로 구현")
    resolved = run_eval.match_pairs([pair], rows, "modu")
    assert resolved["N-T1"]["kind"] == "negative"
    assert resolved["N-T1"]["new_id"] is None


def test_match_pairs_date_inversion_rejected():
    rows = [{"id": 1, "category": "decision", "content": "이메일 확정",
             "superseded_by": None, "date": "2026-03-09"},
            {"id": 2, "category": "decision", "content": "소셜 추가",
             "superseded_by": None, "date": "2026-02-01"}]
    with pytest.raises(run_eval.PairMatchError):
        run_eval.match_pairs([_PAIR], rows, "modu")


# ── 구성-상태 정밀 검사 ──────────────────────────────────────────────────────

def test_check_state_pre_detects_partial_and_vector_loss():
    expected = {(1, 3), (2, 4)}
    # 부분 적용(pair 1개만 걸린 상태)은 pre에서 중단
    assert run_eval.check_state({(1, 3)}, expected, {1: True, 2: True}, "pre")
    # old 벡터 소실도 pre 위반
    assert run_eval.check_state(set(), expected, {1: True, 2: False}, "pre")
    # 정상 pre
    assert not run_eval.check_state(set(), expected, {1: True, 2: True}, "pre")


def test_check_state_post_requires_exact_set_and_vector_absence():
    expected = {(1, 3), (2, 4)}
    ok_presence = {1: False, 2: False}
    assert not run_eval.check_state({(1, 3), (2, 4)}, expected, ok_presence, "post")
    # 예상 외 관계 추가 → 위반
    assert run_eval.check_state({(1, 3), (2, 4), (9, 8)}, expected, ok_presence, "post")
    # 누락 → 위반
    assert run_eval.check_state({(1, 3)}, expected, ok_presence, "post")
    # old 벡터 잔존 → 위반
    assert run_eval.check_state({(1, 3), (2, 4)}, expected, {1: True, 2: False}, "post")


# ── summary writer ───────────────────────────────────────────────────────────

def _row(**kw):
    base = {"run_id": "r1", "date": "2026-07-18", "commit": "abc", "corpus": "modu",
            "config": "E0", "phase": "dev", "judge": "gpt-4o-mini", "n": 26,
            "context_precision": 0.8}
    base.update(kw)
    return base


def test_summary_upsert_key_includes_phase(tmp_path):
    """(run_id,corpus,config,phase) 키 — dev와 final은 별도 행(리뷰 2-P2)."""
    writer = run_eval.SummaryWriter(tmp_path / "summary.csv")
    writer.upsert(_row(phase="dev"))
    writer.upsert(_row(phase="final", judge="gpt-4o"))
    rows = writer._load()
    assert len(rows) == 2


def test_summary_upsert_merges_blank_fields(tmp_path):
    """audit가 빈 필드만 채워도 measure가 쓴 지표를 지우지 않는다."""
    writer = run_eval.SummaryWriter(tmp_path / "summary.csv")
    writer.upsert(_row(context_precision=0.8))
    writer.upsert({"run_id": "r1", "corpus": "modu", "config": "E0",
                   "phase": "dev", "routing_accuracy": 0.9})
    rows = writer._load()
    assert len(rows) == 1
    assert rows[0]["context_precision"] == "0.8"
    assert rows[0]["routing_accuracy"] == "0.9"


def test_summary_judge_conflict_rejected(tmp_path):
    """같은 키에 다른 judge upsert는 거부 — --overwrite로만 교체(리뷰 3-P2)."""
    writer = run_eval.SummaryWriter(tmp_path / "summary.csv")
    writer.upsert(_row(judge="gpt-4o-mini"))
    with pytest.raises(RuntimeError, match="judge 충돌"):
        writer.upsert(_row(judge="gpt-4o"))
    writer.upsert(_row(judge="gpt-4o", context_precision=0.9), overwrite=True)
    assert writer._load()[0]["judge"] == "gpt-4o"


# ── 구성 토글(복원형) ────────────────────────────────────────────────────────

def test_config_overrides_sequential_transitions_and_restore():
    """E0→E1→E2 연속 전환 시 recency 전역값이 0→0→0.2로 관측되고 원값 복원
    (리뷰 1-1: E2가 이전 구성의 0을 물려받는 결함 방지)."""
    import backend.retriever.qa_engine as qa_engine
    original = qa_engine.CHUNK_RECENCY_WEIGHT
    observed = []
    for config in ("E0", "E1", "E2-e2e"):
        with run_eval.config_overrides(config):
            observed.append(qa_engine.CHUNK_RECENCY_WEIGHT)
    assert observed == [0.0, 0.0, 0.2]
    assert qa_engine.CHUNK_RECENCY_WEIGHT == original  # 복원


def test_config_overrides_restores_on_exception():
    import backend.retriever.qa_engine as qa_engine
    original = qa_engine.CHUNK_RECENCY_WEIGHT
    with pytest.raises(ValueError):
        with run_eval.config_overrides("E2-e2e"):
            raise ValueError("측정 중 실패")
    assert qa_engine.CHUNK_RECENCY_WEIGHT == original


# ── 기권·체인 판정 ───────────────────────────────────────────────────────────

def test_abstain_patterns():
    assert run_eval.is_abstain("해당 내용은 기록에서 확인되지 않는다.")
    assert run_eval.is_abstain("제공된 기록에 없는 정보입니다.")
    assert not run_eval.is_abstain("총 예산은 3억 원이다.")


def test_chain_included_requires_both_phrases():
    pair = {"old_match": "이메일", "new_match": "소셜"}
    assert run_eval.chain_included(["이메일 로그인 확정", "소셜 로그인 추가"], pair)
    assert not run_eval.chain_included(["소셜 로그인 추가"], pair)  # old 누락


# ── R0-vec 수집기: memory 벡터 배제 ─────────────────────────────────────────

def test_r0_vec_filters_to_document_chunks(monkeypatch):
    """R0-vec 호출에 item_type=document 필터가 실제로 걸린다(리뷰 1-5)."""
    import backend.retriever.qa_engine as qa_engine
    store = MagicMock()
    store.similarity_search_with_score.return_value = []
    monkeypatch.setattr(qa_engine, "_get_vectorstore", lambda: store)

    run_eval.collect_r0_vec(1, "질문")

    kwargs = store.similarity_search_with_score.call_args.kwargs
    assert {"item_type": "document"} in kwargs["filter"]["$and"]


# ── 마커: phase 분리 ─────────────────────────────────────────────────────────

def test_marker_path_separates_phase():
    """dev 완료 마커가 final 실행을 건너뛰게 하지 않는다(리뷰 2-P2)."""
    dev = run_eval.marker_path("r1", "modu", "E0", "dev")
    final = run_eval.marker_path("r1", "modu", "E0", "final")
    assert dev != final


# ── --no-langsmith 경계 ──────────────────────────────────────────────────────

def test_disable_langsmith_removes_client_env(monkeypatch):
    """flag가 tracing·client 환경 자체를 제거해 키 없이 로컬 완주 가능(리뷰 2-P3)."""
    monkeypatch.setenv("LANGSMITH_API_KEY", "x")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    run_eval.disable_langsmith()
    import os
    assert os.environ.get("LANGSMITH_TRACING") == "false"
    assert "LANGSMITH_API_KEY" not in os.environ


# ── pairs 보상 복구 오케스트레이션 ───────────────────────────────────────────

def _fake_subprocess(sequence):
    """호출된 커맨드의 서브커맨드명을 기록하고 지정된 returncode를 돌려주는 가짜."""
    calls = []

    def fake_run(cmd, **kwargs):
        step = next((c for c in cmd if not c.startswith("-")
                     and not c.endswith("python") and not c.endswith(".py")
                     and c not in ("docker",)), "?")
        calls.append(step)
        code = sequence.get(step, 0)
        if isinstance(code, list):
            code = code.pop(0)
        return MagicMock(returncode=code)

    return calls, fake_run


def _pairs_args(corpus="modu"):
    ns = MagicMock()
    ns.corpus, ns.phase, ns.runid = corpus, "dev", "r1"
    return ns


def test_pairs_worker_failure_triggers_restore_and_recheck(tmp_path, monkeypatch):
    """worker 실패 → restore → pre-state 재검증 통과 시 '복구 완료'로 중단
    (리뷰 2-P1a + 3-P1b: 복구 후 재검증까지가 복구 완료의 정의)."""
    monkeypatch.setattr(run_eval, "STATE_DIR", tmp_path)
    (tmp_path / "modu").mkdir(parents=True)
    (tmp_path / "modu" / "checkpoint.sql").write_text("dump")
    (tmp_path / "modu" / "checkpoint_chroma").mkdir()
    (tmp_path / "modu" / "checkpoint.ok").write_text("ok")   # 유효 체크포인트

    # 멱등 post-check(1=post 아님) → pre-check(0) → worker 실패 → restore → 재검증(0)
    calls, fake_run = _fake_subprocess({"_pairs-worker": 1,
                                        "_state-check": [1, 0, 0], "restore": 0})
    monkeypatch.setattr(run_eval.subprocess, "run", fake_run)

    with pytest.raises(SystemExit) as exc:
        run_eval.cmd_pairs(_pairs_args())
    assert "복구 완료" in str(exc.value)
    assert calls == ["_state-check", "_state-check", "_pairs-worker",
                     "restore", "_state-check"]
    assert not run_eval.invalid_marker("modu").exists()


def test_pairs_recheck_failure_seals_invalid(tmp_path, monkeypatch):
    """복구 후 재검증 실패 시 run을 invalid로 봉인한다."""
    monkeypatch.setattr(run_eval, "STATE_DIR", tmp_path)
    (tmp_path / "modu").mkdir(parents=True)
    (tmp_path / "modu" / "checkpoint.sql").write_text("dump")
    (tmp_path / "modu" / "checkpoint_chroma").mkdir()
    (tmp_path / "modu" / "checkpoint.ok").write_text("ok")

    # post-check(1) → pre-check(0) → worker 실패 → restore → 재검증 실패(1)
    calls, fake_run = _fake_subprocess({"_pairs-worker": 1,
                                        "_state-check": [1, 0, 1], "restore": 0})
    monkeypatch.setattr(run_eval.subprocess, "run", fake_run)

    with pytest.raises(SystemExit) as exc:
        run_eval.cmd_pairs(_pairs_args())
    assert "invalid" in str(exc.value)
    assert run_eval.invalid_marker("modu").exists()


def test_pairs_idempotent_when_already_post(tmp_path, monkeypatch):
    """이미 post 상태면(중단 재개 등) pairs를 재적용하지 않고 건너뛴다(P1-C)."""
    monkeypatch.setattr(run_eval, "STATE_DIR", tmp_path)
    monkeypatch.setattr(run_eval, "RESULTS_DIR", tmp_path)
    (tmp_path / "modu").mkdir(parents=True)
    # 이 run의 coverage가 이미 존재 → 복구 경로도 불필요(R2-005)
    (tmp_path / "pair_coverage_modu_dev_r1.csv").write_text("pair_id\n")
    # 첫 _state-check(post)가 통과(0) → 즉시 건너뜀, worker 미호출.
    # 단, post 상태 프로젝트 메모리는 보장해야 하므로 pmem은 재생성한다(C-001).
    calls, fake_run = _fake_subprocess({"_state-check": 0})
    monkeypatch.setattr(run_eval.subprocess, "run", fake_run)

    run_eval.cmd_pairs(_pairs_args())            # SystemExit 없이 정상 반환
    assert calls == ["_state-check", "pmem"]
    assert "_pairs-worker" not in calls


def test_pairs_post_state_recovers_missing_coverage(tmp_path, monkeypatch):
    """R2-005: post 전환 후 coverage 기록 전에 중단된 재개 — 상태 변경 없이
    coverage만 --coverage-only worker로 재생성한다."""
    monkeypatch.setattr(run_eval, "STATE_DIR", tmp_path)
    monkeypatch.setattr(run_eval, "RESULTS_DIR", tmp_path)
    (tmp_path / "modu").mkdir(parents=True)

    captured = []

    def fake_run(cmd, **kwargs):
        captured.append(cmd)
        return MagicMock(returncode=0)           # post-check 통과 + 복구 성공

    monkeypatch.setattr(run_eval.subprocess, "run", fake_run)
    run_eval.cmd_pairs(_pairs_args())            # SystemExit 없이 정상 반환

    cov_calls = [c for c in captured if "--coverage-only" in c]
    assert len(cov_calls) == 1
    assert "_pairs-worker" in cov_calls[0]
    assert "--phase" in cov_calls[0] and "dev" in cov_calls[0]
    assert "--runid" in cov_calls[0] and "r1" in cov_calls[0]
    # 상태 변경 경로(checkpoint/restore/적용 worker)는 호출되지 않음
    assert not any("checkpoint" in c or "restore" in c for c in captured)
    assert all("--coverage-only" in c for c in captured if "_pairs-worker" in c)


def test_pairs_checkpoint_guard_blocks_dirty_state(tmp_path, monkeypatch):
    """체크포인트 부재 + pre-state 위반이면 체크포인트를 만들지 않고 중단
    (리뷰 3-P1a: 오염 상태의 체크포인트 확정 방지)."""
    monkeypatch.setattr(run_eval, "STATE_DIR", tmp_path)
    (tmp_path / "modu").mkdir(parents=True)
    # post-check(1=아님) → 체크포인트 없음 → checkpoint 단계 호출 → 그 안 _state-check 실패
    calls, fake_run = _fake_subprocess({"_state-check": 1, "checkpoint": 1})
    monkeypatch.setattr(run_eval.subprocess, "run", fake_run)

    with pytest.raises(SystemExit):
        run_eval.cmd_pairs(_pairs_args())
    assert calls == ["_state-check", "checkpoint"]      # worker까지 가지 않음
    assert not (tmp_path / "modu" / "checkpoint.sql").exists()


def test_checkpoint_guard_direct(tmp_path, monkeypatch):
    """checkpoint 커맨드 자체도 pre-state 검증 실패 시 파일을 만들지 않는다."""
    monkeypatch.setattr(run_eval, "STATE_DIR", tmp_path)
    (tmp_path / "modu").mkdir(parents=True)
    calls, fake_run = _fake_subprocess({"_state-check": 1})
    monkeypatch.setattr(run_eval.subprocess, "run", fake_run)

    with pytest.raises(SystemExit) as exc:
        run_eval.cmd_checkpoint(_pairs_args())
    assert "오염 상태" in str(exc.value)
    assert not (tmp_path / "modu" / "checkpoint.sql").exists()


def test_pairs_worker_sql_failure_rolls_back(tmp_path, monkeypatch):
    """worker의 UPDATE 중간 실패는 트랜잭션 rollback(반쪽 SQL 상태 금지)."""
    monkeypatch.setattr(run_eval, "STATE_DIR", tmp_path)
    (tmp_path / "modu").mkdir(parents=True)
    (tmp_path / "modu" / "project_id").write_text("1")

    rows = _rows("이메일 로그인 확정", "소셜 로그인 추가")
    monkeypatch.setattr(run_eval, "fetch_memory_rows", lambda pid: rows)
    monkeypatch.setattr(run_eval, "load_pairs", lambda: [_PAIR])
    monkeypatch.setattr(run_eval, "require_openai_key", lambda: None)

    cursor = MagicMock()
    cursor.rowcount = 0                     # UPDATE 실패 시나리오
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    conn.cursor.return_value.__exit__.return_value = False
    import backend.db.mysql as mysql_mod
    monkeypatch.setattr(mysql_mod, "get_connection", lambda: conn)

    ns = MagicMock()
    ns.corpus, ns.phase, ns.runid = "modu", "dev", "r1"
    ns.coverage_only = False                # MagicMock 속성은 truthy — 명시 필요
    with pytest.raises(RuntimeError, match="UPDATE 실패"):
        run_eval.cmd_pairs_worker(ns)
    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()


# ── 실행 로그 (tee_output) ───────────────────────────────────────────────────

def _emit_fd1(msg: str) -> None:
    """fd 1에 직접 쓴다 — 실서비스의 print(sys.stdout=fd1)와 동일 경로.
    (pytest 기본 fd 캡처는 sys.stdout 객체를 교체하므로 print로는 fd 경로를
    검증할 수 없어 os.write(1)로 실제 fd를 친다.)"""
    import os
    os.write(1, (msg + "\n").encode("utf-8"))


def test_tee_output_captures_parent_and_child_with_timestamps(tmp_path):
    """부모(fd1) + 자식 subprocess 출력이 [시각] 접두어와 함께 한 파일에 모인다."""
    import re
    log = tmp_path / "run.log"
    with run_eval.tee_output(log):
        _emit_fd1("부모-라인")
        run_eval.subprocess.run(["echo", "자식-라인"])   # fd 상속 → 캡처
    text = log.read_text(encoding="utf-8")
    assert "부모-라인" in text
    assert "자식-라인" in text
    assert re.search(r"\[\d\d:\d\d:\d\d\] 부모-라인", text)  # 줄 단위 타임스탬프
    assert "run start" in text and "run end" in text      # 배너
    # fd가 원복되어 이후 출력이 로그로 새지 않는다
    _emit_fd1("복원-확인")
    assert "복원-확인" not in log.read_text(encoding="utf-8")


def test_tee_output_appends_across_runs(tmp_path):
    """같은 로그 경로로 두 번 실행하면 이어붙는다(이력 보존)."""
    log = tmp_path / "run.log"
    with run_eval.tee_output(log):
        _emit_fd1("첫-실행")
    with run_eval.tee_output(log):
        _emit_fd1("둘-실행")
    text = log.read_text(encoding="utf-8")
    assert "첫-실행" in text and "둘-실행" in text
    assert text.count("run start") == 2


def test_run_log_path_naming_is_stable():
    p = run_eval.run_log_path("modu", "final", "20260718-0930")
    assert p.name == "run_modu_final_20260718-0930.log"
    assert p.parent == run_eval.RESULTS_DIR


# ── Materials & Methods (render_methods / cmd_methods) ───────────────────────

def test_render_methods_records_asrun_facts():
    """as-run 방법론: run_id·모델·구성 매트릭스·측정축·상태 모델·재현 커맨드."""
    md = run_eval.render_methods("RID-1", "final")
    assert "Materials & Methods" in md
    assert "run_id: `RID-1`" in md
    for token in ("R0-both", "E2-e2e", "context_precision", "checkpoint",
                  run_eval.PHASE_JUDGE["final"]):   # judge 통일: gpt-4.1-mini
        assert token in md, token
    assert "| modu |" in md and "| csbot |" in md          # 코퍼스별 재료 행
    for pid in ("P-M1", "P-M2", "P-C1", "N-C1", "N-M1"):   # 골든 pair 전건
        assert pid in md, pid
    assert "RUNID=RID-1" in md and "--runid $RUNID" in md  # 재현 커맨드


def test_render_methods_sample_sizes_match_golden():
    """재료 표의 표본 수가 골든 로더 집계와 일치(history 5·conflict_negative 4)."""
    questions = run_eval.load_golden()
    md = run_eval.render_methods("RID-2", "dev")
    for corpus in ("modu", "csbot"):
        cq = [q for q in questions if q["corpus"] == corpus]
        n_hist = sum(1 for q in cq if q["expected_history_mode"])
        n_confneg = sum(1 for q in cq if q["tag"] == "conflict_negative")
        # 코퍼스 행에 해당 코퍼스의 history·conflict_negative 카운트가 들어간다
        row = next(line for line in md.splitlines()
                   if line.startswith(f"| {corpus} |"))
        assert f"| {n_hist} |" in row and f"| {n_confneg} |" in row
    assert sum(1 for q in questions if q["expected_history_mode"]) == 5


def test_cmd_methods_writes_file(tmp_path, monkeypatch):
    monkeypatch.setattr(run_eval, "RESULTS_DIR", tmp_path)
    ns = MagicMock()
    ns.runid, ns.phase = "RID-3", "dev"
    run_eval.cmd_methods(ns)
    out = tmp_path / "METHODS_RID-3.md"
    assert out.exists() and "Materials & Methods" in out.read_text(encoding="utf-8")


# ── 리뷰 수정 회귀 테스트 (TASK-006 코드리뷰 P1/P2) ──────────────────────────

def test_db_name_is_per_corpus():
    """P1-A: 코퍼스별 스키마로 격리 → 전체-DB 스냅샷이 서로를 덮지 않는다."""
    assert run_eval.db_name("modu") == "paim_modu"
    assert run_eval.db_name("csbot") == "paim_csbot"
    assert run_eval.db_name("modu") != run_eval.db_name("csbot")


def test_suggestion_target_parsing():
    """P2-E: supersede 제안의 target(new decision) 추출 — dict/JSON/누락/불량."""
    assert run_eval._suggestion_target({"evidence": {"superseding_memory_id": 42}}) == 42
    assert run_eval._suggestion_target(
        {"evidence": '{"superseding_memory_id": "7"}'}) == 7
    assert run_eval._suggestion_target({"evidence": {"other": 1}}) is None
    assert run_eval._suggestion_target({"evidence": "not-json"}) is None
    assert run_eval._suggestion_target({}) is None


def test_pairs_passes_phase_and_runid_to_worker(tmp_path, monkeypatch):
    """P1-E: worker에 phase·runid가 전달돼 커버리지 CSV가 이 실행에 귀속된다."""
    monkeypatch.setattr(run_eval, "STATE_DIR", tmp_path)
    (tmp_path / "modu").mkdir(parents=True)
    (tmp_path / "modu" / "checkpoint.sql").write_text("dump")
    (tmp_path / "modu" / "checkpoint_chroma").mkdir()
    (tmp_path / "modu" / "checkpoint.ok").write_text("ok")

    captured = []
    state_calls = {"n": 0}

    def fake_run(cmd, **kwargs):
        captured.append(cmd)
        if "_state-check" in cmd:
            state_calls["n"] += 1
            # 1번째=post-check(1=post 아님) → 진행, 이후 pre·final post=0(통과)
            return MagicMock(returncode=1 if state_calls["n"] == 1 else 0)
        return MagicMock(returncode=0)               # checkpoint/worker 성공

    monkeypatch.setattr(run_eval.subprocess, "run", fake_run)
    ns = MagicMock()
    ns.corpus, ns.phase, ns.runid = "modu", "final", "RID-9"
    run_eval.cmd_pairs(ns)

    worker_cmd = next(c for c in captured if "_pairs-worker" in c)
    assert "--phase" in worker_cmd and "final" in worker_cmd
    assert "--runid" in worker_cmd and "RID-9" in worker_cmd


def test_measure_resume_rejects_judge_mismatch(tmp_path, monkeypatch):
    """P2-D: --resume이 다른 judge의 완료 마커를 조용히 재사용하지 않는다."""
    monkeypatch.setattr(run_eval, "STATE_DIR", tmp_path)
    marker = run_eval.marker_path("RID", "modu", "E0", "dev")
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("gpt-4o")                      # 기존 judge
    ns = MagicMock()
    ns.corpus, ns.config, ns.phase, ns.runid = "modu", "E0", "dev", "RID"
    ns.resume, ns.overwrite, ns.judge = True, False, "gpt-4o-mini"  # 다른 judge 요청
    with pytest.raises(SystemExit) as exc:
        run_eval.cmd_measure(ns)
    assert "judge 불일치" in str(exc.value)


def test_report_filters_by_runid(tmp_path, monkeypatch, capsys):
    """P2-C: report가 run_id로 한정 → 여러 run 수치가 한 표에 섞이지 않는다."""
    monkeypatch.setattr(run_eval, "RESULTS_DIR", tmp_path)
    w = run_eval.SummaryWriter(tmp_path / "summary.csv")
    w.upsert({"run_id": "OLD", "corpus": "modu", "config": "E0", "phase": "dev",
              "judge": "gpt-4o-mini", "context_precision": "0.111"})
    w.upsert({"run_id": "NEW", "corpus": "modu", "config": "E0", "phase": "dev",
              "judge": "gpt-4o-mini", "context_precision": "0.999"})
    ns = MagicMock()
    ns.runid = "NEW"
    run_eval.cmd_report(ns)
    out = capsys.readouterr().out
    assert "run_id=NEW" in out and "0.999" in out
    assert "0.111" not in out                         # 다른 run은 제외


def test_render_methods_uses_asrun_judge(tmp_path, monkeypatch):
    """P2-B: METHODS가 summary의 실제 judge를 반영(기본값 고정 아님)."""
    monkeypatch.setattr(run_eval, "RESULTS_DIR", tmp_path)
    w = run_eval.SummaryWriter(tmp_path / "summary.csv")
    w.upsert({"run_id": "RID", "corpus": "modu", "config": "E0", "phase": "final",
              "judge": "gpt-4o-custom", "context_precision": "0.5"})
    md = run_eval.render_methods("RID", "final")
    assert "gpt-4o-custom" in md and "summary 실측" in md


def test_tee_output_survives_logfile_failure_without_hang(tmp_path):
    """P2-F: 로그 sink가 죽어도 파이프를 계속 배출(자식 데드락 방지)."""
    log = tmp_path / "run.log"
    t = run_eval.tee_output(log)
    t.__enter__()

    class Boom:
        def write(self, *a):
            raise OSError("disk full")
        def flush(self):
            pass
        def close(self):
            pass

    try:
        t._logfile = Boom()                           # 이후 모든 로그 write 실패
        _emit_fd1("실패-후-라인")
        run_eval.subprocess.run(["echo", "child-after-failure"])  # fd 상속, 블로킹 X
    finally:
        t.__exit__(None, None, None)
    assert "logfile" in t._sink_errors                # 실패 기록됨(무시 아님)


def test_restore_requires_checkpoint_ok(tmp_path, monkeypatch):
    """P1-D: 완성 표식(.ok) 없으면 restore가 손상 스냅샷을 쓰지 않고 중단."""
    monkeypatch.setattr(run_eval, "STATE_DIR", tmp_path)
    (tmp_path / "modu").mkdir(parents=True)
    (tmp_path / "modu" / "checkpoint.sql").write_text("dump")   # sql만 존재(.ok 없음)
    (tmp_path / "modu" / "checkpoint_chroma").mkdir()
    ns = MagicMock()
    ns.corpus = "modu"
    with pytest.raises(SystemExit) as exc:
        run_eval.cmd_restore(ns)
    assert "유효한 체크포인트 없음" in str(exc.value)


def test_corpus_transcripts_excludes_non_dated_docs(tmp_path, monkeypatch):
    """실측 1회차 결함 회귀: QA 테스트셋·타임라인 .md가 코퍼스로 적재되면 gold
    답변이 검색 대상이 된다(평가 오염). 날짜 접두(YYYY-MM-DD) 회의록만 적재."""
    d = tmp_path / "corpus"
    d.mkdir()
    (d / "2026-03-02_킥오프.md").write_text("회의록")
    (d / "2026-03-09_결정.md").write_text("회의록")
    (d / "modu_rag_qa_testset_and_person_timeline.md").write_text("gold 답변")
    (d / "2026-13-99_날짜아님.md").write_text("불량 날짜")
    monkeypatch.setattr(run_eval, "HERE", tmp_path)
    monkeypatch.setitem(run_eval.CORPORA, "modu", {"dir": "corpus", "qa": ""})
    names = [p.name for p in run_eval.corpus_transcripts("modu")]
    assert names == ["2026-03-02_킥오프.md", "2026-03-09_결정.md"]


# ── 리뷰 라운드 2 회귀 ───────────────────────────────────────────────────────

def test_chain_source_excludes_chroma_chunks():
    """R2-001: 체인 판정 원천은 MySQL 이력 행 content만 — 원문 Chroma 청크에
    결정 문구가 우연히 있어도 통과하지 않는다."""
    pair = {"old_match": "이메일 로그인 확정", "new_match": "소셜 로그인 추가"}
    debug_chroma_only = {"mysql_rows": [],
                         "chroma_chunks": [{"text_full":
                                            "이메일 로그인 확정 … 소셜 로그인 추가"}]}
    assert run_eval.chain_included(
        run_eval.chain_source_texts(debug_chroma_only), pair) is False
    debug_mysql = {"mysql_rows": [{"content": "이메일 로그인 확정"},
                                  {"content": "소셜 로그인 추가"}],
                   "chroma_chunks": []}
    assert run_eval.chain_included(
        run_eval.chain_source_texts(debug_mysql), pair) is True
    # R0-both 등 debug["mysql_rows"]가 목록이 아닌 경우(카운트)도 안전
    assert run_eval.chain_source_texts({"mysql_rows": 3}) == []


def test_measure_resume_overwrite_judge_mismatch_remeasures(tmp_path, monkeypatch):
    """R2-002: judge 불일치 + --overwrite면 마커를 건너뛰지 않고 재측정 본문으로
    진행한다(README의 '--overwrite로 교체' 계약)."""
    monkeypatch.setattr(run_eval, "STATE_DIR", tmp_path)
    monkeypatch.setattr(run_eval, "RESULTS_DIR", tmp_path)
    marker = run_eval.marker_path("RID", "modu", "E0", "dev")
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("gpt-4o")                      # 기존 judge

    def sentinel(corpus):                            # 측정 본문 진입 증명
        raise RuntimeError("측정 본문 도달")

    monkeypatch.setattr(run_eval, "setup_env", sentinel)
    ns = MagicMock()
    ns.corpus, ns.config, ns.phase, ns.runid = "modu", "E0", "dev", "RID"
    ns.resume, ns.overwrite, ns.judge = True, True, "gpt-4o-mini"
    with pytest.raises(RuntimeError, match="측정 본문 도달"):
        run_eval.cmd_measure(ns)
    # 재측정 진입 시 마커는 무효화로 제거됐다(R6-001) — 실패해도 '완료'로 안 남음
    assert not marker.exists()
    # judge 일치면 여전히 건너뜀(setup_env 미도달 = 예외 없음). 마커 재생성 후 확인.
    marker.write_text("gpt-4o")
    ns.judge = "gpt-4o"
    run_eval.cmd_measure(ns)
    assert marker.exists()                           # 건너뜀 경로는 마커 보존


def test_tee_pump_survives_non_oserror_sink(tmp_path):
    """R2-003: 닫힌 파일류의 ValueError 등 OSError 외 sink 예외에도 pump가
    EOF까지 배출을 계속하고 정상 종료한다."""
    log = tmp_path / "run.log"
    t = run_eval.tee_output(log)
    t.__enter__()

    class ClosedFile:
        def write(self, *a):
            raise ValueError("I/O operation on closed file")
        def flush(self):
            pass
        def close(self):
            pass

    try:
        t._logfile = ClosedFile()
        _emit_fd1("밸류에러-후-라인")
        run_eval.subprocess.run(["echo", "child-after-valueerror"])  # 블로킹 X
    finally:
        t.__exit__(None, None, None)
    assert not t._thread.is_alive()                  # EOF까지 배출 후 종료
    assert "logfile" in t._sink_errors


def test_tee_exit_keeps_sinks_open_while_pump_alive(tmp_path):
    """R2-003: join 시간 초과로 pump가 살아 있으면 sink를 닫지 않는다
    (EOF 전 폐쇄로 인한 로그 절단·BrokenPipe 방지)."""
    import os
    log = tmp_path / "run.log"
    t = run_eval.tee_output(log)
    t.__enter__()
    real_thread = t._thread

    class StuckThread:                               # join 후에도 살아있는 pump
        def join(self, timeout=None):
            pass
        def is_alive(self):
            return True

    t._thread = StuckThread()
    try:
        _emit_fd1("느린-배출-라인")
        t.__exit__(None, None, None)
        assert "pump" in t._sink_errors              # 경고 기록
        assert not t._logfile.closed                 # EOF 전 폐쇄 금지
    finally:
        real_thread.join(timeout=5)                  # 실제 pump는 EOF로 종료
        t._logfile.close()
        os.close(t._console)


def test_pairs_worker_coverage_only_touches_nothing(tmp_path, monkeypatch):
    """R3-001+R4-001: --coverage-only는 MySQL·Chroma·OpenAI 키 어느 I/O 경계에도
    접촉하지 않고 적재 덤프(memory_rows)만으로 coverage CSV를 재생성한다.
    모든 경계에 실패 sentinel — DB 조회·벡터 I/O가 추가되는 회귀는 즉시 실패."""
    monkeypatch.setattr(run_eval, "STATE_DIR", tmp_path)
    monkeypatch.setattr(run_eval, "RESULTS_DIR", tmp_path)
    (tmp_path / "modu").mkdir(parents=True)
    dump = {"project_id": 1,
            "memory_rows": _rows("이메일 로그인 확정", "소셜 로그인 추가"),
            "suggestions": [], "hook_log": [{"status": "called"}]}
    (tmp_path / "modu" / "ingest_dump.json").write_text(
        json.dumps(dump, ensure_ascii=False))
    monkeypatch.setattr(run_eval, "load_pairs", lambda: [_PAIR])

    key_calls = []
    monkeypatch.setattr(run_eval, "require_openai_key",
                        lambda: key_calls.append(1))

    def forbid(name):                                # 모든 I/O 경계 차단 sentinel
        def _fail(*a, **k):
            raise AssertionError(f"coverage-only가 {name}에 접촉했다")
        return _fail

    import backend.db.mysql as mysql_mod
    import backend.db.chroma as chroma_mod
    import backend.retriever.memory_vector as mv_mod
    monkeypatch.setattr(mysql_mod, "get_connection", forbid("MySQL"))
    monkeypatch.setattr(chroma_mod, "get_collection", forbid("Chroma"))
    monkeypatch.setattr(mv_mod, "delete_memory_vector", forbid("벡터 삭제"))

    ns = MagicMock()
    ns.corpus, ns.phase, ns.runid = "modu", "dev", "r1"
    ns.coverage_only = True
    run_eval.cmd_pairs_worker(ns)                    # sentinel 미발화로 완주

    assert not key_calls                             # 키 검사 미호출
    cov = tmp_path / "pair_coverage_modu_dev_r1.csv"
    assert cov.exists()
    assert "P-T1" in cov.read_text(encoding="utf-8")


def test_pair_coverage_write_failure_keeps_final_file(tmp_path):
    """R3-002: 기록 중 실패 시 기존 최종 CSV는 무손상, 새 최종 파일·tmp 잔재도
    생기지 않는다 — tmp→replace 원자 게시를 실패 주입으로 고정."""
    dump = {"suggestions": [], "hook_log": []}

    class ExplodingDict(dict):
        def items(self):
            raise RuntimeError("기록 중 실패")

    cov = tmp_path / "pair_coverage_modu_dev_r1.csv"
    cov.write_text("기존-완성본\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="기록 중 실패"):
        run_eval.write_pair_coverage(cov, ExplodingDict(), dump)
    assert cov.read_text(encoding="utf-8") == "기존-완성본\n"   # 최종본 무손상

    cov2 = tmp_path / "pair_coverage_modu_dev_r2.csv"
    with pytest.raises(RuntimeError, match="기록 중 실패"):
        run_eval.write_pair_coverage(cov2, ExplodingDict(), dump)
    assert not cov2.exists()                         # 새 최종 파일 미생성
    assert list(tmp_path.glob("*.tmp")) == []        # tmp 잔재 정리(추적 디렉터리)


def test_pair_coverage_preserves_global_hook_status(tmp_path):
    """R2-004: 전역 hook 상태 분포가 커밋되는 CSV에 남되(별도 컬럼) pair 판정은
    오염되지 않는다. 기록은 원자적(R2-005 — tmp 잔재 없음)."""
    import csv as csv_mod
    resolved = {"P-1": {"kind": "positive", "old_id": 1, "new_id": 2}}
    dump = {"suggestions": [],
            "hook_log": [{"status": "error"}, {"status": "called"},
                         {"status": "error"}]}
    cov = tmp_path / "pair_coverage_modu_dev_r1.csv"
    hook_status = run_eval.write_pair_coverage(cov, resolved, dump)
    assert hook_status == {"error": 2, "called": 1}
    with open(cov, encoding="utf-8") as f:
        rows = list(csv_mod.DictReader(f))
    assert rows[0]["detector_result"] == "miss"      # error가 판정을 오염 안 함
    assert '"error": 2' in rows[0]["global_hook_status"]
    assert not cov.with_name(cov.name + ".tmp").exists()  # 원자적 기록


# ── 라운드 5: 부분 평균 게시 차단 + 문서·as-run 기본값 정합 ──────────────────

def test_reject_partial_ragas_blocks_nan():
    """R5-001: 필수 지표 컬럼에 NaN(실패 job)이 있으면 게시 전에 예외 —
    mean(skipna)의 조용한 부분 평균이 summary·마커로 기록되지 않는다."""
    pd = pytest.importorskip("pandas")
    col_map = {"llm_context_precision_with_reference": "context_precision",
               "context_recall": "context_recall"}
    ok = pd.DataFrame({"llm_context_precision_with_reference": [1.0, 0.5],
                       "context_recall": [1.0, 1.0]})
    run_eval.reject_partial_ragas(ok, col_map)  # 완전한 결과는 통과
    bad = pd.DataFrame({"llm_context_precision_with_reference": [1.0, float("nan")],
                        "context_recall": [1.0, 1.0]})
    with pytest.raises(RuntimeError, match="부분 평균"):
        run_eval.reject_partial_ragas(bad, col_map)
    # 지표 외 컬럼(user_input 등)의 NaN은 무관
    meta = pd.DataFrame({"user_input": [None], "context_recall": [1.0]})
    run_eval.reject_partial_ragas(meta, col_map)


def test_ragas_score_aborts_before_publish_on_nan(monkeypatch):
    """R5-001: evaluate가 NaN을 돌려주면 ragas_score가 예외로 중단 —
    cmd_measure의 게시(summary·마커·상세 CSV)는 전부 그 뒤라 실행되지 않는다.
    ragas 내부 구성요소를 전부 가짜로 대체해 네트워크·임시파일 무접촉(hermetic)."""
    pd = pytest.importorskip("pandas")
    run_eval._install_vertexai_shim()   # ragas 임포트 전 필수(하네스와 동일)
    ragas_mod = pytest.importorskip("ragas")
    import ragas.llms as ragas_llms
    import ragas.metrics as ragas_metrics
    import openai
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-dummy")

    class _FakeResult:
        def to_pandas(self):
            return pd.DataFrame(
                {"llm_context_precision_with_reference": [1.0, float("nan")],
                 "context_recall": [1.0, 1.0]})

    # 실제 클라이언트·judge·지표 생성을 우회(AsyncOpenAI가 임시파일을 만들어
    # read-only 환경에서 실패하던 문제도 함께 제거).
    monkeypatch.setattr(openai, "AsyncOpenAI", lambda **kw: object())
    monkeypatch.setattr(ragas_llms, "llm_factory", lambda *a, **kw: object())
    monkeypatch.setattr(ragas_metrics, "LLMContextPrecisionWithReference",
                        lambda **kw: object())
    monkeypatch.setattr(ragas_metrics, "LLMContextRecall", lambda **kw: object())
    monkeypatch.setattr(ragas_mod, "EvaluationDataset",
                        type("_ED", (), {"from_list": staticmethod(lambda x: x)}))
    monkeypatch.setattr(ragas_mod, "evaluate", lambda **kw: _FakeResult())
    rows = [{"tag": "decision", "question": "q1", "contexts": ["c"],
             "reference": "r"},
            {"tag": "decision", "question": "q2", "contexts": ["c"],
             "reference": "r"}]
    with pytest.raises(RuntimeError, match="부분 평균"):
        run_eval.ragas_score(rows, "gpt-4.1-mini", False, 1)
    assert "context_precision" not in rows[0]  # 문항별 점수 합류도 미실행


def test_ragas_score_raises_judge_max_tokens(monkeypatch):
    """judge max_tokens 상향: ragas 기본 1024는 E0 원본 답변 faithfulness의
    진술 분해 출력이 잘려 IncompleteOutputException→NaN을 유발했다(modu E0
    final Job[62]). ragas_score가 llm_factory에 JUDGE_MAX_TOKENS를 넘기고,
    그 값이 기본 1024보다 큰지 검증 — 기본으로 되돌아가면 실패."""
    pd = pytest.importorskip("pandas")
    run_eval._install_vertexai_shim()
    ragas_mod = pytest.importorskip("ragas")
    import ragas.llms as ragas_llms
    import ragas.metrics as ragas_metrics
    import openai
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-dummy")
    captured = {}

    def _fake_factory(*a, **kw):
        captured.update(kw)
        return object()

    class _FakeResult:
        def to_pandas(self):
            return pd.DataFrame(
                {"llm_context_precision_with_reference": [1.0],
                 "context_recall": [1.0]})

    monkeypatch.setattr(openai, "AsyncOpenAI", lambda **kw: object())
    monkeypatch.setattr(ragas_llms, "llm_factory", _fake_factory)
    monkeypatch.setattr(ragas_metrics, "LLMContextPrecisionWithReference",
                        lambda **kw: object())
    monkeypatch.setattr(ragas_metrics, "LLMContextRecall", lambda **kw: object())
    monkeypatch.setattr(ragas_mod, "EvaluationDataset",
                        type("_ED", (), {"from_list": staticmethod(lambda x: x)}))
    monkeypatch.setattr(ragas_mod, "evaluate", lambda **kw: _FakeResult())
    rows = [{"tag": "decision", "question": "q1", "contexts": ["c"],
             "reference": "r"}]
    run_eval.ragas_score(rows, "gpt-4.1-mini", False, 1)

    assert captured.get("max_tokens") == run_eval.JUDGE_MAX_TOKENS
    assert run_eval.JUDGE_MAX_TOKENS > 1024   # ragas 기본으로 회귀 금지


def test_invalidate_measurement_removes_only_target(tmp_path, monkeypatch):
    """R6-001: 재측정 무효화가 대상 run/config의 게시물 3종(마커·상세 CSV·
    summary 행)만 제거하고 다른 측정은 건드리지 않는다."""
    import csv as csv_mod
    monkeypatch.setattr(run_eval, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(run_eval, "STATE_DIR", tmp_path / "state")
    # 대상: modu/E0/final, 무관: modu/E0/dev
    marker = run_eval.marker_path("RID", "modu", "E0", "final")
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("gpt-4.1-mini")
    other_marker = run_eval.marker_path("RID", "modu", "E0", "dev")
    other_marker.write_text("gpt-4.1-mini")
    detail = run_eval.detail_path_for("modu", "E0", "final", "RID")
    detail.write_text("qid\nB1\n")
    sw = run_eval.SummaryWriter(tmp_path / "summary.csv")
    sw.upsert({"run_id": "RID", "corpus": "modu", "config": "E0",
               "phase": "final", "judge": "gpt-4.1-mini", "context_precision": "0.3"})
    sw.upsert({"run_id": "RID", "corpus": "modu", "config": "E0",
               "phase": "dev", "judge": "gpt-4.1-mini", "context_precision": "0.9"})

    removed = run_eval.invalidate_measurement("RID", "modu", "E0", "final")

    assert not marker.exists() and not detail.exists()
    assert other_marker.exists()                       # 무관 측정 보존
    with open(tmp_path / "summary.csv", encoding="utf-8") as f:
        rows = list(csv_mod.DictReader(f))
    assert len(rows) == 1 and rows[0]["phase"] == "dev"  # final 행만 제거
    assert "summary.csv 행" in removed and marker.name in removed


def test_overwrite_invalidates_before_measurement_failure(tmp_path, monkeypatch):
    """R6-001: --overwrite 재측정이 측정 본문에서 실패해도, 무효화가 그 앞에서
    이미 실행돼 기존 게시물 3종이 '완료'로 남지 않는다(resume 오건너뜀 방지)."""
    import argparse
    monkeypatch.setattr(run_eval, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(run_eval, "STATE_DIR", tmp_path / "state")
    marker = run_eval.marker_path("RID", "modu", "E0", "final")
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("gpt-4.1-mini")
    detail = run_eval.detail_path_for("modu", "E0", "final", "RID")
    detail.write_text("qid\nB1\n")
    run_eval.SummaryWriter(tmp_path / "summary.csv").upsert(
        {"run_id": "RID", "corpus": "modu", "config": "E0", "phase": "final",
         "judge": "gpt-4.1-mini", "context_precision": "0.3"})
    # 무효화(본문 진입 전)는 통과하고, 그 직후 setup_env에서 측정 실패를 주입
    def _boom(*a, **k):
        raise RuntimeError("측정 실패 주입")
    monkeypatch.setattr(run_eval, "setup_env", _boom)
    ns = argparse.Namespace(corpus="modu", config="E0", phase="final",
                            runid="RID", judge="gpt-4.1-mini", resume=False,
                            overwrite=True, workers=3, no_langsmith=True)
    with pytest.raises(RuntimeError, match="측정 실패 주입"):
        run_eval.cmd_measure(ns)
    # 세 게시물 모두 제거된 상태 — resume이 '완료'로 오인하지 않는다
    assert not marker.exists()
    assert not detail.exists()
    assert not (tmp_path / "summary.csv").exists() or \
        run_eval.SummaryWriter(tmp_path / "summary.csv")._load() == []


def test_docs_and_methods_match_runtime_defaults():
    """R5-002/R5-003: as-run METHODS와 README가 실제 기본값(workers·judge)을
    기록한다 — CLI 기본값 변경 시 문서가 어긋나면 실패."""
    md = run_eval.render_methods("RID-DOC", "dev")
    assert f"workers 기본 {run_eval.WORKERS_DEFAULT}" in md
    readme = (_REPO / "backend" / "test" / "golden" / "README.md").read_text(
        encoding="utf-8")
    assert f"기본 {run_eval.WORKERS_DEFAULT}" in readme
    assert run_eval.PHASE_JUDGE["dev"] in readme
    assert run_eval.PHASE_JUDGE["final"] in readme
    assert "4o-mini" not in readme  # 교체 전 judge 표기 잔존 금지


# ── TASK-007: 출처 추적성(인용 근거성) 측정 ───────────────────────────────────

def test_citation_grounding_scores():
    """근거 있는 인용만 인정하고 유형 라벨·본문 언급·허위 출처는 0점."""
    cg = run_eval.citation_grounding
    labels = ["2026-03-02_회의.md", "설계.md"]
    assert cg("착수는 5월. (출처: 2026-03-02_회의.md)", labels) == 1.0
    # 본문에 파일명만 언급, 완전 마커 없음 → 0.0 (리뷰 R-006)
    assert cg("2026-03-02_회의.md 에 따르면 5월 착수", labels) == 0.0
    # 컨텍스트 유형 이름을 출처로 오용 → 0.0
    assert cg("결론. (출처: 구조화 기록)", labels) == 0.0
    # 검색 출처에 없는 허위 파일 인용 → 0.0
    assert cg("(출처: 없는파일.md)", labels) == 0.0
    # 인용 자체가 없음 → 0.0
    assert cg("그냥 답변", labels) == 0.0


def test_citation_grounding_delimiter_safe_filename():
    """파일명에 ')' 가 있어도 리터럴 매칭이라 근거로 인정(리뷰 R-003)."""
    labels = ["회의록) 최종.md"]
    assert run_eval.citation_grounding(
        "결론. (출처: 회의록) 최종.md)", labels) == 1.0


def test_citation_grounding_multi_source_marker():
    """한 마커에 콤마로 여러 출처를 묶어도 근거로 인정 — 스모크에서 확인된
    실제 표기 (출처: A, B). 모두 검색 출처면 1.0."""
    labels = ["2026-03-23_a.md", "2026-03-30_b.md"]
    assert run_eval.citation_grounding(
        "담당은 박현우. (출처: 2026-03-23_a.md, 2026-03-30_b.md)", labels) == 1.0
    # 묶인 출처 중 하나라도 검색 출처 밖이면 0.0
    assert run_eval.citation_grounding(
        "(출처: 2026-03-23_a.md, 없는.md)", labels) == 0.0


def test_citation_grounding_repo_label_with_paren_in_multi_source():
    """R3-P2: 라벨에 ')'가 든 저장소 출처(README.md (repo#7))가 다중 출처
    마커에 묶여도, 알려진 라벨 경계 파싱으로 정상 인정한다."""
    labels = ["README.md (repo#7)", "design.md"]
    assert run_eval.citation_grounding(
        "정비함. (출처: README.md (repo#7), design.md)", labels) == 1.0
    # 단일 저장소 라벨도 정상
    assert run_eval.citation_grounding(
        "(출처: README.md (repo#7))", labels) == 1.0
    # repo 라벨 + 허위가 섞이면 0.0
    assert run_eval.citation_grounding(
        "(출처: README.md (repo#7), 없는.md)", labels) == 0.0


def test_split_contexts_separates_sql_and_vector():
    """추적 스냅샷용: SQL 구조화 기록과 벡터 원문 청크를 출처 라벨·렌더링
    메타데이터와 함께 분리. 벡터는 text_full(전문)을 우선 사용한다."""
    debug = {
        "mysql_rows": [{"content": "결정1", "source_label": "a.md",
                        "category": "action", "owner": "김", "date": "2026-03-02",
                        "due_date": "2026-03-09", "completed": True}],
        "chroma_chunks": [{"text": "짧은", "text_full": "원문 전체 청크",
                           "source_label": "b.md", "date": "2026-03-02"}],
    }
    sql, vec = run_eval.split_contexts(debug)
    # SQL은 _row_line_body 렌더링에 쓰이는 메타(owner·date·due_date·완료)까지 보존(C5-003)
    assert sql == [{"content": "결정1", "source_label": "a.md", "category": "action",
                    "owner": "김", "date": "2026-03-02", "due_date": "2026-03-09",
                    "completed": True}]
    assert vec == [{"text": "원문 전체 청크", "source_label": "b.md",
                    "date": "2026-03-02"}]
    # 빈 debug → 빈 리스트
    assert run_eval.split_contexts({}) == ([], [])


def test_split_contexts_tolerates_r0_int_counts():
    """C5-001: R0 수집기는 mysql_rows/chroma_chunks에 정수 카운트를 넣는다.
    비리스트 값은 빈 리스트로 처리해 TypeError로 측정이 중단되지 않게 한다."""
    assert run_eval.split_contexts(
        {"mysql_rows": 5, "chroma_chunks": 3}) == ([], [])


def test_gen_context_falls_back_to_joined_contexts():
    """C5-002: 렌더링 컨텍스트가 없으면(R0) 수집 원문을 join해 폴백 — 빈
    컨텍스트로 생성·기권하지 않게 한다."""
    assert run_eval._gen_context({"rendered_context": "렌더링됨"},
                                 ["a", "b"]) == "렌더링됨"
    assert run_eval._gen_context({}, ["a", "b"]) == "a\nb"


def test_citation_grounding_grounded_plus_fabricated_is_zero():
    """근거 있는 인용에 허위 인용이 섞이면 0점 — 허위 출처 오통과 방지."""
    labels = ["a.md"]
    assert run_eval.citation_grounding(
        "(출처: a.md) 그리고 (출처: b.md)", labels) == 0.0


def test_build_context_configured_preserves_rendered_and_labels(monkeypatch):
    """[R-001] RAGAS용 원문 contexts는 유지하되, 생성·인용 측정용 렌더링
    컨텍스트(출처 마커 포함)와 검색 출처 라벨 집합을 debug로 노출한다."""
    from backend.retriever import qa_engine
    debug = {"mysql_rows": [{"content": "c1", "source_label": "a.md"}],
             "chroma_chunks": [{"text_full": "t1", "source_label": "b.md"}]}
    monkeypatch.setattr(
        qa_engine, "_build_context",
        lambda *a, **k: ("[구조화 기록]\nc1 (출처: a.md)", ["a.md"], debug))
    contexts, out = run_eval._build_context_configured(
        1, "q", history_mode=False)
    assert contexts == ["c1", "t1"]                 # RAGAS 입력은 원문 유지
    assert out["rendered_context"] == "[구조화 기록]\nc1 (출처: a.md)"
    assert out["source_labels"] == ["a.md", "b.md"]
