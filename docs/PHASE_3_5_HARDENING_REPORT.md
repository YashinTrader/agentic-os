# Phase 3.5 Hardening Report

## Invariants verified

- Only `local-python-exec-test` has `supports_execution: true`
- `codex-restricted` remains `supports_execution: false`
- `promotion_state: restricted_candidate` consistent with non-execution
- No `shell=True` in Phase 3.5 modules
- `dispatch/codex_adapter.py` contains no subprocess calls
- `inspect_codex_cli.py` uses fixed argv discovery only
- Canary script exit code 3 (refused) without activation flags

## Validator extensions

- `validate_phase35_adapter_boundaries` in `scripts/validate.py`
- Dedicated config file presence and id check

## Test modules

Seven `test_phase3_5_*.py` modules covering adapter, environment, context, result parser, executor integration, activation boundary, and safety boundaries.