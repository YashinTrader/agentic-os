# AOS-WIN-001 — Windows Desktop Distribution

**Status:** design accepted by the Director, 2026-10-23. Paid items and publisher identity are reserved for the owner (section 9).
**Trigger:** on 2026-10-23, Smart App Control (SAC) blocked the unsigned uv/Hermes venv launcher. The live builder layer lost its interpreter. The way Agentic OS ships today depends on Hermes, uv, Git and an unsigned venv, all trusted only on reputation, and that is not a product.
**Constraint:** this track must not block restoring the owner's current installation. That recovery path runs separately (`agentic-os-ops/releases/R12/RUNTIME_DECISION.md`) and reuses this track's runtime builder.

## 1. Decision summary

| Question | Decision |
|---|---|
| Primary channel | **MSIX through the Microsoft Store.** The Store signs the package, so we need no certificate of our own for this channel, SAC trusts it by publisher, updates and rollback come with the Store, and per-user install needs no admin |
| Direct channel | **A signed MSIX for sideloading, plus a signed per-user EXE bootstrapper (WiX Burn or NSIS) that installs it.** Both are signed with a publicly trusted certificate (Azure Artifact Signing, formerly Trusted Signing, is preferred). It never asks the user to import a certificate |
| Runtime | **Bundled CPython embeddable distribution** (PSF-signed binaries), a pinned minor version, and a **hash-locked wheel set** resolved at build time. The core path needs no Hermes, uv, pip, Git, WSL2 or Docker on the user's machine |
| Product Python version | **3.13** (mature wheels, security support until 2029-10), confirmed in WIN-M01. 3.11.9 is only the **bridge** for restoring the owner's current install, because no newer 3.11 Windows binaries exist |
| Process model | A per-user **supervisor host** (`AgenticOS.Supervisor.exe`, a signed native stub that embeds the runtime) owns the existing Python supervisor inside a **Windows Job Object**. A separate **desktop shell** (`AgenticOS.exe`) talks to it over an authenticated local named pipe or loopback API |
| UI | **Tauri 2** (Rust plus WebView2, which ships in Windows 11). It packages to MSIX and MSI/NSIS and is small. The existing stdlib dashboard (`dashboard/app.py`) becomes the first API surface |
| Credentials | **Windows Credential Manager** (DPAPI, per user) behind a `SecretStore` interface. Keys reach agent CLIs only through the environment of the child process that needs them, never on the command line. All logs pass through a redaction filter |
| State | Signed application files are immutable (`WindowsApps`, or `%LOCALAPPDATA%\Programs\AgenticOS\<version>` for direct installs). Runtime state lives in `%LOCALAPPDATA%\AgenticOS\state`. **User projects** live in a user-chosen folder (default `Documents\Agentic OS\Projects`) that is never virtualized or removed |
| Third-party agents | **Optional adapters** (Claude Code, Codex, Grok, Gemini, Antigravity). They are detected, never bundled or downloaded silently. Each adapter declares its executable and how its signature is verified, and the core works with none installed (local missions, review-only, dry run) |
| Git | The core needs repository operations. Bundle **MinGit** from Git for Windows (signed upstream; GPL with a source offer) as a separate, verified component, or use libgit2 through pygit2 (signed by us). Decided in WIN-M02 by binary count and licence review |

**Not chosen:**
- Electron: an 80–150 MB runtime per install, and a second JS runtime to keep patched.
- WinUI 3 alone: its C# UI work duplicates the existing web dashboard.
- A Windows Service: needs admin, which violates requirement 10.
- PyInstaller/Nuitka one-file builds: self-extraction to `%TEMP%` produces unsigned executables at runtime, which SAC blocks and AV flags.
- WSL2 or Docker: banned by requirement 6.

## 2. Architecture

```
AgenticOS.exe (Tauri shell, signed)  ──pipe/loopback + per-session token──►  AgenticOS.Supervisor.exe (signed stub)
   accounts · projects · missions                                               │  Job Object: KILL_ON_JOB_CLOSE, breakaway denied
   budgets · logs · results · diagnostics                                       ▼
                                                                            runtime\python.exe (PSF-signed, embeddable)
                                                                              └─ existing supervisor (run_supervisor_layers.py)
                                                                                   ├─ builder / claude-consumer layers
                                                                                   └─ adapter children: agent CLIs (optional, user-installed)
```

