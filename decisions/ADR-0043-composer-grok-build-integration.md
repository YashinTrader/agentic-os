# ADR-0043: Composer / Grok Build integration — design, preview, and assignment loop

- Status: accepted
- Date: 2026-07-01
- Updated: 2026-07-12 — builder display identity → Grok Build (Grok 4.5); Phase 3.8B activates file-based assignment loop
- Deciders: composer/grok (implementer), pending claude review
- Related: `dispatch/execution_route_policy.py`, `dispatch/local_builder_core.py`, `dispatch/assignment_channel.py`, `agents/composer_restricted_adapter.yaml`, `scripts/assignments.py`, `docs/GROK_BUILD_LOOP.md`

## Context

Phase 3.7C made `codex-restricted` dispatchable as an autonomous local builder with a dedicated execution route (`codex_local_builder`), standing policy, and read-only dashboard visibility. Claude (Development Director) must assign work to the Primary Builder/Integrator and ingest branches/handoffs without human message relay.

**Builder identity (2026-07-12):** The Primary Builder/Integrator role is now filled by **Grok Build (Grok 4.5)**. Stable adapter/agent ids remain `composer-restricted` / `composer` so existing references, routes, and handoff naming do not churn. Only `display_name` and notes were updated.

Composer/Grok runs inside Grok Build. There is no stable, documented headless Grok/Composer CLI equivalent to `codex exec -C {worktree} --json -o {out}` in this repository today.

## Decision

### 1. Invocation interface — file-based bridge (primary); CLI/API deferred

**What exists today (Composer 2.5 / Grok Build):**

| Option | Status | Notes |
|--------|--------|-------|
| (a) Headless CLI | **Not available** | No `composer exec` or `grok build --headless` contract checked into Agentic OS. `composer-cli-preview` in the registry is dry-run preview only. |
| (b) API | **Not wired** | No Grok/Composer execution API integrated; would require credentials and network (forbidden in this phase). |
| (c) File-based bridge | **Selected** | Claude writes assignment JSON to `runtime/dispatch/assignments/inbox/`; Composer runtime (human or future poller) reads inbox, builds in a worktree, writes result JSON to `runtime/dispatch/assignments/outbox/` and a v2 handoff. |

**Phase 3.8 delivered:** assignment schema scaffolding, validated reader/writer primitives, adapter registry entry (`composer-restricted`, preview-only), generalized local-builder route policy, and adapter-driven local-builder core. **No live invocation.**

**Phase 3.8B delivers (2026-07-12):** full bounded assignment contract, atomic claim lifecycle (`pending → claimed → building → awaiting_review → accepted|changes_requested|rejected`), CLI entrypoints (`scripts/assignments.py`), task-YAML status bridge, dashboard lifecycle view, operating doc `docs/GROK_BUILD_LOOP.md`, and an end-to-end local dogfood. **Still no automatic execution** — builder sessions pick up assignments manually via CLI.

**Full assignment contract fields:** `task_id`, `title`, `goal`, `base_branch`, `base_sha`, `new_branch`, `allowed_paths`, `forbidden_operations`, `acceptance_criteria`, `verification_commands`, `timeout`, `handoff_path`, `assigned_by`, `assigned_to`, `created_at`, `status` (plus stable metadata: `assignment_id`, `adapter_id`, `execution_route`, `task_path`).

**Live-activation follow-up must wire (Gabriel-gated):**

1. Enable `composer-restricted` in `config/execution-policy.yaml` (`enabled_adapters`) after Gabriel approves Grok credentials.
2. Implement a Grok inbox poller (or Grok Build hook) that claims assignments, calls `run_local_builder` via the adapter-driven core with a Composer/Grok command builder, and writes outbox results.
3. If a headless Grok/Composer CLI becomes available, extend `dispatch/composer_adapter.py` command builder mirroring `codex_adapter.py` and switch the poller from manual to subprocess invocation.
4. Add `secrets_required` enforcement only when `supports_execution: true` and real keys are approved.

### 2. Route policy and adapter-driven local builder generalization

- Add `ROUTE_COMPOSER_LOCAL_BUILDER = "composer_local_builder"` alongside `ROUTE_CODEX_LOCAL_BUILDER`.
- `local_worktree` adapters declare `required_execution_route` per agent; validation accepts any recognized local-builder route (not hardcoded to codex).
- Extract shared runner from `dispatch/codex_local_builder.py` into `dispatch/local_builder_core.py`. Command construction, environment augmentation, and executable resolution remain adapter-specific callables.
- `codex-restricted` behavior is unchanged: same route, gates, argv shape, and test fixtures. Codex remains the only execution-capable local-builder adapter until live activation.

