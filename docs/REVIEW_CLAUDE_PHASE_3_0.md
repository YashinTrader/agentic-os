# Claude Review — Phase 3.0 Dispatch Preview

- **Reviewer:** claude (architect/reviewer)
- **Date:** 2026-06-08
- **Scope:** Phase 3.0 dry-run dispatch preview layer
- **Branch:** `agent/composer/T-PHASE3-0-dispatch-preview`
- **Verification:** `py -m unittest` → **182/182 OK** (634 s); `py scripts/validate.py` → **Validation passed**; live `py scripts/preview_dispatch.py --json --no-write --no-log` → preview emitted, `executed: false`, no subprocess call.

---

## Verdict

**APPROVE**

Phase 3.0 lands exactly the scope promised in `docs/PHASE_3_DESIGN_SPEC.md` §I and `docs/PHASE_3_0_BLOCKERS.md` — adapter registry, preview module, CLI, read-only dashboard tab, validator extension, tests — and **no execution path**. The "no subprocess" claim is verifiable two ways: (a) `grep -E "subprocess|os\.system|os\.popen" dispatch/preview.py` returns only docstrings, and (b) `tests/test_dispatch_preview.py::test_preview_module_has_no_subprocess_import` enforces it as a regression test.

The merge can proceed. Phase 3.1 (execute path) remains blocked.

---

## ADR-0012 gates — Phase 3.0 status

| Gate | Requirement | Phase 2 | Phase 3.0 | Verification |
|------|-------------|---------|-----------|--------------|
| E1 | Explicit operator command only | ✅ | ✅ | no automatic dispatch loop, dashboard has no Run button |
| E2 | Dry-run mode for every adapter | ⏳ | ✅ | validator rejects active adapter without `supports_dry_run: true`; `blocked-mcp-preview` proves the negative path |
| E3 | Per-agent adapter allowlisted | ⏳ | ✅ | `agents/adapter_registry.yaml` + `validate_adapter_registry()`; cross-checked by tests |
| E4 | Commands previewed before run | ⏳ | ✅ | preview JSON contains expanded `command`, `working_directory`, scope_paths |
| E5 | Timeout required on subprocess | ⏳ | **⏳ partial** | `timeout_seconds` declared per adapter; no subprocess yet so no runtime enforcement (correct for 3.0) |
| E6 | Output captured to JSONL + artifacts | ⏳ | **⏳ partial** | preview artifact + `logs/dispatch-<run_id>.jsonl` + `dispatch_preview_created`/`dispatch_blocked` events; runtime capture deferred (correct for 3.0) |
| E7 | Active task + handoff required | ✅ | ✅ | `load_task_for_plan` raises if task missing; `handoff_path` emitted as expectation |

E5/E6 status matches `docs/PHASE_3_0_BLOCKERS.md` row-for-row.

---

## Executive Summary

Phase 3.0 is a clean, surgically-bounded preview layer:

- **One new package** (`dispatch/`) with one module (`preview.py`) plus one CLI (`scripts/preview_dispatch.py`).
- **One new registry** (`agents/adapter_registry.yaml`) with schema enforcement (`validate_adapter_registry`) so registry edits go through PR review.
- **One new dashboard tab** that is verifiably read-only — grep confirms zero `subprocess.run` / `Popen` / `shell=True` callsites inside the dispatch tab markup.
- **Two new canonical event types** (`dispatch_preview_created`, `dispatch_blocked`); five execution-related types (`dispatch_approved`, `dispatch_started`, `dispatch_completed`, `dispatch_failed`, `handoff_required`) sit in `RESERVED_EVENT_TYPES` and would be **rejected by the validator** today, which correctly prevents accidental emitter creep.
- **One refactor** (`orchestrator/paths.py` extraction) untangles the `resolve_output_dir` helper from the LangGraph import chain so dispatch tests and CI both work without LangGraph installed.

The Phase 2.6 risk-gate fix is correctly consumed: `evaluate_risk()` is called inside `build_dispatch_preview` and `merge_approval_gate` takes the stricter of `(risk_result, adapter)` levels. The test `test_risk_gate_integration_deploy_task` proves the Phase 2.6 precedence flows through to dispatch.

