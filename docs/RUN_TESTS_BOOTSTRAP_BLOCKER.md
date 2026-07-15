# run_tests.py Bootstrap Blocker (Cognee / Rust / Cargo)

**Date:** 2026-07-15  
**Status:** Known infrastructure blocker — separate from Phase 3.9 feature work  
**Candidate follow-up task:** `T-INFRA-RUN-TESTS-BOOTSTRAP-REPAIR` (not yet filed)

## Summary

`python scripts/run_tests.py` fails **before unittest discovery**. The wrapper always runs `pip install -r requirements.txt` first; that install fails while preparing metadata for a Rust-backed dependency pulled by `cognee==1.1.0`. No tests are collected or executed when this happens.

## Exact failure locus

| Item | Value |
|------|--------|
| Wrapper | `scripts/run_tests.py` |
| Failure step | Lines 83–95: `subprocess.run([sys.executable, "-m", "pip", "install", "-r", requirements.txt, "-q"])` |
| Requirements file | `requirements.txt` |
| Blocking pin | `cognee==1.1.0` (also lists `PyYAML`, `langgraph>=0.2.0`) |
| Failure class | `metadata-generation-failed` / `Preparing metadata (pyproject.toml) did not run successfully` |
| Exit code | `1` (written to `runtime/unittest_last_run.txt` before any suite run) |

## Failure chain

1. `run_tests.py` prints `run_tests: repo=... commit=...`.
2. Because `requirements.txt` exists, it invokes `python -m pip install -r requirements.txt -q`.
3. Pip reaches a package build that needs a Rust toolchain (via **puccinialin** temporary rustup under `%LOCALAPPDATA%\puccinialin\...`).
4. The build reports Cargo is missing from PATH even after puccinialin downloads/updates a toolchain:

   ```
   Checking if cargo is installed
   cargo 1.97.0 (c980f4866 2026-06-30)

   Cargo, the Rust package manager, is not installed or is not on PATH.
   This package requires Rust and Cargo to compile extensions.
   ```

5. Pip aborts with `error: metadata-generation-failed`.
6. `run_tests.py` returns the pip exit code and **never** reaches the `unittest discover` invocation (lines 97–113).

## Environment notes (observed 2026-07-15)

- `where cargo` / `where rustc` on the worker PATH: **absent** (system Cargo not on PATH).
- Puccinialin cache at `C:\Users\gabot\AppData\Local\puccinialin\puccinialin\Cache` **exists** and installs/updates `stable-x86_64-pc-windows-msvc`, but the package metadata step still fails with “Cargo … not on PATH”.
- Python used by the wrapper may be Hermes venv (`...\hermes-agent\venv\Scripts\python.exe`) or another interpreter; both fail at the same bootstrap step.
- Repository Python unit tests do **not** require a successful Cognee install for the Agentic OS assignment/dispatch/dashboard suite.

## Why plain unittest discovery remains valid

`run_tests.py` only adds dependency bootstrap. Its suite command is exactly:

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

Running that command **without** the pip bootstrap:

- discovers and executes the repository Python tests;
- does not need Cognee, Rust, or Cargo for the Phase 3.x channel tests;
- is the evidence path approved for closeout when the wrapper is blocked.

Record the plain-discovery result (test count, failures, errors, elapsed time, exit code) as suite evidence. Do **not** claim `scripts/run_tests.py` passed.

## Proposed infrastructure repair task

Separate from feature closeout. Suggested acceptance criteria:

1. Install a durable Rust/Cargo toolchain on the agent host **or** make puccinialin’s Cargo visible on PATH for pip builds.
2. Optionally split `requirements.txt` into runtime vs optional Cognee extras so default `run_tests.py` does not force native builds.
3. `python scripts/run_tests.py` reaches unittest discovery and exit 0 on a clean agent machine.
4. Keep plain `unittest discover` as a bootstrap-free fallback documented in `docs/GROK_BUILD_LOOP.md`.

## Non-goals for Phase 3.9 closeout

- Do not mix Cognee/Cargo install repair into the wake/poke feature branch as a required fix.
- Do not weaken the handoff protocol to accept a failed bootstrap as a green suite.
