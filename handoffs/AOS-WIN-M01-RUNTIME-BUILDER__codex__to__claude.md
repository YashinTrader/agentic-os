# AOS-WIN-M01 runtime builder and installable ZIP prototype

Owner: Codex. Review target: Claude. Source checkout HEAD: b4aee5f5bbe6200be4d44caf8f933f537eeb4e8d (agent/codex/win-m01-runtime).
Changes remain uncommitted, as instructed. No downloads, dependency installs, pushes, API calls, credential changes, or protected adapter changes were performed.

## Delivered

- packaging/windows/build_runtime.py: offline metadata closure, target markers, RECORD verification, copied PSF interpreter and signed venv launcher, PE signature inventory, deterministic manifest, smoke imports, build-info, and verify diff.
- packaging/windows/build_package.py: verified runtime plus git archive of the recorded commit, launcher/installer/uninstaller templates, every payload hash, runtime manifest hash and PE inventory, deterministic ZIP and SHA256SUMS.
- AgenticOS.cmd, Launch-AgenticOS.ps1, Package-Common.ps1, Install-AgenticOS.ps1, Uninstall-AgenticOS.ps1: separate immutable-file app versions and mutable state/projects, integrity checks before activation, runtime rebinding, N-1 retention, verified rollback, opt-in logon task, persisted crash guard, identity-fenced stop/uninstall, state/projects preservation.
- tests/test_build_runtime.py and tests/test_build_package.py; packaging/windows/README.md usage/trust/limitations.
- scripts/repository_verification.py includes this exact handoff in POST_TEST_ALLOWLIST_EXACT.

## Execution constraints and deviations

The addendum's sibling C:/Users/gabot/agentic-os-worktrees/win-m01-out is outside the writable sandbox. New-Item returned Access denied (rc 1). All real outputs instead live under this clone's runtime/_win-out, which is gitignored. The original task explicitly permits a runtime/ output; the addendum's exact external path could not be honored under the enforced sandbox. No escalation is available.

At session start, before reading TASK_INSTRUCTIONS.md, the generic AGENTS.md session-pickup command was attempted against the live checkout. It failed with PermissionError when creating a claim and returned 1; no assignment was claimed. The task-specific isolated-clone override was then followed. No further live-checkout operations were made.

Windows sandbox denied WRITE_DAC/icacls permissions. Installed payload files are marked read-only, and ordinary overwrite refusal is tested. This is an accidental-write safeguard, not a user security boundary; the owner can reverse attributes and add files. This limitation is documented, without silently falling back to a writable installed payload.

The official CPython Tcl tree has four unsigned optional binaries. The headless acceptance builds exclude cpython/tcl/*, cpython/Lib/tkinter/* and cpython/DLLs/_tkinter.pyd instead of allowing those binaries. Third-party native .pyd files are explicitly allowed by the site-packages glob below. All other inventoried PEs must have Valid signatures.

## Exact build and verification commands

Working directory for commands below: C:/Users/gabot/agentic-os-worktrees/win-m01-runtime.
All Python commands use the required PSF-signed runtime, or the packaged PSF-signed launcher in the installed acceptance app.
PowerShell snippets capture $LASTEXITCODE immediately; exit statuses below are process statuses, not pipeline success.

```powershell
$python = 'C:/Users/gabot/agentic-os-runtime/py311/Scripts/python.exe'
# runtime/_win-requirements.txt contains three lines: PyYAML, psutil, langgraph.
& $python -B packaging/windows/build_runtime.py build `
  --python-home C:/Users/gabot/agentic-os-runtime/cpython-3.11.9 `
  --site-packages C:/Users/gabot/AppData/Local/hermes/hermes-agent/venv/Lib/site-packages `
  --requirements runtime/_win-requirements.txt --out runtime/_win-out/build1 `
  --allow-unsigned 'venv/Lib/site-packages/**/*.pyd' `
  --exclude 'cpython/tcl/*' --exclude 'cpython/Lib/tkinter/*' --exclude 'cpython/DLLs/_tkinter.pyd'
