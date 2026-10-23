# Windows runtime builder (prototype)

Run with a trusted PSF CPython interpreter. No installer, pip, uv, download, or
network request is used by the builder. Inputs are an existing official CPython
installation and a trusted, already populated site-packages directory.

```powershell
$python = 'C:/Users/gabot/agentic-os-runtime/py311/Scripts/python.exe'
& $python packaging/windows/build_runtime.py build `
  --python-home C:/Users/gabot/agentic-os-runtime/cpython-3.11.9 `
  --site-packages C:/Users/gabot/AppData/Local/hermes/hermes-agent/venv/Lib/site-packages `
  --requirements runtime/_win-requirements.txt --out runtime/_win-build1 `
  --allow-unsigned 'venv/Lib/site-packages/**/*.pyd'
& $python packaging/windows/build_runtime.py verify --runtime runtime/_win-build1
& ./runtime/_win-build1/venv/Scripts/python.exe -I -B -c 'import yaml, psutil, langgraph'
```

Requirements contain one bare distribution name per line; blank lines and #
comments are supported. Output must be new or empty. Failure leaves a partial
output for inspection; choose a new directory for retry. Exclusions are additive
case-insensitive fnmatch patterns against slash-separated RECORD paths. Defaults:
`*/__pycache__/*`, `*.pyc`, `../*`. Absolute paths, traversal and escaping symlinks
are rejected even with custom exclusions. RECORD hashes and declared sizes are
checked before copying. Entries without hashes (normally RECORD itself) are
inventoried with `verified: false`, not represented as authenticated source files.

The base CPython installation is copied into `cpython/`, excluding installed
site-packages, caches and ensurepip. The source interpreter creates `venv/` using
`-m venv --without-pip`; its configuration is then bound to the copied CPython.
Activation scripts are removed; launch the interpreter directly. Nothing depends
on the source installation after assembly. This is relocatable **per build**:
build directly at the intended destination. Moving a finished runtime requires
rebinding its pyvenv.cfg home and verifying again.

The source interpreter must have a Valid Authenticode signature with organization
Python Software Foundation. Every .exe/.dll/.pyd in the output is hashed and
checked with Get-AuthenticodeSignature, including the copied base interpreter.
Valid signatures from other publishers (e.g. Microsoft) are accepted for other
PEs. Only NotSigned files can be exempted by explicit --allow-unsigned globs;
invalid/revoked/hash-mismatch signatures cannot be exempted. Failures print exact
paths usable as allow globs. Prefer narrow globs after inspecting those files.
Python source, metadata, and third-party native extensions are not thereby PSF
signed. RECORD checks establish consistency with the supplied metadata, not
publisher authenticity. Source packages and metadata must be trusted: smoke
imports and source packaging marker evaluation execute their code.

Dependency closure uses source packaging.markers in an isolated subprocess,
with the target interpreter environment and extra=''. Requested dependency extras
are not activated. Compound markers retain their ordinary Boolean semantics.
If packaging is unavailable, the conservative fallback includes every marked
requirement, even optional ones; it can over-include or fail on missing optional
distributions. It never assumes an unknown marker is false. This prototype
resolves installed distribution names, not version constraints or wheel ABI
compatibility; the import smoke check supplies a limited compatibility check.
Top-level import names come from top_level.txt or RECORD, including namespaces.

runtime-manifest.json is deterministic, sorted, and timestamp-free. All files
have SHA-256 hashes. **Exception to raw-byte hashing:** pyvenv.cfg uses
hash_encoding=runtime-path-template: its build directory bytes are replaced by
`${RUNTIME}` before hashing. Absolute Windows venv home paths otherwise make
identical manifests at different destinations impossible. All other files use
hash_encoding=bytes. Verify performs the same normalization and reports changed,
missing, added files and changed signer status/subject. build-info.json holds
time and destination outside the deterministic manifest. Smoke uses -I -B so it
does not generate untracked bytecode. Use -B for later read-only runtime checks,
or expect verification to flag newly generated caches.

The manifest is not itself signed: an attacker able to replace both files and
manifest can forge a consistent bundle. This is an integrity/audit prototype,
not an MSIX installer or publisher-signed release. MSIX layout, certificate
provisioning, timestamping, offline certificate/revocation policy, signed manifest
anchoring, upgrade/rollback, runtime rebinding and third-party native signing
remain release-engineering work for a production release. The prototype installer
below implements local rebinding and version rollback. Authenticode trust is evaluated by local Windows
policy; results can change with the machine trust store or certificate state.

## Installable ZIP prototype

Assemble from a verified runtime and a committed application revision. Application
code comes only from `git archive <sha>`, so uncommitted changes are never silently
included. The installer and launcher templates come from this directory and are
individually hashed in the package manifest.

```powershell
& $python packaging/windows/build_package.py --runtime runtime/_win-out/build1 `
  --repo . --sha b4aee5f --version 0.1.0-prototype --out runtime/_win-out/package1
