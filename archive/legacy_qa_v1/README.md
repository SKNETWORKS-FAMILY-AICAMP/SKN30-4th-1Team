# Legacy Q&A v1 baseline

This directory preserves the router-branching Q&A baseline for comparison with
the Agentic-only runtime. It is not imported by the service, Docker image, or
wheel package.

The executable source is commit 2406f4f899fe1ac907cb5f8acb787ce7cd695be6.
The local convenience tag is legacy-qa-v1-baseline-20260729. The runner
materializes the commit directly in a detached temporary worktree, so a clone
can run the archive even before the tag is published. This keeps the router
baseline historical even when shared retrieval code changes later.

## Run

~~~bash
# Verify tag, lockfile, and tracked source blobs first.
python archive/legacy_qa_v1/scripts/verify_snapshot.py

# Run only the frozen router-branching suite in an isolated detached worktree.
python archive/legacy_qa_v1/scripts/run_suite.py legacy

# Run only the current Agentic-only suite.
python archive/legacy_qa_v1/scripts/run_suite.py current

# Run both independently.
python archive/legacy_qa_v1/scripts/run_suite.py both
~~~

The runner uses uv run with the locked dev dependency group when uv is
available. It refuses an uncommitted current worktree by default so a
comparison always names an exact candidate commit. For a local, non-release
check only, pass --allow-dirty.

## Run the Legacy baseline as an evaluation candidate

`run_comparison.py` materializes the frozen Legacy commit and an explicitly
named Agentic candidate in separate detached worktrees. It checks that both
refs contain the exact same corpus/question objects before either side starts,
runs the selected sides sequentially, and writes separate `legacy/` and
`candidate/` outputs plus SHA-pinned `comparison.json` metadata.

Planning is read-only with respect to Docker and OpenAI, so it is the expected
first step while no API key is available:

~~~bash
uv run python archive/legacy_qa_v1/scripts/run_comparison.py \
  plan both \
  --candidate-ref <PR18_INTEGRATION_COMMIT> \
  --output-dir /tmp/paim-eval-plan-modu \
  --corpus modu \
  --phase dev \
  --run-id pr18-modu-dev-01
~~~

Each side can also be prepared or executed independently by replacing `both`
with `legacy` or `current`. `--candidate-ref` is still required so every
metadata record always identifies both comparison endpoints.

A live run uses each ref's own
`backend/test/golden/run_eval.py` and forces official OpenAI,
`gpt-4.1-mini`, and no LangSmith tracing:

~~~bash
OPENAI_API_KEY=... uv run python archive/legacy_qa_v1/scripts/run_comparison.py \
  run both \
  --candidate-ref <PR18_INTEGRATION_COMMIT> \
  --output-dir /tmp/paim-eval-run-modu \
  --corpus modu \
  --phase dev \
  --run-id pr18-modu-dev-01 \
  --acknowledge-live-eval-state
~~~

The acknowledgement is deliberate. The historical evaluation CLI uses the
fixed Docker container `paim-eval-db` and loopback port `3316`, performs LLM
extraction and judging, and mutates MySQL/Chroma state. The wrapper refuses to
adopt or remove a container that existed before it started. It serializes its
own runs, executes Legacy and candidate one at a time, and removes only the
dedicated evaluation container created by the selected side. Do not run the
historical CLI separately against that container while this wrapper is active.

The wrapper copies files for the selected run id into side-specific result
directories and records hashes in `comparison.json`; it never records the API
key. Full live results still depend on external model behavior and independent
LLM-based ingestion, so preserve the metadata and inspect per-question outputs,
not only aggregate averages.

This is a same-dataset comparison, not a harness-identical benchmark. Each ref
executes its own `backend/test/golden/run_eval.py`: the Legacy ref contains the
router-specific E2 collector/audit, while PR #18 contains the Agentic retrieval
adapter and history audit. `comparison.json` therefore records both runner Git
object IDs and `same_harness`; for PR #18 this value is expected to be `false`.
Compare the common metric outputs, but review the raw per-question contexts,
answers, sources, tool/history debug, and each ref's METHODS file alongside the
aggregate summary before attributing a delta to the runtime architecture.

If the baseline object is absent in a shallow clone, planning stops with a
diagnostic instead of silently testing another ref. Fetch the missing history
or exact baseline commit from a trusted remote, then rerun the plan.

### Route interpretation

Do not compare `route` as a cross-version quality metric. The Legacy baseline
has a real router and may retain its historical routing audit. PR #18 instead
selects tools dynamically; its response value `route="semantic"` is a client
compatibility/display field, not evidence that the semantic path was selected.
The current evaluation records routing accuracy as `N/A` and audits Agentic
history/tool behavior separately. The comparison wrapper preserves both sides'
raw artifacts but does not turn `route` into a pass/fail verdict.

## Scope

- Legacy suite: pre-Agentic router, direct LangGraph Q&A flow, attachment
  boundary, history retrieval, citations, and supersede-context behavior.
- Current suite: Agentic tool-orchestrator contract, temporary attachment
  evidence, and this archive boundary.
- Live database/Chroma/LLM evaluation is never automatic. `run_comparison.py`
  exposes it only as an explicit, sequential, state-acknowledged operation;
  `plan` and the archive unit suites remain key-free.

The runtime must not import this directory. The old router is preserved only
by the fixed commit and this materialization recipe. All active Q&A
entrypoints — project query API, Streamlit Q&A, and the separate session-memory
API — use the Agentic path. The session-memory API was not part of the original
router-branching baseline, but its current runtime is Agentic as well.