# Repeat identically with --out runtime/_win-out/build2.
& $python -B packaging/windows/build_runtime.py verify --runtime runtime/_win-out/build1
& $python -B -m unittest tests.test_build_runtime tests.test_build_package
& $python -B scripts/validate.py
& $python -B packaging/windows/build_package.py --runtime runtime/_win-out/build1 `
  --repo . --sha b4aee5f --version 0.1.0-prototype --out runtime/_win-out/package-final1
# Repeat identically with --out runtime/_win-out/package-final2.
$a = (Get-FileHash runtime/_win-out/build1/runtime-manifest.json).Hash
$b = (Get-FileHash runtime/_win-out/build2/runtime-manifest.json).Hash
if ($a -ne $b) { exit 1 }
$a = Get-Content runtime/_win-out/package-final1/SHA256SUMS -Raw
$b = Get-Content runtime/_win-out/package-final2/SHA256SUMS -Raw
if ($a -ne $b) { exit 1 }
& $python -B -c "import zipfile; zipfile.ZipFile('runtime/_win-out/package-final1/AgenticOS-0.1.0-prototype.zip').extractall('runtime/_win-out/unpacked-final')"
$prefix = Join-Path $PWD 'runtime/_win-out/prefix'
powershell -NoProfile -ExecutionPolicy Bypass -File runtime/_win-out/unpacked-final/Install-AgenticOS.ps1 `
  -AppRoot "$prefix/apps" -StateRoot "$prefix/state" -ProjectsRoot "$prefix/projects"
