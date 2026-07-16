# Claude Autonomous Review Loop

```
builder completes
  → assignment → awaiting_review
  → review.requested (idempotent)
  → supervisor launches Claude Code headlessly
  → Claude returns structured verdict
  → supervisor validates + applies verdict
  → accepted | changes_requested (+ wake composer) | rejected
```

Interactive Claude chat is **not** required for routine reviews.

Layers:

1. **Execution** — `run_orchestrator.py` launches builder and Claude reviewer processes.
2. **Notification** — pokes remain Claude-facing audit events; they do not launch processes.

See also `docs/AUTONOMOUS_LOOP_LAYERS.md` and `docs/CLAUDE_REVIEWER_ADAPTER.md`.
