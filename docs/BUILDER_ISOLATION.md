# Builder filesystem isolation

Status: **blocked pending real Windows boundary proof and installed CLI verification**.
Do not enable automatic Grok execution on the basis of this change.

## Boundary

The supervisor provisions a standalone clone, with the T-M1-30 unique directory
and branch naming scheme. `allocate_worktree(..., standalone_clone=True)` uses
a fresh `git init`, supervisor-created bundle, local bundle fetch, and checkout
of the specified base SHA on the unique branch. This produces a standalone
clone without object borrowing, hardlinks or shared metadata. Linked Git worktrees, common Git dirs,
object alternates, reparse points and hardlinks are refused by the launcher.
The legacy operator allocator retains its default behavior; supervisor builders
explicitly select standalone clones. Existing linked workspaces cannot resume.
The legacy `dispatch/local_builder_core.py` production route does not yet
provision the new contract/hash and is therefore refused by the shared launch
gate. Migrating that route is outstanding; it must not receive a bypass. Its
post-build Git/acceptance subprocesses also need isolation before enabling it.

`orchestrator/builder_isolation.py` uses stdlib ctypes CreateRestrictedToken
with DISABLE_MAX_PRIVILEGE (0x1), zero restricting SIDs, and Low integrity
(SetTokenInformation). WRITE_RESTRICTED and the random SID/DACL grant path
were removed: reviewer real-token evidence shows WRITE_RESTRICTED prevents
process initialization on this host. Setup failures refuse launch without fallback.

Only the active standalone clone, including `.agentic/profile`, is recursively
labelled Low. A global Windows mutex serializes builder execution (one builder
at a time). Under that gate the launcher inspects mandatory labels throughout
the supervisor-configured builder inventory, including protected children,
and refuses any stale Low label. It does not silently relabel other workspaces.
The supervisor passes the allocator inventory root for primary, fallback and
acceptance launches. Direct callers default to the workspace's parent and must
supply AGENTIC_BUILDER_INVENTORY_ROOT for nested inventories.

When the root exits, the launcher terminates any remaining job descendants,
waits for zero active job processes, restores the clone recursively to Medium,
and verifies that no Low labels remain before returning a terminal poll/wait
result. A partial setup failure also restores labels. Restoration errors block
completion, retain the gate, and prevent import. The import path independently
refuses Low-labelled results. A crashed supervisor may leave stale labels;
the next launch refuses until a trusted operator restores them to Medium.
No user account, elevation, system policy or protected-root DACL is changed.

Low integrity is a write boundary for Medium objects, not an exclusive writable
path allowlist. LocalLow and other Low-labelled paths remain writable. Low
processes can still READ user files; confidentiality is outside this boundary.
UIPI blocks window messages to Medium processes. These residuals apply to all
descendants. Do not place Agentic OS state in Low-labelled locations.

The process starts suspended, enters a kill-on-close Job, then resumes. Jobs
provide process ownership and descendant termination, not filesystem isolation.
Only explicitly allowlisted pipe handles are inherited through STARTUPINFOEX.
The supervisor relays those pipes to its log files; no writable supervisor file
handle or token handle is given to the builder. Descendants inherit the token
and job. Read access is not sandboxed by this mechanism.

The builder environment is constructed from a small system-variable allowlist.
HOME, USERPROFILE, APPDATA, LOCALAPPDATA, TEMP, TMP, XDG directories and GROK_HOME
point at the private profile. Live state/config roots, inherited credentials,
Git redirections and Python injection variables are absent. No authentication
material is copied. CLI authentication under this profile is **not verified**.
Do not copy an entire user profile or relax isolation to make login work.

Acceptance commands also run through the isolated launcher. The Medium
supervisor never executes task acceptance code itself. Successful results are
fetched from a local bundle created by the supervisor from the standalone clone. Before import, the stopped
clone is checked again for shared metadata/reparse points/hardlinks and its
untrusted Git config is replaced with a minimal config disabling hooks and
fsmonitor. No automatic standalone-clone deletion has been added; preserve it
for review. The existing linked-worktree cleanup command will refuse it.
Even `git clone --local` invoked Git for Windows' MSYS upload-pack shell and
failed here with a CreateFileMapping access denial. Bundle-backed provisioning
and import avoid that shell transport. Git uses file-only protocol, ignores
system/global configuration for these operations, and receives no inherited
Git environment overrides; user configuration is not modified. Import uses a
relative local bundle source, preventing Windows drive syntax from being
interpreted as an SSH remote. The real clone/import regression now passes and
checks object independence with the workspace containment scan.

## Local contract