**Lifecycle:**
- **Startup at logon:**
  - MSIX: the `windows.startupTask` extension, which the user can toggle.
  - Direct install: a per-user Task Scheduler task with a logon trigger.
  - No admin either way.
- **Shutdown:** the existing graceful stop (T-M1-25 `stop_supervisor`). The host then closes the Job handle, so no orphan process can survive.
- **Crash recovery:** the host restarts the Python supervisor with exponential backoff and a circuit breaker. The existing layer circuit stays the inner loop. After N failures in a window, the shell shows the error and offers the diagnostics bundle.
- **Process ownership:** Job Object membership replaces name- and command-line-based process scanning on Windows. The psutil inventory stays only for legacy adoption.
- **Rollback:** Store/MSIX versions are side by side and the previous package can be restored. Direct installs keep the previous `Programs\AgenticOS\<version>` until the new version passes a health check. State schema migrations are versioned and reversible, and a pre-upgrade state snapshot is taken.

**Code reuse:**
- The supervisor, dispatch, ledger and adapters run unchanged on the bundled runtime.
- The new code is the host stub, the shell, the path abstraction and the secret store.
- `AGENTIC_OS_STATE_ROOT` and `AGENTIC_OS_CONFIG_ROOT` already separate state from code (T-M1-17/T-M1-22). WIN-M03 removes the remaining assumption that the state root is a Git checkout.

## 3. Installer and dependency design

**Build pipeline** (CI on `windows-2025` runners; reproducible from the lock files):
1. **Fetch the runtime.** Download the CPython embeddable zip from python.org. Verify its SHA-256 against the release page and the Authenticode signer (Python Software Foundation) of every PE file.
2. **Resolve dependencies.** Install from `requirements-core.lock`, which is hash-pinned (`--require-hashes`, `--only-binary=:all:`). Pins are produced by `uv pip compile --generate-hashes` on the build machine only. The core set is PyYAML and psutil, plus langgraph and its closure (36 dists measured on 2026-10-23). Optional extras such as cognee are separate locks and are not shipped in core.
3. **Inventory binaries.** Every `.exe`, `.dll` and `.pyd` is recorded with its SHA-256, origin wheel and RECORD hash, and its signer status, in `binary-inventory.json`. The build **fails** on any PE file not in the allowlist. Measured on 2026-10-23: the 3.11 closure has 12 unsigned third-party `.pyd` files (pydantic_core, orjson, ormsgpack, psutil, PyYAML, uuid_utils, websockets, xxhash, zstandard ×2, charset_normalizer ×2). pip's distlib launchers and Tcl DLLs are excluded entirely.
4. **Sign.** There are two different mechanisms, and they must not be confused:
   - **MSIX package signing.** `AppxSignature.p7x` signs the package's block map, so every file's hashes are covered as a unit. It does **not** put an Authenticode signature into the individual `.exe`, `.dll` or `.pyd` files. For packaged processes, Windows validates images through the package's signature. Whether Smart App Control accepts a load of an internally unsigned PE file from an installed package depends on how the package was signed:
     - **Store-signed:** the Store re-signs the package with Microsoft's certificate.
     - **Our certificate:** the package is signed with our publicly trusted certificate.

     This is an empirical question to prove on clean SAC-On machines (WIN-M04), not an assumption.
   - **Authenticode on individual PE files.** An embedded signature in each `.exe`, `.dll` or `.pyd`. This is the only trust anchor for anything that is **not** loaded from an installed MSIX package: a ZIP or per-user directory install, a bootstrapper EXE, files copied out of a package, and tools spawned from outside the package context. (Per-file catalog signatures need a system-wide catalog install, which requires admin, so they are out of scope.)

   | Channel | Package signature | Per-PE Authenticode | Required proof on clean SAC-On machines |
   |---|---|---|---|
   | Store MSIX | Microsoft Store | Not required by design. Ours are signed anyway where we build them | Install, launch, and import of every native `.pyd` with 0 Code Integrity blocks |
   | Sideloaded MSIX | Our certificate (publicly trusted) | **Required for every shipped PE** until the proof shows package trust alone suffices under SAC | Same, plus behaviour with SAC in Evaluation mode |
   | Bootstrapper EXE | — | Our certificate | Launches under SAC with no SmartScreen block once the reputation of the signed identity is established |
   | Per-user directory or ZIP (prototype and internal bridge only) | — | **Required for every PE**. PSF-signed CPython plus our signature on third-party `.pyd` files | 0 Code Integrity blocks across start, restart, every import and stop |

   The build fails if any shipped PE file is unsigned in a channel that requires per-PE Authenticode. The third-party `.pyd` files in today's bridge runtime are unsigned; that is a documented gap of the internal bridge, not acceptable for release.
