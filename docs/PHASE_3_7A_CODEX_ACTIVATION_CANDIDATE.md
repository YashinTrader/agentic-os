# Phase 3.7A Codex Activation Candidate

## Summary

Phase 3.7A prepares the Codex restricted adapter as an **activation candidate** with `supports_execution: true` and `execution_scope: canary_only`. Every gate through `evaluate_activation_gates()` remains unsatisfied for live execution during this milestone.

## Candidate configuration

| Field | Value |
|-------|-------|
| adapter_id | codex-restricted |
| promotion_state | activation_candidate |
| supports_execution | true |
| execution_scope | canary_only |
| maximum_runs | 1 |
| approval_level | human |
| live_run_authorized | false |
| phase3_7b_authorization_required | true |

## Activation bundle

Generated under `runtime/dispatch/codex_activation/<activation_id>/`:

- `activation_manifest.json` — status `awaiting_claude_review` or `awaiting_human_approval`
- `human_approval_request.json` — status `awaiting_human_decision`
- `preflight.json` — preflight complete, no live run
- `canary_preview.json` — expected canary markdown path

## Gate stack (stops before step 16)

1. supports_execution  
2. promotion_state canary-compatible  
3. manifest status live-approved  
4. manifest reviewed commit  
5. CLI help hash  
6. canary contract hash  
7. command contract hash  
8. human-signed approval  
9. anti-replay  
10. CLI compatibility  
11. worktree allocation  
12. operator `--execute-canary`  
13. emergency disable  
14. maximum runs  
15. Claude + human references  
16. **Phase 3.7B authorization** (absent in 3.7A)

## Next milestone

Claude final review of Phase 3.7A, then human approval, then Phase 3.7B authorization before first live canary.