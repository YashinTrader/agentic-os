# ADR-0043: Composer 2.5 (Grok Build) integration — design and preview scaffolding

- Status: accepted
- Date: 2026-07-01
- Deciders: composer (implementer), pending claude review
- Related: `dispatch/execution_route_policy.py`, `dispatch/local_builder_core.py`, `dispatch/assignment_channel.py`, `agents/composer_restricted_adapter.yaml`

## Context

Phase 3.7C made `codex-restricted` dispatchable as an autonomous local builder with a dedicated execution route (`codex_local_builder`), standing policy, and read-only dashboard visibility. Claude (Development Director) must assign work to Composer 2.5 (Grok Build) and ingest branches/handoffs without human message relay.

Composer runs inside Grok Build (Cursor-hosted). There is no stable, documented headless Grok/Composer CLI equivalent to `codex exec -C {worktree} --json -o {out}` in this repository today.

## Decision

### 1. Invocation interface — file-based bridge (primary); CLI/API deferred

**What exists today (Composer 2.5 / Grok Build):**

| Option | Status | Notes |
|--------|--------|-------|
| (a) Headless CLI | **Not available** | No `composer exec` or `grok build --headless` contract checked into Agentic OS. `composer-cli-preview` in the registry is dry-run preview only. |
| (b) API | **Not wired** | No Grok/Composer execution API integrated; would require credentials and network (forbidden in this phase). |
| (c) File-based bridge | **Selected** | Claude writes assignment JSON to `runtime/dispatch/assignments/inbox/`; Composer runtime (human or future poller) reads inbox, builds in a worktree, writes result JSON to `runtime/dispatch/assignments/outbox/` and a v2 handoff. |

**Phase 3.8 delivers:** assignment schema, validated reader/writer primitives, adapter registry entry (`composer-restricted`, preview-only), generalized local-builder route policy, and adapter-driven local-builder core. **No live invocation.**

**Live-activation follow-up must wire:**

1. Enable `composer-restricted` in `config/execution-policy.yaml` (`enabled_adapters`) after Gabriel approves Grok credentials.
2. Implement a Composer inbox poller (or Grok Build hook) that claims assignments, calls `run_local_builder` via the adapter-driven core with a Composer command builder, and writes outbox results.
3. If a headless Grok/Composer CLI becomes available, add `dispatch/composer_adapter.py` command builder mirroring `codex_adapter.py` and switch the poller from manual to subprocess invocation.
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

- Positive: Composer is first-class in registry and route policy; Claude can assign via files today; codex path unchanged and regression-gated.
- Negative: Live execution still requires human Grok session or a follow-up poller; file bridge adds eventual-consistency latency.
- Neutral: `enabled_adapters` stays codex-only until explicit activation task.

## Reviewer sign-off

- [x] composer (implementer)
- [ ] claude (reviewer)