---

## Architecture Review

**Consistent with the local-first, file-based control plane.** No new external dependencies; no MCP transport activation; no network; no secrets storage.

- `dispatch/preview.py` reads from existing sources (`agents/adapter_registry.yaml`, `runtime/orchestrator/latest_plan.json`, `tasks/*/*.yaml`, `runtime/orchestrator/latest_state.json`) and writes only to `runtime/dispatch/` and `logs/dispatch-<run_id>.jsonl`. No mutation of tasks, handoffs, ADRs, or registries.
- The adapter registry mirrors the existing skills/MCPs/teams/roles registry pattern (top-level `adapters:` list, per-entry required fields, validator cross-check).
- The orchestrator package is now genuinely consumable without LangGraph: `orchestrator/__init__.py` lazy-imports `run_orchestration`, `orchestrator/paths.py` is langgraph-free, and `orchestrator/loaders.py` + `orchestrator/risk.py` (consumed by dispatch) never touched langgraph. This is a quiet but important architectural cleanup — it means the dispatch layer is genuinely independent of the planning layer's transitive deps.
- `scripts/run_tests.py` is a reasonable lift of the earlier `capture_unittest.py` and writes `runtime/unittest_last_run.txt` with git SHA + exit code (per a9ccb0e).

---

## Safety Review

**The "no subprocess" claim is verified at three layers** — and that is the right design choice for Phase 3.0:

1. **Static guarantee:** `dispatch/preview.py` has no `import subprocess`, `os.system`, `os.popen`. Confirmed by grep.
2. **Test guarantee:** `test_preview_module_has_no_subprocess_import` reads the source file and asserts those strings are absent. `test_no_subprocess_execution_in_preview_module` patches `subprocess.run` and `subprocess.Popen` and asserts `mock_run.assert_not_called()` / `mock_popen.assert_not_called()`.
3. **Event-vocabulary guarantee:** all five execution-related event types (`dispatch_started`, etc.) are in `RESERVED_EVENT_TYPES` and excluded from `ALLOWED_EVENT_TYPES`. Validator + `protocol/emit_event.append_event` would both reject any emitter that tried to use them.

**Allowlist enforcement** in `validate_command_allowlist`:

- `_command_root` does `shlex.split(command, posix=False)`, takes `Path(parts[0]).name.lower()`, strips `.exe`, and checks against `allowed_commands`. Robust for the four hardcoded templates.
- `forbidden_args` check is a **substring** lookup against the lowercased command. This is sufficient for the current adapter templates (where every field is literal text), but it is not robust against template-injection in Phase 3.1+: if a future plan/task were to contain `"--execute"` inside a `task_id` or path, the check would mis-flag (or, worse, the bypass would be possible by encoding around the substring). **Phase 3.1 must switch this to a tokenised check after `shlex.split`** before any executor is wired up. Documented as M2 below.

**Risk-gate merge** in `merge_approval_gate`:

- Picks the stricter of `(risk_result.approval_level, adapter.approval_level)`. `APPROVAL_PRECEDENCE = {"none": 0, "reviewer": 1, "human": 2, "blocked": 3}`. Correctly handled.
- Sets `approval_status` to one of `none / pending / pending_reviewer / pending_human / blocked` — `pending` is dead code (set then always overwritten), cosmetic.
- The early-return branch when `adapter is None` sets `approval_status: "blocked"` but copies `approval_level` from `risk_result`. That can produce `(approval_level: "human", approval_status: "blocked")` which is semantically fine (we're blocking dispatch because there's no adapter) but inconsistent in terminology. Phase 3.1 must check **both** fields, not just one. Documented as M3 below.

**Working-directory containment:** `resolve_working_directory` only accepts `repo_root`, `worktree`, or `task_subdir`, and all three resolve under the repo root. `worktree` and `task_subdir` are placeholders for Phase 3.2 (worktree isolation); for now they fall through to `repo_root`. Acceptable.

