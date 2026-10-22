# Logical work ownership

All coordinated builder entry points share `dispatch/work_lock.py` and the
coordinator repository's `runtime/dispatch/locks/` directory. Task ids are hashed
for filenames; the original logical id is retained in each JSON record. Audit
records live in `locks/audit/`. A short OS file lock serializes create, heartbeat,
release, and supersede transactions across threads and processes; the durable
ownership record is created exclusively. Process death releases the transaction
mutex but never removes work ownership.

## Identity and assignment lifecycle

New assignments carry `logical_task_id`, defaulting to the task YAML `id`.
Set `logical_task_id` in YAML to group related work. YAML corrections/follow-ups
can use `parent_task_id`; ancestry is resolved across active/done/blocked tasks.
Missing parents and cycles fail closed. Assignment corrections use
`--parent-assignment-id` (also supported in task YAML). They inherit their
parent's logical id. An explicit `--logical-task-id` or YAML `logical_task_id`
is an intentional split. Do not infer independence from a suffix such as B or C.

```powershell
python scripts/assignments.py create --from-task tasks/active/T-FIX-B.yaml --parent-assignment-id assign-parent
```

Creation reserves ownership immediately. Claim adopts only that same assignment's
reservation; legacy inbox files acquire ownership when claimed. A distinct
assignment with the same logical id is blocked even if it targets another agent
or route. Reclaiming the same assignment does not authorize a second active run.

`accepted`, `rejected`, `cancelled`, and `superseded` release ownership and record
an audit event. `changes_requested`, build completion awaiting review, failure,
timeout, and orphan detection retain ownership. Failed work therefore cannot
silently become eligible for another builder after a launch lease is removed.
The assignment reassign operation explicitly supersedes the old lock, preserving
its logical identity and recording actor, reason, and prior holder. Configured
supervisor Codex fallbacks also explicitly supersede with an audit record, after
the primary exits (or before any process starts when its adapter is unavailable).

Supervisor pre-launch failures are an exception to failure retention. Before
acquiring a run's lock, the supervisor persists a run record. Validation,
allocation, task/adapter loading, and spawn failures record `failed_launch`
evidence and release only that attempt's lock, with an audit reason fenced by
assignment and run id. An unavailable adapter keeps its `blocked_no_adapter`
evidence and also releases its pre-launch lock. The same assignment can retry;
cleanup cannot release an explicitly superseded replacement holder. Once an
agent process starts, the existing failure/timeout retention rules apply.

Failed queued wakes retry at most three times, waiting 30 seconds after the
first failure and 60 seconds after the second. Retry metadata is persisted on
the signal. Exhausted signals move to `runtime/dispatch/wake_queue/dead_letter/`
with reason, attempts, and timestamps, and appear in supervisor status
`wake_alerts`. Each tick re-evaluates blocked builders before scanning eligible
wakes, skips failed/deferred heads, and starts at most one process. A missing
primary adapter can resolve to Codex before that start; a failure after a process
starts follows the condition retry schedule on later ticks.

## Enforcement

- Assignment `create` and `claim` call the shared lock module.
- `scripts/run_local_builder_worker.py:process_one` acquires before invoking the
  builder. It adopts a reservation only after claiming the matching assignment
  assigned to Codex; a correction's different task id cannot adopt its parent.
- `dispatch/local_builder_core.py:run_adapter_local_builder` independently enforces
  ownership before worktree allocation, covering direct local-builder calls.
- `orchestrator/supervisor.py:process_wake_signal` acquires before allocation or
  process launch, including its already-claimed assignment path. Existing launch
  leases continue to guard launch concurrency.
- `work_lock_enabled: true` in `config/execution-policy.yaml` is required before
  builder concurrency may exceed one. This is checked by policy validation,
  the worker, the shared local-builder core, and supervisor lease acquisition.
  Work ownership enforcement itself is always active, even at concurrency one.