Get-Content runtime/_win-out/package1/SHA256SUMS
Expand-Archive runtime/_win-out/package1/AgenticOS-0.1.0-prototype.zip ./unpacked
powershell -NoProfile -ExecutionPolicy Bypass -File ./unpacked/Install-AgenticOS.ps1
```

The ZIP has sorted entries, fixed 1980 timestamps, fixed file permissions, and no
runtime build-info.json. Its SHA-256 is in SHA256SUMS. Compression reproducibility
assumes the same Python/zlib toolchain. package-manifest.json records every payload
file's raw SHA-256, source commit, runtime manifest hash, and PE inventory; it cannot
hash itself. Verify SHA256SUMS through a separately trusted channel before
extracting and executing the installer. Neither the manifest nor PowerShell scripts
are signed; someone who can replace the manifest and payload can forge a package.

Default install locations (no administrator privileges):

| Content | Location |
| --- | --- |
| Versions | `%LOCALAPPDATA%\Programs\AgenticOS\<version>` |
| Active pointer | `%LOCALAPPDATA%\Programs\AgenticOS\current.json` |
| Mutable state | `%LOCALAPPDATA%\AgenticOS\state` |
| Projects | `%USERPROFILE%\Documents\Agentic OS\Projects` |

Override with `-AppRoot`, `-StateRoot`, `-ProjectsRoot`; roots must be separate,
non-nested directories. Live checkout/deploy paths, drive roots and paths through
existing junctions/symlinks are refused. State starts with runtime/, tasks/, logs/.
No task is registered by default. `-RegisterLogonTask` explicitly registers a
per-user interactive logon trigger with no repetition or scheduler restart policy.
The task name includes an app-root hash. Upgrades and rollback update its target;
uninstall removes only the recorded task.

The installer checks every package file and rejects extra files before copying,
checks the staging copy again, rebinds runtime/venv/pyvenv.cfg to the final copied
CPython, writes install.json, marks installed files read-only, then activates
current.json. Read-only attributes prevent ordinary file overwrites; they are not
an ACL security boundary and the owner can remove them or add files. No WRITE_DAC
privilege is required. Installed pyvenv.cfg differs from its raw package hash by
the documented home rebind; `build_runtime.py verify --runtime <app>/runtime`
verifies the normalized runtime hash at its installed location. Stop an active
supervisor before upgrade. Failed integrity checks leave the active pointer alone;
other interruptions can leave an inactive staging/version directory for inspection.
Do not run multiple installers/uninstallers concurrently.

Install a new version with the same three roots. The active version and its
previous version are kept; older recorded versions are pruned. `-Rollback` swaps
the pointer back to the previous version (and can swap it forward again).

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File ./unpacked/Install-AgenticOS.ps1 -Rollback
$current = Get-Content "$env:LOCALAPPDATA/Programs/AgenticOS/current.json" -Raw | ConvertFrom-Json
& "$($current.app_root)/AgenticOS.cmd"           # foreground; no restart loop
& "$($current.app_root)/AgenticOS.cmd" status    # complete layer status JSON
& "$($current.app_root)/AgenticOS.cmd" stop      # audited graceful stop, then owned tree
powershell -NoProfile -ExecutionPolicy Bypass -File ./unpacked/Uninstall-AgenticOS.ps1
```

The launcher exports state/config roots and disables bytecode writes. It invokes
the packaged interpreter and existing supervisor/stop entrypoints. A state-local
exclusive launcher lock prevents competing starts. Three nonzero supervisor exits
within 1800 seconds persist in launcher_crashes.json; the next start exits 78 with
recovery instructions. Status and stop remain available. No automatic retry loop
exists. `Launch-AgenticOS.ps1 -PythonExecutable <path>` is a local test seam used
with a fake command that exits 1; normal AgenticOS.cmd always selects the packaged
runtime. A forcibly killed launcher cannot record a supervisor exit.

Uninstall uses the existing identity-fenced stop command (15-second graceful
timeout, then only the recorded owned tree); stop failures retain the installation.
It removes active/previous app versions and current.json. State and projects are
kept unless explicitly passed `-RemoveState` and/or `-RemoveProjects`. Back up
valuable state before testing these removal options. Empty app-root and inactive
staging artifacts may remain after interrupted installations.

The offline test suite is `python -B -m unittest tests.test_build_runtime
tests.test_build_package` using the trusted interpreter. Package tests invoke real
Windows PowerShell under temporary prefixes, with synthetic distributions/archive
and no real signature calls or network. The real acceptance run excludes optional
unsigned CPython Tcl/Tk files for this headless supervisor, and explicitly allows
the inventoried third-party .pyd files. MSIX identity, publisher signing, signed
bootstrap/checksums, installer locking, stronger app ACLs, and transactional recovery
after power loss remain production gaps.