**Plan / task path resolution:** `load_plan` resolves a CLI-provided `--plan` path against the repo root but does not enforce containment. Phase 3.0 only **reads** the file, so the failure mode is reading an unintended JSON file outside the repo, not writing. For Phase 3.1 executor this needs containment.

---

## Protocol Review

**Event vocabulary is correctly layered.**

- `PHASE_1_EVENT_TYPES` = lifecycle (unchanged).
- `PHASE_2_EVENT_TYPES` = ops (unchanged, no new emitters drifted).
- `PHASE_3_PREVIEW_EVENT_TYPES = {"dispatch_preview_created", "dispatch_blocked"}` — the only Phase 3 types currently allowed.
- `RESERVED_EVENT_TYPES` = `{validation_passed, review_packet_created, dispatch_approved, dispatch_started, dispatch_completed, dispatch_failed, handoff_required}`. **These are documented but not in `ALLOWED_EVENT_TYPES`**, so the validator rejects them today. This is exactly the right asymmetry: vocabulary doc-ahead is fine; emitter doc-ahead would be drift.

**Two log streams:**

- `logs/agent-events.jsonl` — canonical, validated, append-only. Receives `dispatch_preview_created` / `dispatch_blocked` (via `append_preview_event` → `protocol.emit_event.append_event`).
- `logs/dispatch-<run_id>.jsonl` — per-preview structured log line with `(ts, run_id, mode, dispatch_allowed, task_id, adapter_id, approval_level)`. **Not** validated by `scripts/validate.py` (it only covers `agent-events.jsonl`). That is intentional — these are run artifacts — but a brief mention in `docs/AGENT_PROTOCOL.md` would make the split explicit. Documented as L1.

**No task mutation, no handoff mutation, no ADR mutation by the dispatch layer.** Confirmed by code review. Preview's `expected_outputs` lists a "Proposed handoff" path but never writes it.

---

## Validation and Test Review

**Validator coverage extended correctly.**

- `validate_adapter_registry()` is wired into `main()` (line 934). Enforces all 19 required fields, `adapter_type ∈ {cli, mcp, http}`, `status ∈ {active, disabled, planned}`, `working_directory_policy ∈ {repo_root, worktree, task_subdir}`, boolean `secrets_required`, list types for `allowed_commands`/`forbidden_args`/`required_clis`/`env_vars_required`, **and** an active-adapter must have `supports_dry_run: true`, **and** at least one `active` adapter must exist.
- The "at least one active" rule is good for Phase 3.0 because it forces the registry to remain functional; Phase 3.1 may want to relax it for fully-blocked deployments, but that's a later concern.
- The `blocked-mcp-preview` entry tests the negative path: `status: disabled`, `supports_dry_run: false`, `risk_level: high`, `approval_level: human`. Validator accepts it because it isn't active. CLI / preview correctly reject it when selected explicitly.

**Test suite is appropriately thick:**

- `test_dispatch_preview.py` has 11 tests covering registry load, allowlist (forbidden arg + disallowed root), risk-gate integration, output shape, no-subprocess (both mock and source-grep), CLI exit codes, disabled adapter rejection, explicit-blocked rejection, and `requires_human_approval` propagation.
- `tests/support.py` provides `skip_without_langgraph` so the orchestrator tests skip cleanly on minimal installs while dispatch tests still run.
- `scripts/run_tests.py` ensures dependencies are installed first, captures stdout+stderr, writes `runtime/unittest_last_run.txt` with commit SHA, exit code, and tail. Better than the previous capture script.

**No test gaps blocking Phase 3.0.** Phase 3.1 will need new test groups for the executor (approval enforcement, timeout enforcement, log capture), but those belong with that implementation.

---

## Dispatch Preview Review

**Module API is clean.** `build_dispatch_preview` is a single entry point that takes optional `adapter_id`, `plan_path`, `task_path` and returns a fully-formed preview dict. `persist_preview` is a separate concern (artifact writes). `append_preview_event` is a third separate concern (canonical event log). The CLI composes all three.

