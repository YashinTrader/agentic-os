# Claude Reviewer Adapter

Headless Claude Code adapter for Agentic OS autonomous review.

## Components

| Path | Role |
|------|------|
| `orchestrator/review_schema.py` | Strict verdict JSON schema + validation |
| `orchestrator/claude_reviewer_adapter.py` | CLI argv, launch, poll, collect, cancel |
| `orchestrator/review_dispatcher.py` | Review requests, leases, verdict application |
| `scripts/run_claude_reviewer.py` | One-shot reviewer |
| `scripts/run_orchestrator.py` | Unified builder + reviewer supervisor |

## Auth modes

- **`claude_code_local_auth` (default):** installed Claude Code CLI + existing local OAuth session. Tokens never serialized.
- **`anthropic_api`:** requires `ANTHROPIC_API_KEY` at process launch only; value never written to run artifacts.

## Command shape

```text
claude -p "<review prompt>"
  --output-format json
  --json-schema <REVIEW_JSON_SCHEMA>
  --permission-mode dontAsk
  --allowedTools Read,Glob,Grep,Bash(git status *),...
  --disallowedTools Edit,Write,...
```

Optional correction resume: `--resume <session_id>` (never `--continue`).

`shell=False`, captured stdout/stderr, bounded timeout.

## Interface

```python
adapter.launch_review(request)
adapter.poll_review(run_id)
adapter.collect_verdict(run_id)
adapter.cancel_review(run_id)
```

## Evidence

- Launch: PID + `runtime/dispatch/reviews/<run_id>/`
- Completion of review: schema-valid verdict JSON
- Assignment resolution: only via `dispatch.assignment_channel.resolve_assignment` after validation
