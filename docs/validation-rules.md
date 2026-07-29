# Backend Validation Rules

Validation is acceptance-oriented, not an additional open-ended code review.

Required checks:

1. Every mandatory acceptance criterion has evidence.
2. Configured backend format, lint, type, test, and build checks pass or have an approved exception.
3. Every accepted Critical, High, and Medium review finding is resolved or explicitly blocked.
4. No finding triaged as `NEEDS_HUMAN` at Critical or High severity remains
   without a recorded human decision in `review-triage.md`.
5. Regression tests exercise the corrected behavior.
6. The diff does not include forbidden frontend paths. Verify with a read-only
   scope check that inspects **both the baseline diff and untracked files**.
   Do not rely on `git diff` alone: a newly created frontend file is invisible
   to it.

   > The scope tool (`scripts/check-scope.sh`) is an **externally supplied
   > personal workflow asset** and is not tracked in this repository. If it is
   > not provided, rule 21 applies and validation is `BLOCKED`.
7. The verification run was not `INCONCLUSIVE`. If every check was skipped
   because no commands are configured, nothing was verified.
8. The final implementation remains within the approved plan or documents an approved deviation.
9. Remaining risks are listed clearly in Korean.

Return `BLOCKED` rather than guessing when validation depends on unavailable credentials, services, datasets, requirements, or runtime environments.

Return `BLOCKED`, never `PASS`, when an unresolved `NEEDS_HUMAN` finding of
Critical or High severity exists. Severity is judged from the review, not from
whether the implementer chose to act on it.

## Docker-dependent gates

The MySQL integration gate (`tests/integration/mysql/run.sh`) requires the Docker
socket. **Withholding Docker access from the validator session is a deliberate
security decision** — socket access is equivalent to host root and would nullify
the read-only property that is the session's only safety guarantee.

**The absence of the Docker socket is therefore not, by itself, a reason to
return `BLOCKED`.** This exception applies to the Docker socket only. It does not
extend to other missing credentials, services, datasets, or runtime environments.

This gate may be judged from a log the user produced. That log is
**non-independent execution evidence**, and it is a valid basis for judgment only
when **all** of the following hold.

1. The full command shows a **direct invocation of the tracked runner**
   `tests/integration/mysql/run.sh` — not a personal wrapper.
2. Start and end times in **UTC**, the **final exit code**, and how stdout and
   stderr were captured.
3. All eight stages are present, in order:
   `preflight → pytest(local) → compose up/wait → migration 1 → migration 2 →
   port resolve → pytest(mysql) → cleanup`.
   **`END rc=0` appears only after `cleanup`.**
4. An identifier binding the log to the state under validation — the
   **state fingerprint** defined below.
5. A manifest of execution inputs: the runner, `compose.yml`,
   `backend/db/migrate_v9.sql`, `backend/db/schema.sql`,
   `tests/integration/mysql/schema_v8.sql`, `uv.lock`, `pyproject.toml`, the
   **MySQL image digest** (`mysql:8.0` is a moving tag), and the Python, uv,
   Docker Engine, and Docker Compose versions.
6. The exact expected skip manifest below, and the actual `-vv -rs` skip details
   from the delegated run. Both node IDs and reasons must be visible.
7. The state the validator recomputes **matches** the state recorded in the log.

**If any of these is missing, return `BLOCKED`.**

A log that is truncated, or whose recorded state does not match, cannot yield
`PASS`. Distinguish the two outcomes:

- **`FAIL`** — the state matches but a test or the cleanup contract failed.
- **`BLOCKED`** — the log is missing, truncated, the run was interrupted, or the
  state cannot be bound.

Skips are **not** prohibited as a class. The pre-migration baseline completed
with local rc `0` (`935 passed, 2 skipped`) and MySQL rc `0` (`48 passed`). Its
exact expected skip manifest is:

| node ID | reason |
|---|---|
| `tests/test_golden_harness.py::test_ragas_score_aborts_before_publish_on_nan` | `could not import 'ragas': No module named 'ragas'` |
| `tests/test_golden_harness.py::test_ragas_score_raises_judge_max_tokens` | `could not import 'ragas': No module named 'ragas'` |

