# Phase 3.6 Hardening Report

## MA1 — Command construction defect

**Fixed.** `append_codex_prompt()` appends the prompt after `-o` and output path. Regression tests in `tests/test_phase3_6_codex_command.py` fail under the prior `argv[-1] = prompt_arg` pattern.

## Activation boundary

- `codex-restricted.supports_execution: false` (registry + dedicated config)
- Only `local-python-exec-test` executable
- Manifest statuses capped at pre-active in Phase 3.6

## Canary boundary

- `run_codex_canary.py` always exits 3 at Phase 3.6 HEAD
- Twelve layered gates in `dispatch/codex_canary_gates.py`
- No Codex subprocess in tests (mocked)

## CLI discovery

- `inspect_codex_cli.py`: fixed argv only (`--version`, `--help`, `exec --help`)
- `shell=False`; no prompt execution
- Compatibility record at `runtime/registry/codex_cli_compatibility.json` (generated, not canonical config)

## Validator extensions

- `validate.py`: Phase 3.6 artifact and argv contract checks
- `validate_codex_activation.py`: outputs `READY_FOR_REVIEW` or blockers only

## Safety greps (verified at implementation)

| Check | Status |
|-------|--------|
| codex-restricted disabled | pass |
| no live Codex prompt subprocess | pass |
| no shell=True in Phase 3.6 modules | pass |
| no fabricated human approval | pass |
| no canary executed | pass |