**Preview JSON shape** includes everything Phase 3.1 will need to refuse-or-proceed:
- `dispatch_allowed`, `executed: false`, `mode: "dry_run_preview"` — explicit Phase 3.0 markers
- `command`, `working_directory`, `timeout_seconds`, `env_vars_required`, `secrets_required`, `scope_paths` — execution metadata
- `risk_gate` + `approval_gate` — both layers
- `plan_path`, `context_pack_path`, `handoff_path`, `logs_path` — links back to upstream artifacts
- `rollback_strategy` — string hint for `writes_files` adapters
- `statement: "Dry-run preview only. No agents were launched. No subprocess executed."` — final guard

**Behavior on edge cases I verified:**

- Live run against current `latest_plan.json` (gemini-owned task) → no active gemini adapter → `dispatch_allowed: false`, errors include `"no active adapter for agent 'gemini'"`. Correct.
- Explicit `--adapter blocked-mcp-preview` → status `disabled` + `supports_dry_run: false` → both errors raised → `dispatch_allowed: false`. Correct.
- Task with `requires_human_approval: true` → `risk_result.approval_level: human` (Phase 2.6 fix) → `approval_gate.approval_level: human`. Correct.
- Task with `"production deploy"` text → risk gate human (Phase 2.6 fix) → approval gate human → `approval_status: pending_human`. Correct.

---

## Issues

### Critical
None.

### High Priority
None blocking the Phase 3.0 merge.

### Medium Priority

- **M1. Gitignore missing for dispatch artifacts.** `runtime/orchestrator/runs/**` is gitignored but `runtime/dispatch/previews/**`, `runtime/dispatch/latest_preview.json`, and `logs/dispatch-*.jsonl` are not. Each preview run produces new files; without gitignore they will be staged accidentally. Add three entries to `.gitignore`.

- **M2. `forbidden_args` substring check.** `validate_command_allowlist` does `if str(forbidden).lower() in cmd_lower`. Robust for current adapters where templates contain only known literals. For Phase 3.1+, a `task_id` or path that legitimately contains a forbidden substring would mis-flag, and a sufficiently crafted plan field could conceivably mask one. **Phase 3.1 must replace this with a token-level check** via `shlex.split` and exact-token comparison, before any executor uses it. Add a regression test once that lands.

- **M3. `merge_approval_gate` field mismatch.** When `adapter is None`, the gate sets `approval_status: "blocked"` but copies `approval_level` from `risk_result` (which can be `human`, `reviewer`, or `none`). Phase 3.1 executor must check both fields; a single-field check on `approval_level != "blocked"` would not refuse this case. Either (a) force `approval_level: "blocked"` when no adapter is selected, or (b) document the dual-check contract in the design spec. Option (a) is cleaner.

- **M4. ADR for adapter registry schema.** The handoff Open Question is "ADR-0013 for adapter registry schema — create now or with Phase 3.1?" — recommend **create now**, alongside Phase 3.0 merge. The adapter registry is load-bearing: it defines the allowlist, approval defaults, and required-CLI contract that Phase 3.1 will enforce. Schema changes after Phase 3.1 ships would be harder to evolve. Reviewer approval, ~one page.

### Low Priority

- **L1. Log-stream split not documented.** `docs/AGENT_PROTOCOL.md` describes only `logs/agent-events.jsonl`. Add a short note that `logs/dispatch-<run_id>.jsonl` is a structured-but-unvalidated run-artifact stream separate from the canonical event log.

- **L2. Dispatch log filename has double `dispatch-` prefix.** `run_id = f"dispatch-{stamp}-{uuid}"`, and the log filename template adds another `dispatch-`, so files become `logs/dispatch-dispatch-20260608T...jsonl`. Cosmetic; either trim the prefix from `run_id` (preferred) or change the filename template to `logs/{run_id}.jsonl`.

- **L3. `approval_status: "pending"` is dead code.** Initial assignment that is always overwritten. Remove or move to a default at the end.

- **L4. `dispatch_allowed` semantics need a one-line doc.** The field means "the preview is internally well-formed and could be presented to an executor", **not** "execution may proceed". Phase 3.1 executor will additionally check `approval_gate.approval_status` and a recorded approval. Add the line to `docs/PHASE_3_DESIGN_SPEC.md` so future readers don't conflate the two.