5. **Package.** MSIX (`runFullTrust`, `startupTask`, no broad capabilities), plus the bootstrapper EXE for direct installs. Packaging also produces an SBOM (CycloneDX) and the inventory.
6. **Verify.** The clean-machine matrix in `AOS-WIN-001_CLEAN_MACHINE_TEST_PLAN.md`.

**Install footprint (estimate):**
- Runtime: about 25 MB.
- Core wheels: about 40 MB.
- App and host: about 10 MB.
- Shell: about 10 MB.
- Total: roughly 85–90 MB. MinGit adds about 45 MB.

**Prerequisites:**
- **None for the core.** WebView2 ships with Windows 11 24H2+. No runtime downloads.
- **Crash-loop guarantee:**
  - The launcher refuses to start after 3 non-zero exits in 30 minutes (exit 78, one actionable message).
  - The supervisor classifies policy denials as `BLOCKED_SECURITY_POLICY` and never retries them.
  - Status writes are budgeted: ≤0.2/s healthy, ≤1/min parked.
  - The logon task has no repetition trigger.
  - Installation or runtime failures therefore cannot trap users in a high-resource loop (incident 2026-10-23).

**Uninstall:**
- Removes the app files, the logon task or startup task, and the credential entries under the `AgenticOS/` target prefix.
- Asks before removing runtime state. MSIX virtualized app data is removed by Windows, so the shell offers **export** first.
- **Never** touches the projects folder unless the user explicitly asks.

## 4. Security and code-signing strategy

| Topic | Rule |
|---|---|
| Windows security | Never disable or bypass SAC, Defender, Code Integrity or SmartScreen. Installation never adds exclusions |
| Trust anchor | Store channel: the Microsoft Store signature. Direct channel: a publicly trusted code-signing identity. **Azure Artifact Signing** is preferred because it uses a Microsoft-trusted CA, HSM-held keys, short-lived certs and CI integration, at about USD 10 a month. Its identity validation has eligibility limits by country and entity type, so this is an owner decision. The alternative is an OV certificate on an HSM token (about USD 200–400 a year). An EV certificate no longer gives instant SmartScreen reputation, so it is not worth the premium |
| Runtime downloads | Nothing executable is fetched at runtime. Updates arrive only as complete signed packages. Adapters for third-party agents point the user to the vendor's official installer and verify the vendor signature before first use |
| Secrets | Credential Manager or DPAPI. Secrets never appear in argv or in state files, and the log pipeline redacts them (key-shaped values plus known secrets, registered at load). A redaction canary in tests fails the build if a seeded key appears in any log, status file or diagnostics bundle |
| Least privilege | Per-user install only, no admin, no services, no firewall rules (the API binds to loopback or a named pipe with a per-session token and a user-only ACL). The MSIX capability list is the minimum |
| Updates | Store channel: the Store's own updates. Direct channel: MSIX App Installer (`.appinstaller`) or the Tauri updater with a signed manifest. Both verify the signature and version monotonicity and keep N-1 for rollback |
| Supply chain | Hash-locked wheels, pinned build images, an SBOM and binary inventory per release, and reproducibility checked by rebuilding in CI and diffing the inventory |
| Diagnostics | A user-triggered ZIP: versions, inventory check, Code Integrity and SAC event summaries (read-only), redacted logs, and supervisor status. It is never uploaded automatically |

## 5. Support boundaries (v1)

- **Public release target:** Windows 11 **24H2 and later**, x64, standard user, SAC On/Evaluation/Off, Defender or a third-party AV.
- **Out of scope unless a specific support decision is made:** all other Windows releases, including Windows 10 and Windows 11 before 24H2. Also out of scope: ARM64 (planned once all core wheels ship win_arm64), Windows Server, multi-user shared installs, enterprise WDAC policies stricter than SAC, and running agents as admin.
- **Third-party agents:** each is the user's own account and install. Agentic OS supports the adapter contract, not the vendor's CLI.

## 6. Missions (each ≤ 4 h; GO / FIX / NO-GO per the release policy)