& $python -B runtime/_win-out/e2e.py
```

The e2e.py driver records expanded argv, stdout/stderr, process return codes and heartbeat samples in runtime/_win-out/e2e-results.json. It verifies the relocated installed runtime, launches AgenticOS.cmd in a hidden background process, waits for both ticks to increase, calls status and stop, waits for launcher exit, checks every recorded process identity is gone/reused, uninstalls, asserts state/projects retained, then reinstalls. It never loops supervisor starts.

Guard pack command:

```powershell
& $python -B runtime/_win-out/run-guards.py
```

That driver copies current tracked files (including working-tree modifications) plus the new package source/tests into an OS temporary source snapshot, omitting generated/ignored build outputs. It writes a .git pointer back to the read-only source Git metadata, so provenance has the actual commit. It runs exactly:

```text
C:/Users/gabot/agentic-os-runtime/py311/Scripts/python.exe -B -m unittest tests.test_import_guard tests.test_dispatch_executor tests.test_console_encoding tests.test_process_ownership_fencing tests.test_provenance_deploy_root
```

The snapshot path and SHA-256 of every copied source file are in runtime/_win-out/guard-snapshot.json. Final snapshot: C:/Users/gabot/AppData/Local/Temp/win-m01-guards-zbz4qtbv. Two earlier direct guard attempts were stopped because executor fixtures recursively copied the large generated runtimes. An initial metadata-free snapshot returned 1 (39 tests, one malformed-provenance result from missing Git SHA); the final snapshot preserves Git identity and passes. No test source was modified to bypass the failure.

## Results

| Check | True process exit / result |
| --- | --- |
| Runtime build1 | 0 |
| Runtime build2 | 0 |
| Runtime manifest comparison | identical, comparison rc 0 |
| Runtime verify build1 | 0 |
| Runtime/package unit tests | 0; 18 tests, 34.196 seconds |
| Required guard pack | 0; 39 tests, 148.181 seconds |
| scripts/validate.py | 0; Validation passed (existing deprecated event warnings) |
| Final package build1 | 0 |
| Final package build2 | 0 |
| Final SHA256SUMS comparison | identical, comparison rc 0 |
| Final package extraction | 0 |
| Real final install | 0 |
| Installed runtime verify | 0 |
| Heartbeat advancement | builder 1 -> 2; claude 1 -> 2 |
| AgenticOS.cmd status | 0; both layers running/ticking |
| AgenticOS.cmd stop | 0; graceful: recorded supervisor tree is gone |
| Launcher process exit | 0 |
| Recorded-process survivor check | 0; all gone |
| Final uninstall | 0; stopped tree confirmed, app/current removed |
| State/projects preservation | 0; both roots still exist |
| Final reinstall | 0 |
| Complete end-to-end driver | 0 |

Runtime manifest SHA-256 (both builds): 989a02da878401e96b3f4f0dd526de12274559e9c5a0ac98bdded7713a92469b.
Final ZIP SHA-256 (both builds): 077169ef5f835e366ee44ce07b7b2c507bb7735ff4fd1c9b937724ccf7fac1ad.
Runtime inventory: CPython 3.11.9, 36 distributions, 3443 files, 48 PEs, 12 explicitly allowed NotSigned third-party .pyd files. Distribution versions and exact PE paths/status/subjects are recorded in runtime-manifest.json and package-manifest.json.

Evidence under runtime/_win-out/: real-build1.log, real-build2.log, package-final1.log, package-final2.log, unit-final2.log, guards-final.log, guard-snapshot.json, validate.log, install-final.log, e2e.log, e2e-results.json, supervisor.log. The initial prototype package was installed and uninstalled successfully before final packaging; the final acceptance uses package-final1 and unpacked-final. An exploratory installed verify overlapped that initial removal and returned 1 for removed files; final installed verification is performed separately before any lifecycle mutation.

## Trust and production gaps

This is an offline integrity/installability prototype, not MSIX or a signed publisher release. PSF signatures cover CPython executables, not our Python/PowerShell source or third-party extensions. Unsigned manifests/checksums need a separately trusted delivery channel; replacing manifest and payload can forge integrity. RECORD verifies consistency with trusted source metadata, not publisher authenticity. Source packaging marker evaluation and smoke imports execute trusted input code. The fallback conservatively includes unknown markers and may fail on optional dependencies; version constraints/ABI resolution are not implemented.

pyvenv.cfg uses an audited runtime-path-template SHA-256 to make manifests identical across build roots. Install rebinds only its home line; runtime verification and rollback verification check the normalized hash at the installed path. Package raw hashes cover the original pre-rebind bytes; install.json and the home rebind are explicit install-time additions/changes. Runtime build-info.json is intentionally outside the deterministic package.

Production follow-up: signed bootstrap/manifest anchoring, MSIX identity/publisher signing, app ACL hardening, installer concurrency lock, transactional recovery after power loss and logon registration failures. No scheduled task was registered during acceptance. Uninstall fails closed on unverified stop identities, keeps state/projects unless removal is explicitly requested, and does not delete interrupted staging artifacts. The launcher guards three nonzero exits in 30 minutes without retry loops; forcibly killing the launcher cannot persist an exit it never observes.

## Final real lifecycle evidence

The final acceptance driver returned 0. Both heartbeat counters advanced 1 -> 2.
Supervisor PID 41408 and recorded process PIDs 42968, 30000, 25500, 29700 were all
verified gone after stop; launcher PID 38696 exited 0. The final app is installed
at runtime/_win-out/prefix/apps/0.1.0-prototype, with current.json restored. It is
stopped. State and projects remain at runtime/_win-out/prefix/state and
runtime/_win-out/prefix/projects. No scheduled logon task was requested or created.

These are the lifecycle commands expanded by e2e.py (the start uses a hidden
subprocess and waits for both heartbeat files before invoking stop):

```powershell
$app = "$prefix/apps/0.1.0-prototype"
& $python -B packaging/windows/build_runtime.py verify --runtime "$app/runtime" # rc 0
# cmd /c "$app/AgenticOS.cmd"   # launcher process eventually rc 0
& "$app/AgenticOS.cmd" status # rc 0
& "$app/AgenticOS.cmd" stop   # rc 0, graceful; recorded tree gone
powershell -NoProfile -ExecutionPolicy Bypass -File runtime/_win-out/unpacked-final/Uninstall-AgenticOS.ps1 `
  -AppRoot "$prefix/apps" # rc 0; state/projects kept
powershell -NoProfile -ExecutionPolicy Bypass -File runtime/_win-out/unpacked-final/Install-AgenticOS.ps1 `
  -AppRoot "$prefix/apps" -StateRoot "$prefix/state" -ProjectsRoot "$prefix/projects" # rc 0
```

The original runtime build path and copied interpreter home are not required by
the installed runtime: installed verification checks its rebinding, and the real
supervisor/stop ran with the packaged interpreter. The exported app has no .git,
so layer status reports config_root_git_sha null; the source SHA is retained in
package-manifest.json and install.json.

Final review checks: git diff --check returned 0; every source file in the passing
guard snapshot still has the same SHA-256 (only this allowlisted handoff was
written afterwards). Existing TASK files and codex output logs from the interrupted
run were left untouched. No commit was created.