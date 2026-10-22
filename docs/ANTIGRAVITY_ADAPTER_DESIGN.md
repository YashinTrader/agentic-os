# Antigravity CLI adapter: offline Phase 1

Status: experimental, disabled. Based on orchestrator-supplied agy 1.1.5 facts
dated 2026-10-22 in TASK_INSTRUCTIONS.md. No CLI execution, network requests,
credential inspection, live process termination, routing change, or supervisor
change was performed for this spike. The supplied real_probe_success_redacted.log is a redacted real successful probe.
The remaining synthetic glog fixtures are test inputs,
not observations of a live provider. Model IDs and labels in fixtures are examples.

## Execution contract and launch plan

`agents/antigravity_restricted_adapter.yaml` is intentionally absent from the
adapter registry, enabled-adapter list, routing defaults and fallback chains.
Both `enabled` and `supports_execution` are false. The only entry point is
`dispatch.antigravity_adapter.execute_experiment`; it refuses checked-in config.
The pure `build_launch_plan` can be inspected offline without version probes.
Changing these booleans alone is not Phase 2 approval or production promotion.

| Existing contract | Prototype mapping |
| --- | --- |
| ExecutionRequest identity and scope | Explicit logical task/run IDs, separate isolated git clone/worktree, allowlisted role, explicit model and expected backend label |
| ExecutionSafetyEnvelope | Worktree required; terminal sandbox; no extra directories; local keyring auth may still be used; provider network access required for future live execution |
| LaunchPlan | PATH-resolved agy executable, positional argv list, isolated cwd, minimal environment, `inherit_environment=False`, redacted command preview |
| Work ownership | Existing durable `work_lock.acquire`, run-fenced heartbeats and `awaiting_review`; no release merely because process exits |
| Process ownership | Shared `launch_process` invokes `owned_popen(shell=False)`; Windows suspended creation, Job assignment, creation identity, then resume |
| ExecutionResultContract | Classification, structured evidence, ownership metadata and FailureFingerprint; no automatic acceptance |
| Handoff v2 | Independent tests and diff review, sealed test evidence where available, honest repository verification, existing closeout gate before acceptance |

The command is:

```text
agy -p <prompt> --model <model> --sandbox --print-timeout <seconds>s --log-file <run_dir>/agy.log --mode <mode>
```

Read-only analysis uses `plan`. Only `isolated-development-experiment` uses
`accept-edits`. The builder has no arbitrary extra-argv parameter and never emits
`--add-dir` or `--dangerously-skip-permissions`. An explicit nonempty model is
required; there is no model default or retry fallback. Run directories resolve
outside and separate from the worktree (for example,
`<state root>/runtime/dispatch/runs/<run_id>/`), never via `--add-dir`, and execution requires a fresh directory, preventing
old completion evidence or pre-existing log symlinks from being consumed.
The worktree is the child cwd only; evidence files remain outside its workspace.
Resolved paths are checked so existing symlink ancestors cannot redirect run_dir
into the worktree. This placement still requires Phase 2 filesystem isolation
to prevent arbitrary external reads or writes.
The caller must provision the isolated worktree and a unique run directory;
this adapter does not allocate branches or alter assignment channels.

Environment forwarding is limited to platform/path/home/temp variables. Approval
keys, provider API keys, GitHub tokens and unrelated credentials are not inherited.
Home/profile access remains necessary for observed keyring authentication and is
also a configuration isolation risk. Authentication values are never read by the
prototype. The prompt is omitted from the command preview.

## Machine evidence and acceptance

Stdout is final text only: no stream JSON, schema-constrained output or token
usage is established. Only exact glog-framed records are parsed. Stored evidence
is a typed projection, never a copy of arbitrary messages; string fields redact
e-mail addresses. Raw stdout/stderr/agy.log are private runtime files and must
not be attached to handoffs. Export only sanitized structured evidence. Unknown
diagnostics, tokens and credentials are not projected into that evidence.

| Signal | Structured interpretation |
| --- | --- |
| Silent auth attempt / keyring / success / not logged in | Pending, authenticated, authentication_failed; initial pending state alone is not failure |
| Model resolver default / defaulting to CCPA | Resolver default observed; invalidates prior confirmation until a later exact backend label match |
| Propagating selected model override, label | Requested ID, independently expected label, final observed label; exact label equality confirms the request |
| Created conversation / conversation= | Conversation UUID |
| Terminal sandbox and applying agent mode | Applied sandbox and mode, distinct from requested flags |
| Permission settings initialized | Settings seen; `<nil>` or `request-review` alone is not a denial |
| Synthetic tool permission denied | Soft-denial count, even with exit 0; real denial wording remains unverified |
| Invalid unsandboxed permission rules | Separate permission_config_warnings count; settings warning does not fail the run |
| Stream goroutine exited, sending completion signal | Completion only when UUID matches the run conversation |
| doRefreshQuota | Quota event/liveness only; not exhaustion |
| Synthetic quota exhausted / exceeded / rate-limit / 429 diagnostics | Quota blocker; actual exhaustion vocabulary remains a Phase 2 question |

The expected model label must come from an independently established ID-to-label
mapping, never inferred from whatever label the CLI happens to emit. No mapping
is invented in production config. `Resolving model` and pre-auth resolver messages
alone cannot establish which backend ultimately ran. The last label/default
event wins. Missing or mismatched confirmation is `model_unavailable`, including
exit 0 and apparently useful stdout. A pre-auth CCPA default followed by an exact
backend label can pass; defaulting without that later confirmation cannot.

