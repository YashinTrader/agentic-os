# AOS-WIN-001 â€” Clean-machine test plan

**Goal:** every release candidate proves install, start, restart, upgrade, rollback and uninstall on machines that have **never** had Python, uv, Git, Hermes, WSL2, Docker or developer certificates installed.

## 1. Environments

| ID | Image | SAC | Purpose |
|---|---|---|---|
| VM-A | Windows 11 24H2+ Enterprise evaluation (fresh install, Hyper-V checkpoint taken before first sign-in) | **On** (or Evaluation) | Main gate: the conditions that broke the owner's install |
| VM-B | Same image | Off | Control: separates SAC effects from other failures |
| VM-C | Windows 11, standard (non-admin) user, third-party AV | On | Least privilege and AV interaction |
| CI | `windows-2025` hosted runner | Off | Fast per-commit build, inventory and unit-level installer checks only. **Not** a clean-machine gate |

**Rules:**
- Each run reverts to the pristine checkpoint.
- Dev-signed packages are only ever tested on VMs, never on the owner's machine.
- Dev certificates are trusted on the VM through a test-only provisioning script that is never shipped and never documented for users.

## 2. Test matrix (automated with PowerShell plus WinAppDriver or the Tauri test driver; transcripts are evidence)

| # | Scenario | Pass criteria |
|---|---|---|
| T1 | Install as a standard user from Store sideload, `.msix`, or the bootstrapper | No UAC prompt; app files signed (Authenticode Valid on every PE); 0 new Code Integrity 3033/3077 events attributable to the package |
| T2 | First run with no agent CLIs | Shell opens; supervisor healthy in under 15 s; adapters show "not installed"; a dry-run mission completes |
| T3 | Logon start | Supervisor running within 60 s of logon; exactly one instance |
| T4 | Crash recovery | Kill the Python supervisor, then a layer child, then the host. Restart under 10 s; no orphans (the Job Object is empty after the host is killed); circuit opens after N crashes and the UI shows it |
| T5 | Graceful shutdown and sign-out | `stop` rc 0; no leftover processes; state is consistent on the next start |
| T6 | Credentials | Add a key in the UI, run an adapter with a fake CLI that echoes its environment hash. The canary key is absent from all logs, state files, argv and the diagnostics ZIP |
| T7 | Upgrade N-1 â†’ N with a mission in progress | Mission paused, resumed or failed as specified; state migrated; projects untouched |
| T8 | Rollback N â†’ N-1 | App runs; state snapshot restored; signature verified on the rolled-back package |
| T9 | Tampered update (bad signature or downgrade) | Rejected with a clear message; the current version keeps running |
| T10 | Uninstall (default) | App files, task and credential entries gone; projects folder intact; prompt offered for state export |
| T11 | Uninstall (remove all, explicit) | State removed; projects removed **only** if that box was ticked |
| T12 | Diagnostics | ZIP contains versions, inventory check, Code Integrity summary and redacted logs; size under 20 MB |
| T13 | Offline install and first run | Core works without network; adapters report "offline" |
| T15 | Forced crash loop (runtime exits 1 on start; executable blocked by policy) | At most 3 launch attempts, then refusal (exit 78) or a `blocked_security_policy` circuit with one alert. Supervisor-tree CPU â‰¤ 6 s/min, status writes â‰¤ 1/min while parked, no scheduler relaunch storm over 60 min |
| T16 | Per-PE trust audit | Every PE file in the installed app is either Authenticode-Valid or covered by the channel's proven package trust (section 4 table). The result is recorded per file |
| T14 | Reproducibility | Two builds from the same commit give an identical `binary-inventory.json` (hashes), apart from signatures and timestamps |

## 3. Gate

A release candidate needs:
- T1â€“T12 green on VM-A and VM-C.
- T1â€“T5 green on VM-B.
- T14 green in CI.

Any Code Integrity block attributable to our package is **NO-GO**, because it is a critical invariant. Results go under `agentic-os-ops/releases/<R>/` with the transcripts.
