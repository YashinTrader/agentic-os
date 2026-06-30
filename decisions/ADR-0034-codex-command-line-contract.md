# ADR-0034: Codex command-line contract

- Status: accepted
- Date: 2026-06-28
- Deciders: composer (implementer), pending claude review
- Related: `dispatch/codex_adapter.py`, `docs/PHASE_3_6_CODEX_COMMAND_CONTRACT.md`

## Context

Phase 3.5 introduced a Codex argv builder with MA1: prompt assignment overwrote the `-o` output path. Phase 3.6 must lock the contract before activation.

## Decision

1. **Argv shape** — `codex exec -C <wt> -s workspace-write --json -o <path> <prompt>` with prompt as trailing positional.
2. **MA1 fix** — `append_codex_prompt()`; never assign over flag values.
3. **Contract hash** — `compute_command_contract_hash()` binds activation manifests.
4. **Validation** — `validate_codex_argv_contract()` enforces `-o` value, prompt position, forbidden flags.
5. **No shell** — argv list only; subprocess invocation remains outside adapter module.

## Consequences

- Positive: Activation manifests detect command drift; regression tests catch MA1 recurrence.
- Negative: CLI upgrades require compatibility re-review.

## Reviewer sign-off

- [x] composer (implementer)
- [ ] claude (reviewer)