When the complete log is bound to the matching state, any missing, additional,
or reason-changed skip is **`FAIL`**. If the log is truncated or lacks `-vv -rs`
detail so that the node IDs or reasons cannot be compared, the evidence is
**`BLOCKED`**. Only unexpected non-execution of a required stage is
disqualifying as stage omission; the two skips above are expected test results.

Cross-check against artifacts from the same code state — `run.sh --check`, the
harness contract tests, and stages that run without Docker. **The scope check is
not a cross-check for this gate**: it says nothing about MySQL results.

All other gates — scope, smoke, and static checks — are still re-run directly.

### State fingerprint

The fingerprint must be reproducible byte-for-byte by anyone holding the same
tree. The tracked, read-only reference implementation is
`tests/state_fingerprint.py`; its output is authoritative if this prose is ever
read differently. For example, when the delegated log is written inside the
repository:

```bash
LC_ALL=C python3 tests/state_fingerprint.py \
  --repo . \
  --exclude-path .agent-workflow/tasks/TASK-ID/logs/delegated-run.log
```

Repeat `--exclude-path` once for every path created by the run and record those
exact arguments in the log. The command prints one lowercase SHA-256 digest and
a display newline; that display newline is not part of the fingerprint stream.

Run everything under `LC_ALL=C` so sorting and case folding do not vary by
locale. Emit one record per item. Each record is length-prefixed so that
newlines, spaces, and other unusual bytes in a path cannot forge a boundary:

```
<kind> LF <byte-length of path> LF <path bytes> LF <byte-length of payload> LF <payload bytes> LF
```

`<kind>` is one of `head`, `diff`, `file`, or `link`.

| kind | path | payload |
|---|---|---|
| `head` | empty | `git rev-parse --verify HEAD` stdout with exactly its one command-terminating LF removed |
| `diff` | empty | raw stdout bytes of the reference implementation's `git diff --binary ... HEAD --`, including a final LF when Git emits one; this covers staged **and** unstaged changes |
| `file` | repo-relative raw path | `<mode> SP <sha256 of contents>` for each untracked regular file. `<mode>` is exactly four ASCII octal digits from `format(stat.S_IMODE(st_mode), "04o")`, for example `0644`, `0755`, or `4755` |
| `link` | repo-relative raw path | raw bytes returned by `readlink`, with no LF added — the link target, **not** the contents of what it points to |

Payloads never inherit a text command's terminator implicitly. In particular,
the `head` payload has no final LF, a `diff` payload retains every stdout byte,
and a `link` payload has no added LF. The record framing always adds its own
final LF. Therefore a diff that ends in LF is followed by a second LF belonging
to the frame; both bytes are hashed.

Enumerate untracked entries with:

```bash
git ls-files -z --others --exclude-standard
```

Apply exclusions to the NUL-delimited raw paths **after enumeration and before
`lstat`, hashing, or record construction**. Each `--exclude-path` is one
normalized repo-relative path matched by exact raw-byte equality: it is not a
glob or directory prefix, and absolute paths plus `.`/`..` components are
rejected. To exclude multiple files, list every file separately. Ignored files
are already absent because enumeration uses `--exclude-standard`.

Sort the remaining `file` and `link` records by their raw path bytes (the same
ordering as `LC_ALL=C sort -z`), then concatenate `head`, `diff`, and the sorted
records in that order and take the SHA-256 of the whole stream. Unsupported
untracked object types are an error rather than silently omitted. That digest is
the fingerprint.

**Exclude the log file itself and anything else written by the run.** Name the
excluded paths explicitly in the log; a fingerprint that covers its own output
can never be recomputed. Store logs outside the repository when possible.

`tests/test_harness_contract.py` fixes a golden vector containing staged and
unstaged diffs, space and LF bytes in file names, two untracked modes, a
symlink, and an excluded log. It requires the reference implementation and a
separate serializer to produce the same fixed digest.

**Residual risk, accepted.** A hand-edited log that merely looks complete cannot
be excluded by these rules. Without an externally protected signing key, having
the runner sign its own output would not close this either. Recomputing the state
fingerprint narrows the gap but does not eliminate it; this is an inherent limit
of non-independent evidence.
