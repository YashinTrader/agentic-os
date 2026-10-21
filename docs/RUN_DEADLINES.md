# Agent run deadlines

Builders and Claude reviews share `orchestrator/run_deadlines.py` and the process
monitor. `agents/run_deadlines.yaml` configures startup and inactivity limits by
adapter. Defaults are 180 / 600 seconds for builders and 90 / 300 seconds for
reviews. The overall limit comes from the launch timeout (normally 1800 seconds).
An explicit review startup/inactivity argument overrides the adapter value.

Startup requires genuine activity: an accepted turn, model stream event, agent
message, tool execution, or a new/modified worktree file. Claude stream-json and
Codex JSONL are consumed incrementally; incomplete lines are retained. Grok JSON
uses the same structured activity detector. A session allocation, init event,
heartbeat, arbitrary stdout text, or live PID does not count.

Worktree scans compare nanosecond mtimes and sizes against a snapshot taken before
launch. They exclude symlinks, `.git`, runtime artifacts, dependencies, caches, and
the captured stdout/stderr files. Reviews use only structured stdout activity to
preserve their read-only contract. File-backed prompt stdin lets monitoring start
without waiting for the child to consume a pipe. Local builders continue to use
their filtered environment without inheriting host environment variables.

Before first activity, expiry yields `failed_launch`. After activity, a silent gap
yields `stalled`. Overall expiry yields `timed_out`, including when activity keeps
arriving. Normal activity refreshes only the inactivity clock. Polling defaults to
two seconds; detection follows that polling cadence. All durations use a monotonic
clock; durable evidence uses UTC timestamps.

Atomic run records retain `startup_activity_at`, `last_activity_at`,
`activity_events`, `deadline_fired`, and `deadline_fired_at`, together with normal
launch/completion metadata. The monitor writes deadline evidence before killing
the child. Builder failure routing emits one terminal poke and retains worktree
and logical work ownership. Startup deadlines do not trigger a second-adapter
fallback. Assigned Codex local builds route through the worker; unassigned direct
local builds emit their own failure poke. Reviewer deadline failures emit one
review failure poke and leave the assignment awaiting review. Existing deferral
and retry backoff still apply. Resume/release requires the existing work-lock
workflow; a deadline never grants permission to steal a lock.

Production local builders stream through the monitor. The explicit synchronous
`subprocess_runner` injection and skip-agent flags remain compatibility seams for
existing unit tests; they do not exercise live deadline detection. New deadline
tests use fake processes and injected clocks, including the production local
builder branch. Run the focused modules listed in the task handoff; do not launch
real agent CLIs to test timeout behavior.
