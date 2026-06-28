# Phase 3.6 Codex Activation Readiness

## Purpose

Prepare a complete activation and canary package for `codex-restricted` while keeping `supports_execution: false` until a separate human-approved activation task.

## Package components

| Artifact | Role |
|----------|------|
| `dispatch/codex_adapter.py` | MA1-fixed argv builder + contract validation |
| `dispatch/codex_activation.py` | Activation manifest builder/validator |
| `dispatch/codex_canary_contract.py` | Documentation-only canary contract |
| `dispatch/codex_cli_compatibility.py` | Pure CLI compatibility evaluator |
| `dispatch/codex_canary_gates.py` | Layered canary refusal gates |
| `schemas/codex_activation_manifest.schema.json` | Manifest schema |
| `schemas/codex_canary_record.schema.json` | Canary record schema |
| `scripts/validate_codex_activation.py` | Readiness validator (`READY_FOR_REVIEW`) |
| `scripts/prepare_codex_canary.py` | Package preparation (no execution) |
| `scripts/run_codex_canary.py` | Refuses until post-activation |
| `scripts/inspect_codex_cli.py` | Read-only CLI discovery |

## Activation manifest status (this milestone)

Manifests may be at most:

- `draft`
- `reviewer_approved`
- `awaiting_human_approval`

Statuses `human_approved`, `activation_ready`, `active_canary_only`, and `active` are **not** set in Phase 3.6.

## Readiness command

```bash
python scripts/validate_codex_activation.py --json
```

Expected: `READY_FOR_REVIEW` (not `ACTIVE` or `EXECUTABLE`).

## Absolute boundary

`codex-restricted.supports_execution` remains **false**. Only `local-python-exec-test` may execute.