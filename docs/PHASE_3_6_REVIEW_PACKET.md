# Phase 3.6 Review Packet

## Milestone

Phase 3.6 — Codex Activation Readiness + Canary Package

## Base

- Branch: `agent/composer/T-PHASE3-5-CODEX-RESTRICTED-ADAPTER`
- SHA: `2af82a9e7e812e05059b69653583d1c78dfa43b1`
- Claude 3.5 verdict: APPROVE (restricted candidate)

## Deliverables

1. MA1 argv fix + contract hash
2. CLI compatibility evaluator + inspect script
3. Activation manifest schema/validator
4. Documentation-only canary contract
5. Layered canary refusal gates
6. Human approval checklist (no signature)
7. Rollback and emergency-disable docs
8. ADR-0034 through ADR-0037
9. ADR-0029–0033 Claude reviewer sign-offs (clerical)
10. Phase 3.6 test modules (+387 baseline)

## Verification

```bash
cd C:/Users/gabot/agentic-os
python scripts/run_tests.py
python scripts/validate.py
python scripts/validate_codex_activation.py
python scripts/verify_repository_verification.py --handoff handoffs/T-PHASE3-6-CODEX-ACTIVATION-READINESS__composer__to__claude.md
```

## Activation status

**Not activated.** Canary **not run.**

## Recommended Claude focus

- MA1 regression tests vs real CLI help
- Manifest hash binding on config drift
- Canary gate ordering and refusal before subprocess
- Post-test allowlist exactness