Classification reuses `failure_classify.Classification` and `FailureFingerprint`:
deadlines take precedence; then auth failure, quota exhaustion, unconfirmed model,
permission denial or unconfirmed sandbox/mode, candidate completion, generic
failure. Auth/quota retain the existing `blocked_authentication` / `blocked_quota`
categories. Model and permissions map to `blocked_external` process state with
`model_unavailable` and `permission_denied` categories. Unknown/nonzero exit or
missing/mismatched completion is failed. Candidate success requires all of:
completion UUID match, exit 0, exact model label match, sandbox/mode confirmation,
and no soft-denial. It still requires independent verification and handoff closeout.
Log activity and final answer text cannot substitute for acceptance.
Auth events are processed in log order: pre-login not-logged-in messages are
superseded by later keyring/silent-auth success; a subsequent authentication
failure blocks the run even after a print-mode attempt or completion.

## Deadlines, subagents and condition retries

Overall wall time is explicit and bounded to 1..1800 seconds (default 300); it is
both the CLI print timeout and the shared RunDeadlines overall limit.
`agents/run_deadlines.yaml` adds only this adapter: startup 180 seconds,
inactivity 600 seconds. Newly framed log records count as liveness; repeated
polling of unchanged logs does not reset the clock. Initialization can establish
liveness but cannot establish successful execution. Startup/inactivity/overall
expiry yields failed_launch/stalled/timed_out with category deadline. No stdout
polling or root PID liveness extends the overall deadline.

Internal subagents are within the same owned process tree and wall-clock budget.
No child has an independent deadline extension or automatic retry allowance.
The shared owned terminator is used on expiry, exceptions and after root exit
to clean remaining descendants. No name-based killing is added. Existing Job
creation identity checks remain authoritative. Tests mock all process creation
and termination; they establish wiring, not live descendant containment.
Server-side agents or breakaway/detached processes remain unproven. No observed
token usage or child token count exists; usage is null, never zero. Provider spend
cannot be hard-capped by a token estimate. Phase 2 must establish subagent limits
and whether they can be disabled before experiments with meaningful budgets.

All classifications have `retry_eligible=False`; no local retries or paid probes
are performed. `condition_retry_metadata` exposes auth/quota conditions through
the existing `builder_condition.schedule_next_eligible` backoff helper (initial
15 minutes) for future orchestration. It does not dispatch or change the scheduled
supervisor. The existing scheduler handles auth/quota, not model availability:
model_unavailable remains an external blocker requiring explicit re-evaluation,
never mislabeled as quota to trigger retry. Future integration must use existing
condition budgets and provider probes, rather than adding an adapter retry loop.

## Permissions and MCP isolation investigation

Offline inspection covered supplied flags/subcommands, repository MCP isolation
contracts, and local tracked docs/config/adapter references. The supplied facts
establish `plugin(s)`, `--project`, `--new-project`, `--agent` and `--sandbox`;
they do not provide plugin help, config schemas, project inheritance precedence,
a no-plugin flag, an MCP allowlist, or a user-config isolation switch. No fixture
establishes per-invocation MCP isolation. No live `agy plugins/help` inspection,
home config inspection or web lookup was permitted. Thus the result is
**unverified isolation gap**, analogous to Composer, not proof that no such
capability exists. LaunchPlan explicitly records `enforced: false`.

Terminal sandbox restrictions are not proof of filesystem, plugin, MCP or network
isolation. Plan mode is not established as a security boundary. Existing project
permission grants may be inherited. No automatic approval/bypass is permitted.
Headless print mode skipping subagent questions increases risk of inherited
capabilities. Keep this adapter disabled until separately reviewed live probes
resolve these questions or an external isolation envelope constrains them.

## Phase 2 probes and remaining risks

The orchestrator must separately authorize and run these probes; none is part
of this offline deliverable:

1. Pin executable/version, verify seconds-duration syntax, PATH resolution on
   Windows, final stdout semantics and flush order; never use permission bypass.
2. Establish explicit model ID-to-label mappings, invalid model/fallback behavior,
   consecutive override ordering and whether subagents can select other models.
3. Capture redacted auth failures and real quota exhaustion/reset diagnostics;
   distinguish background quota refresh from terminal exhaustion and validate retry timing.
4. Inspect plugin/MCP config and inheritance, `plugins/help`, project/agent config,
   per-invocation allowlisting or config isolation. Test inherited grants with a
   harmless controlled permission soft-denial and exact glog wording. The
   `soft_deny.log` fixture is synthetic; capture a real tool-permission denial
   string in Phase 2 before claiming observed denial coverage.
5. Verify `plan` and terminal sandbox restrictions on harmless writes, external
   directory reads, network and MCP calls in an externally isolated environment.
6. Verify native subagents remain within the Job, including root exit, cancellation,
   startup/inactivity/overall timeout and external agent services; measure total
   cost, usage visibility and child concurrency. Process tests require separate authorization.
7. Verify UUID/session/completion association, interrupted logs, log rotation,
   unknown severity/error diagnostics and whether accept-edits emits mode confirmation.
8. Demonstrate independent verification rejecting an exit-0 false success before
   considering registry, routing, supervisor or adapter promotion changes.

Glog is an undocumented textual interface and may change. Model labels are not
cryptographic attestations. A compromised child can forge its own logs; this
prototype cannot attest provider identity or enforce isolation from CLI claims.
Polling currently reparses the run log; high-volume/rotation behavior needs live
measurement before activation. Deadline termination failures preserve the work
lock for review. No success claim overrides these gaps.
