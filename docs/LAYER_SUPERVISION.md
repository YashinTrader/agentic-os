# Persistent layer supervision

`scripts/run_supervisor_layers.py` independently supervises the builder and Claude
consumer. It writes `runtime/dispatch/layer_supervisor/status.json` atomically.
Each child receives its own heartbeat path and a unique launch token. The token
also works when a Windows executable wrapper has a different PID from Python.

A child exit (including code zero), launch failure, or stale heartbeat restarts
only that child. Delays are 2, 4, 8, ... seconds, capped at 300 seconds. A healthy
600-second run resets the consecutive-failure backoff. More than five exits in a
rolling 600-second window opens that child's circuit; its sibling continues.
The open circuit and bounded exit history survive parent restarts. To recover an
open circuit, stop the parent, retain a copy of its status for audit, correct the
underlying problem, then remove the status file before starting the parent again.

Heartbeats come from the actual idle and work-monitoring loops. They contain
`last_tick_at`, `ticks`, and `last_progress_at`. Progress marks claims, launches,
and persisted work transitions; merely waiting for an agent or polling an idle
queue ticks without advancing progress. The parent reports `alive`, `ticking`,
and `progressing` independently. The heartbeat timeout is three times the child
poll interval, with a 60-second minimum (60 seconds for the default five-second
poll). A starting child gets the same grace period. Progress is recent when a new
progress marker was observed within that timeout; lack of work never triggers a
restart while ticks continue.

The last 20 exits per child retain exit codes, timestamps, reasons, and at most
8192 characters of stderr. Pipe draining retains at most 8192 bytes in memory.
Recovery is measured from the detected exit to the first heartbeat of its
replacement, including backoff; `restart_count` counts replacement launches and
`last_restart_at` records their wall-clock time. A process launch alone does not
establish recovery.

SIGINT, SIGTERM, and Windows CTRL_BREAK request parent shutdown. Each live child
gets SIGTERM on POSIX or CTRL_BREAK in its Windows process group, followed by up
to ten seconds to exit and a kill fallback. Work monitors unwind and stop their
active agent process. Parent status records `stopped` and `stopped_exit_code`,
without adding a crash event for the requested shutdown. Uncatchable OS force
termination or power loss cannot execute cleanup; the last atomic snapshot and
exit history remain the available evidence. No scheduler configuration is changed.

Focused checks (mocked agent CLIs; only a tiny Python dummy runs as a real child):

```powershell
python -m unittest -v tests.test_layer_supervisor tests.test_claude_event_consumer tests.test_physical_agent_launcher tests.test_claude_reviewer_adapter tests.test_phase3_3_review_fixes.HandoffVerificationProtocolTests
python scripts/validate.py
```