- **L5. Carry-over.** `claude` reviewer sign-off boxes on ADR-0010 / 0011 / 0012 are still empty. Flip on this merge.

### Informational (Phase 3.1 hints)

- **I1. Preview freshness.** Open Question from the handoff. Recommend require preview not older than 60 min when Phase 3.1 executor consumes it, to prevent stale-plan execution.
- **I2. CLI availability gate.** Open Question — recommend Phase 3.1 cross-check `required_clis` against `runtime/registry/cli_inventory.yaml` and downgrade to `dispatch_allowed: false` (with warning) if any required CLI is missing. Catches "Codex CLI not installed" before subprocess.
- **I3. Executor module path.** When Phase 3.1 adds `scripts/execute_dispatch.py`, the actual `subprocess.run` should sit in `dispatch/executor.py` (parallel to `dispatch/preview.py`), so the no-subprocess guarantee on `preview.py` remains testable.
- **I4. Approval recording.** No design exists yet for *how* a human approval is recorded (file? git-signed note? handoff field?). Phase 3.1 design ADR must close this.

---

## Required Fixes for Phase 3.0 Merge

None. Recommendations M1 – L5 are best done as a single small follow-up commit on the same branch (10 minutes) before merge, or as the first task on `T-PHASE3-0-FOLLOWUP`. They are not blockers.

If a follow-up task is preferred, see `tasks/active/T-PHASE3-0-FOLLOWUP.yaml`.

---

## Recommended ADR Updates

- **New ADR-0013 — Adapter registry schema and Phase 3.0 dispatch preview contract.** Capture the 19 required fields, the `active ⇒ supports_dry_run` invariant, the allowlist/forbidden-args contract, and the `dispatch_allowed` semantics. Reviewer approval.
- **ADR-0012 — Add a Consequences note** that Phase 3.0 implements E2/E3/E4 at preview level; E5/E6/S3 remain partial; ADR-0014 (to be written with Phase 3.1) will close them.

---

## Phase 3 Readiness

**READY FOR PHASE 3.1 DESIGN ONLY.**

Phase 3.0 = preview only (this branch). Phase 3.1 = execute path. Phase 3.1 must remain blocked until:

1. ADR-0013 (adapter schema) accepted.
2. Phase 3.1 design ADR (execute_dispatch.py contract, approval-recording mechanism, subprocess sandboxing, timeout/log-capture protocol, worktree isolation) drafted and accepted.
3. M2 (token-level allowlist) and M3 (approval-state coherence) implemented and tested.
4. New event types (`dispatch_approved`, `dispatch_started`, `dispatch_completed`, `dispatch_failed`) moved from `RESERVED_EVENT_TYPES` to `PHASE_3_EXECUTE_EVENT_TYPES` with emitters wired.
5. CLI-availability cross-check (I2) added.

---

## Recommended Next Milestone

**Phase 3.0.1 — Adapter ADR + cleanup, then Phase 3.1 design spec.**

Bundle:

- ADR-0013 (adapter registry schema).
- M1 (gitignore), L2 (filename), L3 (dead code), L4 (semantics doc), L5 (sign-off boxes).
- Draft Phase 3.1 design ADR. **Do not implement execute path.**

Then Phase 3.1 implementation in a separate task with its own Claude review.

---

## Final Reviewer Notes

This is the cleanest phase delivery so far. The Phase 2.6 risk-gate fix flows correctly into the new approval merge; the adapter registry mirrors the existing registry patterns; the no-subprocess guarantee is enforced at three layers (code, test, vocabulary); and `docs/PHASE_3_0_BLOCKERS.md` is honest about what remains. The lazy-LangGraph refactor (b4b7631) is a quiet win — it means dispatch can run on minimal CI installs without pulling in 100 MB of transitive deps.

The four open questions in the handoff have my answers above (M4, L1, I1, I2). The first three are merge-time cleanups; I2 (CLI availability cross-check) is a Phase 3.1 design item, not a Phase 3.0 blocker.

**Approve.** Flip the reviewer sign-offs on ADR-0010/0011/0012, ship Phase 3.0, then open the Phase 3.1 design spec task.
