# Phase 3.6 Human Approval Checklist (Gabriel)

> This document is a **checklist only**. It is not an approval and contains no signature or HMAC key material.

## Adapter identity

- **Adapter ID:** `codex-restricted`
- **Reviewed commit SHA:** _(fill at activation time)_
- **Codex CLI version:** _(from `runtime/registry/codex_cli_compatibility.json`)_

## Scope of authorization (when signed in a future task)

Human approval authorizes **only**:

- One documentation-only canary run
- Maximum **1** run (`maximum_runs: 1`)
- Maximum **10–15 minute** timeout
- One new file: `docs/codex-canary-<run-id>.md`
- Worktree path: allocated under `runtime/worktrees/` (no main-repo writes)
- No merge, push, deploy, or production access
- No MCP invocation
- Expected network/API: Codex/OpenAI only via installed CLI

## Token and cost exposure

- `OPENAI_API_KEY` required in operator environment
- Single bounded canary prompt (documentation task)
- No autonomous scheduling or queue

## Pre-flight checks

- [ ] Claude Phase 3.6 review **APPROVE**
- [ ] `supports_execution` flipped to `true` in separate activation commit
- [ ] Activation manifest `human_approved` with matching hashes
- [ ] CLI compatibility record reviewed (`help_hash`, version)
- [ ] Worktree allocated and recorded
- [ ] Signed human approval record present and not consumed
- [ ] Emergency-disable file absent
- [ ] Rollback plan read (`docs/PHASE_3_6_CODEX_ROLLBACK.md`)

## Operator commands (future activation only)

```bash
python scripts/validate_codex_activation.py --json
python scripts/run_codex_canary.py --execute-canary --manifest <path> --allocation <path> --approval <path>
```

## Post-run manual inspection

- [ ] Exactly one `docs/codex-canary-*.md` added in worktree
- [ ] No other tracked changes
- [ ] Logs and handoff captured under `runtime/dispatch/runs/<run-id>/`
- [ ] Adapter returned to disabled or canary-only suspended state
- [ ] Approval marked consumed

## Rollback / disable

```bash
# Emergency disable — see docs/PHASE_3_6_CODEX_ROLLBACK.md
```

## Expiry

Activation manifest `activation_expires_at` must be honored. Expired manifests refuse execution.