Run ids are shared between worker claims, global locks, and builder results.
Long blocking builder calls refresh ownership every 30 seconds. Supervisor state
persistence refreshes ownership during monitoring and records the resulting
process state. Heartbeats do not imply progress or reviewer acceptance.

## Manual dispatch

The orchestrator MUST acquire before launching any out-of-channel work. Use the
same coordinator `--root` as the assignment channel and supervisor, including
when the implementation will run in a separate clone. A clone's independent
runtime directory is not a global coordinator. Do not start independent worker
or supervisor coordinators in each clone; dispatch from the canonical root and
point their build worktrees at the isolated checkout. Before enabling this on an
existing installation, register any already-active manual work with this CLI.

```powershell
python scripts/work_lock.py --root C:/Users/gabot/agentic-os acquire T-FIX --holder-agent codex --run-id manual-fix-1 --base-sha <sha> --branch agent/codex/T-FIX
python scripts/work_lock.py --root C:/Users/gabot/agentic-os status T-FIX
python scripts/work_lock.py --root C:/Users/gabot/agentic-os supersede T-FIX --actor claude --reason "Prior builder stopped; correction authorized" --holder-agent composer --assignment-id assign-replacement --base-sha <sha> --branch agent/composer/T-FIX
python scripts/work_lock.py --root C:/Users/gabot/agentic-os release T-FIX --actor claude --reason "Accepted"
```

All commands are local file operations. Manual agents can refresh their own run
with `dispatch.work_lock.heartbeat(root, logical_id, run_id=...)` during execution.
Inspect/stop the prior process before transferring ownership: supersede changes
coordination state and does not kill an independently launched process.

## Staleness and recovery

`status` returns `stale: true` and `lock_status: stale` after 900 seconds without
a heartbeat. This is a derived observation, never a lease expiry. Acquisition
cannot steal an old lock. Only an explicit release or supersede can clear or
transfer ownership; both require an actor and reason and preserve the full prior
record. Invalid/corrupt records fail closed.

Startup recovery also checks locks against run records and known process
identities (including assignment leases). A holder without a run record and
without a known live process is marked stale with `stale_reason: ghost_holder`
and surfaced in supervisor status `work_lock_alerts`. Recovery never releases
or steals that holder; an operator must explicitly release or supersede it.

Assignment readers expose the live `work_lock_status` record. The assignment
CLI includes it in JSON. Within the existing dashboard contract, the assignment
index's visible `errors` field carries `work_lock_status: stale` with holder and
route. This keeps the change inside dispatch rather than modifying dashboard UI.
Manual holders without an inbox assignment remain visible through CLI status.

## Focused verification

```powershell
python -m unittest -v tests.test_work_lock tests.test_assignment_channel tests.test_phase3_7c_local_builder tests.test_physical_agent_launcher tests.test_phase3_8b_assignment_loop tests.test_agent_wake_poke
python scripts/validate.py
```

Tests use local temporary repositories and mocked agent processes; they do not
launch an agent CLI or contact a network service.

## Coverage limits (verified by orchestrator review, 2026-10-21)

The lock is enforced **only** on these paths:

- the assignment channel (`scripts/assignments.py` create and claim)
- the local-builder worker and `run_adapter_local_builder`
- supervisor launches
- `scripts/work_lock.py`, the sanctioned wrapper for manual dispatch

It is **not** enforced on these:

- Running `codex exec`, `grok`, `claude`, or `git` directly from a terminal.
- Any process that never calls `dispatch/work_lock.py`.

No wrapper or operating-system boundary stops either of these. Manual dispatches must go through `scripts/work_lock.py acquire` first.

Two behaviours were verified independently of the unit tests:

- **Cross-process race:** 12 processes acquired at the same moment, in 5 trials. Each trial had exactly one winner, and the losers got `WorkLockError`.
- **Crash retention:** a holder was killed with `os._exit(137)`. Its lock was kept and the error named it. `supersede` then transferred the lock and wrote an audit record that includes the prior holder.
