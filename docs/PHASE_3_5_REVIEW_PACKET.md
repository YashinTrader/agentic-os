# Phase 3.5 Review Packet

**Branch:** `agent/composer/T-PHASE3-5-CODEX-RESTRICTED-ADAPTER`  
**Base:** `f39188ab882af99920292adbed136effd1f10ffb`

## Deliverables

| Area | Paths |
|------|-------|
| Adapter | `agents/codex_restricted_adapter.yaml`, registry entry |
| Dispatch | `dispatch/codex_adapter.py`, `agent_environment.py`, `agent_context_bundle.py`, `agent_result_parser.py` |
| Scripts | `inspect_codex_cli.py`, `preview_codex_dispatch.py`, `run_codex_canary.py` |
| Schemas | `schemas/codex_restricted_adapter.schema.json`, `agent_execution_result.schema.json` |
| Tests | `tests/test_phase3_5_*.py` (7 modules) |
| ADRs | ADR-0029 – ADR-0033 |
| Docs | `docs/PHASE_3_5_*.md` |

## Claude review focus

1. Activation boundary (`supports_execution: false` throughout)
2. Command builder safety (argv-only, forbidden flags)
3. Environment secret boundary
4. Worktree gate integration
5. HMAC + anti-replay binding (no live Codex in tests)
6. Canary refusal until activation
7. Repository verification at final HEAD

## Clerical pre-test sign-offs

ADR-0025–0028 Claude reviewer checkboxes flipped per Phase 3.4.1 closeout approval.