The supervisor copies task YAML into `.agentic/task.yaml`, writes
`.agentic/TASK_CONTRACT.json` and a Markdown rendering, and records the SHA-256
and contract in its run directory. `.git/info/exclude` ignores `.agentic/` and
tracked contract artifacts are refused. The checked-in JSON schema is validated
with a stdlib validator for the exact subset that schema uses. The launch gate
requires the expected supervisor hash, valid fields, rendering, and all relevant
files. Paths must be relative and contained; missing relevant files report
`contract_files_missing`. Missing scope or an unusable task contract is a
prelaunch failure routed to `reviewable_failure`.

An optional task `contract` mapping provides the schema fields. Otherwise the
objective, execution allowed paths, verification commands and handoff path are
derived conservatively and `derived` is true. Acceptance prose is not executed
as a shell command. Contract acceptance commands are argument vectors parsed
from strings, without a shell; use separate commands rather than shell pipelines.
The supervisor checks allowed changes, handoff presence, out-of-scope edits and
acceptance exit codes before recognizing successful production completion.

Prompts refer to the local contract and include its summary, with explicit
already-assigned/no-pickup/no-external-path rules. Absolute paths in the summary
are refused. AGENTS.md exempts assigned builders. The four assignment/lock CLIs
return exit 3 before parsing arguments when AGENTIC_BUILDER_RUN_ID is set. These
rules and environment changes are defense in depth, not the OS boundary.

## Detection and progress

The supervisor snapshots `(path, size, mtime_ns)` under inbox, claims, locks and
tasks before launch and compares after monitoring. Only its exact assignment
inbox/claim and logical-task lock paths are excluded. Unexpected changes or
outside-path streaming calls produce `isolation_violation`, one deduplicated
alert, a failed run routed to reviewable failure, and diagnostic evidence.
The streaming watcher stops the process tree on an outside-path call.

At 40% of the contract turn budget, absence of an allowed change or PLAN.md
produces one `no_early_progress` alert and operator poke, including tool counts
and the last ten targets. It does not terminate for lack of progress. Exhausted
turn budgets produce reviewable failure with a diagnostic rather than success
or an automatic extra turn budget. The Grok default remains 30 turns.

## Evidence and remaining verification

The real adversarial fixture in `tests/test_builder_isolation_contract.py`
uses temp directories only. It attempts create/append/rename/delete against a
fake canonical checkout, inbox/claim writes, fake canonical `.git` writes,
execution of an absolute-path writer and a descendant Python writer. It also
requires successful writes in the builder clone, its own `.git`, and scratch.
It is intentionally a failing test if the real OS boundary cannot be exercised;
it does not substitute mocks, skips, or a weaker token for boundary evidence.

Reviewer evidence from the unrestricted supervisor token (TASK_34C.md):

| Token variant | Result |
| --- | --- |
| 0x1 + 0x8, fresh SID | 0xC0000142, even cmd.exe |
| 0x1 + 0x8, no restricting SID | 0xC0000142 |
| 0x1 + 0x8, fresh SID + logon SID | 0xC0000142 |
| 0x8, fresh SID + logon SID | 0xC0000142 |
| 0x1, no restricting SIDs, Low IL | inside write succeeds; outside Medium file denied |

The reviewer adversarial matrix additionally denied canonical `.git` writes,
task YAML moves, inbox modification, claim deletion/creation, an absolute-path
child writer, HKCU writes, scheduled-task creation and another Medium builder
workspace write. LocalLow writes succeeded as expected. This evidence is
reviewer supplied, not a pass of the revised automated test in this sandbox.
Codex's restricted sandbox cannot run the real-token proof (WinError 87);
Claude must run the revised test under the unrestricted supervisor token.

Per the installed Grok README reported in the task contract, `--sandbox` uses
Landlock/Seatbelt only, not Windows. No Windows sandbox flag is enabled.
The README itself was not accessed outside this clone. Deny grammar and private
profile authentication still require installed CLI verification; no auth was copied.

Evidence replay tests consume only the copied Grok stream. They find 87 tool
calls and emit one progress checkpoint on usage event 12 of 30, plus outside
path evidence. No real canonical checkout, live state, deploy clone, assignment,
claim or lock was inspected or mutated during development.

## T-M1-34C supersedes the ACL repair

The T-M1-34B DACL helper and its tests were deleted because no restricting SID
is used. Mandatory-label inspection uses Win32 security descriptors and SDDL,
so stale-label detection does not depend on localized icacls output. The real
fixture uses only temporary stand-ins, unique HKCU/task names with cleanup,
byte-identical outside-file checks, another-builder checks and Medium-label
verification after completion. Setup-fault tests remain unit tests, not OS proof.
