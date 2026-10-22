# Test bootstrap: Cognee blocker resolved

T-M1-22 (2026-10-22) moves `cognee==1.1.0` to optional
`requirements-memory.txt`. Default `python scripts/run_tests.py` installs core
`requirements.txt` without Cognee or its Rust/Cargo build chain.

Offline fallback with existing core dependencies:
`python scripts/run_tests.py --skip-install --skip-install-reason "Offline; dependencies installed"`.

Optional memory installation can still require Rust/Cargo; see
[the local profile](COGNEE_LOCAL_PROFILE.md). Profile checks do not import Cognee.
No network installation was attempted during the isolated T-M1-22 task.