| ID | Outcome | Evidence for GO | Builder |
|---|---|---|---|
| WIN-M01 | `packaging/windows/build_runtime.py`: embeddable CPython plus hash-locked core wheels, binary inventory and signer report. **The prototype**, which also produces the 3.11 bridge runtime for the owner's install | A deterministic inventory across two builds; imports of `orchestrator.graph`; the full suite passing on the built runtime | Codex (low) |
| WIN-M02 | Git dependency decision (MinGit vs pygit2), with a binary count, licence review and a worktree test on a clean VM | A decision note, plus worktree allocator tests passing without system Git | Claude decision, Codex spike |
| WIN-M03 | Path abstraction: the state root is no longer a Git checkout; projects root, state root and app root are separate | Supervisor smoke with a read-only app directory; existing provenance tests still green | Codex (medium) |
| WIN-M04 | MSIX prototype (dev-signed, **test VM only**): startupTask, Job Object host stub, SAC behaviour with unsigned `.pyd` inside the package | An install/start/stop/uninstall transcript on a SAC-On VM; Code Integrity event log clean | Codex (medium) |
| WIN-M05 | Supervisor host stub (Rust): Job Object, backoff restart, pipe API, graceful stop bridge | Crash/restart drill, no orphans after a host kill, stop rc 0 | Codex (medium) |
| WIN-M06 | `SecretStore` (Credential Manager) plus redaction canary across logs, state and diagnostics | The canary test, and keys absent from argv (process inventory check) | Codex (low) |
| WIN-M07 | Tauri shell v0: accounts, projects, missions, budgets, logs, results (read mostly), diagnostics button | UI E2E against the host on a clean VM | Codex (low) |
| WIN-M08 | Direct channel: signed bootstrapper plus `.appinstaller` updates plus N-1 rollback | Upgrade then rollback on a clean VM, with state preserved | Codex (medium); **needs signing approval** |
| WIN-M09 | Clean-machine CI matrix (section 7 of the test plan) running every release | A green matrix run attached to the release record | Codex (low) |
| WIN-M10 | Store submission package and listing (privacy policy, support page) | Store certification passed; **needs owner account approval** | Claude, then owner |

**Order:** M01 first (it also unblocks the owner's restoration), then M03 and M05 in parallel, then M04, then M06 and M07 in parallel, then M09, then M08, then M10.

## 7. Roadmap to public release

| Phase | Missions | Exit criterion |
|---|---|---|
| P0 — bridge | M01 (3.11 bridge build) | Owner's live install restored on a signed interpreter (separate owner approval) |
| P1 — runnable package | M01 (3.13), M03, M05, M02 | Supervisor runs from a read-only app directory under a Job Object on a clean VM with no Python, uv, Git or Hermes installed |
| P2 — installable | M04, M06, M07 | Dev-signed MSIX installs, starts at logon, survives a crash, and uninstalls cleanly on a SAC-On VM |
| P3 — trusted | M08, M09 (needs a signing identity) | Publicly signed direct installer passes the full clean-machine matrix, including upgrade and rollback |
| P4 — public | M10 | Store listing live; direct download page with signed hashes |

## 8. Risks

- **Unsigned third-party `.pyd` under SAC.**
  - Direct channel: mitigated by signing every shipped PE file ourselves.
  - Store channel: verified in M04.
  - If SAC rejects them inside MSIX, also sign them before packaging.
- **SAC cannot be re-enabled on a test VM once it is off** (it turns on only on clean installs), so the matrix needs fresh VM images per run. The plan uses checkpoints taken while SAC is still in evaluation or On.
- **Wheel availability for the chosen Python minor.** M01 checks every core dist for a win_amd64 wheel (or a pure wheel) and fails closed.
- **Agent CLIs change their install method or signature.** Adapters verify at first use and degrade to "unavailable" with a clear message.

## 9. Owner decisions required (nothing below is started without approval)

1. **Publisher identity:** an individual or a company name on the Store and the signing certificate.
2. **Store developer account:** registration is free for individuals and a one-time fee for companies; verify current terms at signup.
3. **Direct-channel signing:** Azure Artifact Signing (about USD 10 a month) or an OV certificate on an HSM (about USD 200–400 a year).
4. **Hosting** for direct downloads and the `.appinstaller` feed: GitHub Releases (free) or our own domain.
5. **Clean-machine VMs:** local Hyper-V with free Windows 11 evaluation images (no cost) or paid hosted runners if local capacity is insufficient.
