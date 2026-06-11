# Phase 3.1 — Runtime Capture Contract

**Status:** Design only — Phase 3.2 implements writers  
**Related:** `ExecutionResultContract` in `dispatch/executor_contract.py`

## Run directory layout

```
runtime/dispatch/runs/<run_id>/
  execution_request.json   # ExecutionRequest snapshot at dispatch time
  command_preview.json     # Copy of or reference to preview artifact
  approval_record.json     # Present when approval required
  stdout.log               # Captured stdout (runtime only, gitignored)
  stderr.log               # Captured stderr
  result.json              # ExecutionResultContract
  handoff.md               # Required post-run handoff stub or path
  rollback.md              # Required when writes_files=true
```

All paths under `runtime/dispatch/**` are gitignored (Phase 3.0.1).

## `result.json` fields

| Field | Type | Notes |
|-------|------|-------|
| `run_id` | string | Matches request |
| `executed` | boolean | True only after Phase 3.2 runtime |
| `exit_code` | int \| null | Process exit code |
| `timed_out` | boolean | Timeout enforcement |
| `started_at` | ISO-8601 | UTC |
| `finished_at` | ISO-8601 | UTC |
| `duration_ms` | int | Wall clock |
| `stdout_path` | string | Relative to repo root |
| `stderr_path` | string | Relative to repo root |
| `files_changed` | string[] | From git diff or manifest |
| `blocked_reasons` | string[] | Empty on success |
| `error` | string \| null | Top-level error message |
| `handoff_path` | string | Must be non-empty on completed runs |

## Invariants

- Logs and results are **runtime-only** — never committed to git by automation.
- Dispatch must not mutate task `owner` or `status` fields.
- No auto-merge, push, or deploy artifacts in this directory.

## Phase 3.1 deliverable

`ExecutionResultContract` dataclass and JSON schema
(`schemas/dispatch_executor_contract.schema.json`) define the shape; no log capture
implementation in Phase 3.1.