### 3. Communication channel schema (Claude ↔ Composer)

**Inbox** (`runtime/dispatch/assignments/inbox/{assignment_id}.json`):

```yaml
schema_version: "1.0"
assignment_id: string          # uuid or build-{stamp}-{task}-{suffix}
task_id: string
adapter_id: composer-restricted
assigned_by: claude
assigned_to: composer
status: pending | claimed | cancelled
created_at: ISO-8601 UTC
updated_at: ISO-8601 UTC
execution_route: composer_local_builder
task_path: string            # repo-relative path to task YAML
base_sha: string | null
allowed_paths: [string]
instructions: string | null  # optional override; default from task
handoff_rel: string            # e.g. handoffs/T-FOO__composer__to__claude.md
```

**Outbox** (`runtime/dispatch/assignments/outbox/{assignment_id}.json`):

```yaml
schema_version: "1.0"
assignment_id: string
task_id: string
adapter_id: composer-restricted
run_id: string | null
status: completed | failed | blocked
finished_at: ISO-8601 UTC
handoff_path: string | null
branch_tip_sha: string | null
blocked_reasons: [string]
result_summary: string | null
```

**Claude review path:** Read outbox + handoff markdown + `runtime/dispatch/runs/{run_id}/result.json` when a run exists. Dashboard reuses `load_execution_runs` and enriches with assignment index (read-only). No write/execute controls on the dashboard.

Statuses follow existing run vocabulary where applicable (`completed_verified`, `blocked`, etc.) in run artifacts; assignment layer uses simpler `pending` / `claimed` / `completed` / `failed` / `cancelled`.

## Consequences

### 2026-07-15 amendment: local wake and orchestrator poke-back

Assignment creation may request an adapter-declared local wake. Only Claude may
request wakes. Composer uses an append-only wake queue plus a local watcher that
claims the assignment; it does not invoke Grok or change the automatic-execution
gate. Codex wake reuses the existing local-builder eligibility gate and worker
queue. Unknown or disabled mechanisms remain `pending_wake` rather than failing
assignment creation.

Builders and reviewer resolution write append-only notifications addressed only
to `runtime/dispatch/pokes/orchestrator/`. The CLI can list/drain this queue and
the dashboard may read it, but the dashboard gains no write control. Direct
agent-to-agent poke routing is not permitted.

### 2026-07-16 amendment: execution vs notification layers remain separate

The physical supervisor (execution) and orchestrator pokes (notification) are
independent layers and both remain active:

1. `--wake` notifies the supervisor queue (does not prove a process ran).
2. Supervisor launches the agent when capacity permits (PID/run record proves launch).
3. Completion writes outbox, sets `awaiting_review`, then emits an idempotent poke
   addressed only to `orchestrator`.
4. Claude drains pokes/outbox, reviews branch+handoff, and records
   `accept` / `request-changes` / `reject`.
5. `request-changes` re-enters via Claude-owned correction + `--wake`.
6. Agents never assign, wake, or poke other builders.
7. Duplicate completion pokes for the same undrained `(assignment_id, event)` are
   idempotent and must not spawn duplicate reviews/assignments.

Contract doc: `docs/AUTONOMOUS_LOOP_LAYERS.md`.

### 2026-07-15 amendment: physical agent launcher (Phase 3.9.1)

Gabriel authorized physical process launch. The supervisor
(`scripts/run_orchestrator.py` + `orchestrator/supervisor.py`) consumes wake
records, enforces concurrency=1, claims the assignment, and launches a real
Grok Build process:

```text
grok --cwd <worktree> --max-turns N --output-format json --single "<prompt>"
```

`running` requires a real PID. Stdout/stderr, heartbeats, and failure fingerprints
are persisted under `runtime/dispatch/runs/`. Completion routes to
`awaiting_review` and pokes only Claude. Codex remains a single-shot fallback
via the existing restricted command builder when Grok is blocked by quota/auth
or unavailable — no builder-to-builder reassignment loops. Unchanged external
failure fingerprints never relaunch.

- Positive: Composer is first-class in registry and route policy; Claude can assign via files today; codex path unchanged and regression-gated; physical launch is observable.
- Negative: Host still needs Grok CLI auth/quota; `run_tests.py` bootstrap remains a separate infrastructure issue.
- Neutral: Passive watcher remains available but is no longer the primary wake consumer for composer.

## Reviewer sign-off

- [x] composer (implementer)
- [ ] claude (reviewer)
