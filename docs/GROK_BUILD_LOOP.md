# Grok Build assignment loop (Claude ↔ Grok)

This document is the **operating contract** that replaces Gabriel-as-messenger.
It describes the file-based assignment bridge activated in Phase 3.8B.

**Builder identity:** Grok Build (Grok 4.5) — Primary Builder/Integrator.  
**Stable ids (do not rename):** adapter `composer-restricted`, agent `composer`.  
**Automatic execution:** **OFF**. `composer-restricted` is **not** in
`config/execution-policy.yaml` `enabled_adapters`. Pickup is manual CLI only.

See ADR-0043 and `docs/COMPOSER_LOCAL_BUILDER_PREVIEW.md`.

---

## Paths

| Surface | Path |
|---------|------|
| Inbox (Claude posts / Grok claims) | `runtime/dispatch/assignments/inbox/{assignment_id}.json` |
| Claims (atomic) | `runtime/dispatch/assignments/claims/{assignment_id}.json` |
| Outbox (Grok completes) | `runtime/dispatch/assignments/outbox/{assignment_id}.json` |
| Ingest index (Claude) | `runtime/dispatch/assignments/ingest/latest_ingest.json` |
| CLI | `python scripts/assignments.py …` |
| Handoffs | `handoffs/{task_id}__composer__to__claude.md` |
| Dashboard (read-only) | `python dashboard/app.py` → Execution Runs tab |

Runtime assignment files are gitignored under `runtime/dispatch/**` (except explicit
activation fixtures). Commit handoffs, docs, and `tests/fixtures/` evidence only.

---

## Lifecycle

```
pending → claimed → building → awaiting_review → accepted | changes_requested | rejected
                 ↘ cancelled
```

- **pending** — Claude posted; pickable once.
- **claimed** — atomic claim file created; task YAML → `in_progress`.
- **building** — optional mid-build marker.
- **awaiting_review** — outbox written; task YAML → `review`.
- Terminal states are never re-picked (worker-eligibility discipline).

---

## Claude: post an assignment

### From a task YAML (preferred)

```bash
cd C:/Users/gabot/agentic-os

# Ensure tasks/active/T-MY-TASK.yaml exists with status: ready
python scripts/assignments.py create --from-task tasks/active/T-MY-TASK.yaml \
  --base-branch main \
  --base-sha "$(git rev-parse HEAD)" \
  --new-branch agent/composer/T-MY-TASK \
  --assigned-by claude
```

### Explicit fields

```bash
python scripts/assignments.py create \
  --task-id T-MY-TASK \
  --title "Short title" \
  --goal "One-paragraph goal" \
  --base-branch main \
  --base-sha "$(git rev-parse HEAD)" \
  --new-branch agent/composer/T-MY-TASK \
  --allowed-path "docs/**" \
  --acceptance "Document exists" \
  --verify "python scripts/validate.py" \
  --handoff handoffs/T-MY-TASK__composer__to__claude.md \
  --assigned-by claude
```

Assignment files must include the full contract: `task_id`, `title`, `goal`,
`base_branch`, `base_sha`, `new_branch`, `allowed_paths`, `forbidden_operations`,
`acceptance_criteria`, `verification_commands`, `timeout`, `handoff_path`,
`assigned_by`, `assigned_to`, `created_at`, `status`. Schema is validated on write.

---

## Grok Build session: pick up and complete

Run **one** claim command at session start:

```bash
cd C:/Users/gabot/agentic-os

# List pickable work
python scripts/assignments.py list --pending

# Claim first pending (or pass assignment_id); prints full contract
python scripts/assignments.py claim
# or: python scripts/assignments.py claim assign-YYYYMMDDTHHMMSSZ-...

# Inspect again later
python scripts/assignments.py show <assignment_id>
```

Then build per contract:

1. Create isolated branch/worktree from `base_branch` @ `base_sha`.
2. Stay inside `allowed_paths`; honor `forbidden_operations`.
3. Run `verification_commands` and gates (`scripts/handoff_closeout_gate.py`).
4. Write v2 handoff to `handoff_path` with full 40-char SHAs.
5. Push branch (operator/network allowed for Grok session; policy forbids
   automatic adapter push — manual push is the builder's responsibility).
6. Complete:

```bash
python scripts/assignments.py complete <assignment_id> \
  --handoff handoffs/T-MY-TASK__composer__to__claude.md \
  --branch agent/composer/T-MY-TASK \
  --branch-tip-sha "$(git rev-parse HEAD)" \
  --summary "What shipped; gate exits" \
  --outbox-status awaiting_review
```

Optional mid-build mark:

```bash
python scripts/assignments.py complete <assignment_id> --building --handoff ... --branch ... --branch-tip-sha ...
```

(`--building` sets status then completes in one CLI call.)

---

## Claude: ingest results

```bash
cd C:/Users/gabot/agentic-os
python scripts/assignments.py ingest
python scripts/assignments.py outbox
```

Ingest is pure file I/O: links outbox → handoff path existence, branch name/tip,
and writes `runtime/dispatch/assignments/ingest/latest_ingest.json`.  
**Does not merge or push.**

Dashboard:

```bash
python dashboard/app.py
# or: python -m dashboard.app
# open http://localhost:8501/?tab=execution_runs
```

Read-only: no claim/approve/execute buttons.

---

## Branch naming and gates

| Rule | Value |
|------|--------|
| Branch | `agent/composer/{TASK_ID}` (or contract `new_branch`) |
| Base | contract `base_branch` @ `base_sha` |
| Handoff | v2; `scripts/handoff_verification_block.py`; full 40-char SHAs |
| Closeout | `python scripts/handoff_closeout_gate.py <handoff>` |
| Suite | single-threaded `python scripts/run_tests.py` once, exit 0 |
| Validate | `python scripts/validate.py` exit 0 |
| Verify | `python scripts/verify_repository_verification.py <handoff>` → `Status: verified` |

Forbidden (still): enabling `composer-restricted` in `enabled_adapters`, secrets in
repo, MCP side effects, merge to protected branches, dashboard write controls.

---

## Gabriel-gated blockers (not this loop)

- Adding `composer-restricted` to `enabled_adapters`
- Setting `supports_execution: true` / live Grok credentials
- Headless poller that claims and runs without a human Grok session

The loop above is sufficient for Claude to assign and review without Gabriel
relaying task text.
