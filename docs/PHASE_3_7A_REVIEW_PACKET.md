# Phase 3.7A Review Packet

## Milestone

Phase 3.7A — Codex Canary Activation Candidate

## Base

- Branch: `agent/composer/T-PHASE3-6-CODEX-ACTIVATION-READINESS`
- SHA: `d9f203c39c3a85613ef4c7f76e110e3f4734d9c1`

## Key artifacts

| Artifact | Purpose |
|----------|---------|
| `dispatch/codex_activation_gate.py` | Fifteen gates + Phase 3.7B |
| `dispatch/codex_activation.py` | Manifest v2, human request |
| `scripts/run_codex_canary.py` | Refusal runner |
| `scripts/disable_codex_canary.py` | Emergency disable |
| `scripts/prepare_codex_canary.py` | Package preparation |
| `scripts/validate_codex_activation.py` | READY_FOR_CLAUDE_REVIEW |
| `tests/test_phase3_7a_*` | Safety and gate tests |
| ADR-0038–0041 | New decisions |

## Verification commands

```bash
cd C:/Users/gabot/agentic-os
python scripts/run_tests.py
python scripts/validate.py
python scripts/validate_codex_activation.py
python scripts/run_codex_canary.py --json
```

## Safety assertions

- No Codex subprocess in runner or gate modules
- No human approval signature in repo
- No `phase3_7b_authorization.json`
- Autonomy Level 1

## Verdict requested

Claude final review before human approval and Phase 3.7B.