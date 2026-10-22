# Grok streaming activity

The composer-restricted launcher uses `--output-format streaming-json` with
`--single`, `--cwd`, and `--max-turns`. Single-document JSON output buffers all
activity until exit and cannot support the startup and inactivity deadlines.
Codex and Claude reviewer launch formats are unchanged. Quota probes retain
their separate bounded single-document protocol.

For this adapter, every decoded NDJSON object with a string `type` counts as
progress, including `available_commands`, `thought`, `text`, tool updates,
`usage`, and `end`. Complete nonempty malformed lines count in `liveness_events`
only; they cannot satisfy startup or reset inactivity. Incomplete lines remain
buffered. Process liveness alone does not reset a deadline. Overall time remains
bounded regardless of progress.

Success requires exit code 0 and a top-level stdout `end` event, with no provider
failure. Missing terminal evidence or an unknown exit status fails without an
automatic retry. `sessionId`, `stopReason`, and input/output/total token counters
from the final `end` are persisted as `session_id`, `stop_reason`, and
`token_usage` in supervisor_run.json and result.json. Total tokens are preserved
from the provider; cache/reasoning accounting means input plus output need not
equal total.

The captured success fixture is real Grok streaming-json output from 2026-10-22.
Streaming error envelopes are **unverified**: top-level `type: error` with
`error`/`message`/`data` diagnostics and `type: end` with an error `stopReason` are
supported defensively, but neither has a captured real streaming error fixture.
Regression tests wrap the existing captured nested 402 diagnostic in these
synthetic shapes; they do not claim the shapes are provider observations.
Existing quota/auth matching and nonzero exit handling remain authoritative;
assistant text and tool errors are excluded from provider diagnostics.
