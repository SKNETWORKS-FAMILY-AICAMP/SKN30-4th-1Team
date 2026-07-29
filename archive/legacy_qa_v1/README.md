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

## Scope

- Legacy suite: pre-Agentic router, direct LangGraph Q&A flow, attachment
  boundary, history retrieval, citations, and supersede-context behavior.
- Current suite: Agentic tool-orchestrator contract, temporary attachment
  evidence, and this archive boundary.
- Live database/Chroma/LLM evaluation is intentionally not run here. Those
  inputs are mutable and must be isolated in a later opt-in E2E evaluation.

The runtime must not import this directory. The old router is preserved only
by the fixed commit and this materialization recipe. All active Q&A
entrypoints — project query API, Streamlit Q&A, and the separate session-memory
API — use the Agentic path. The session-memory API was not part of the original
router-branching baseline, but its current runtime is Agentic as well.
