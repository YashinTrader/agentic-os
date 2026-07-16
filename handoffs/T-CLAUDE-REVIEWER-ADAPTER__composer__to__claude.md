# Handoff: T-CLAUDE-REVIEWER-ADAPTER

**From:** composer (Grok Build / Grok 4.5)  
**To:** claude  
**Date:** 2026-07-16T09:00:00Z  
**Task Status After Handoff:** review  
**Handoff Protocol:** v2  

## What I Did

- Implemented headless **Claude Code reviewer adapter** so routine reviews do not require Gabriel to open an interactive Claude chat.
- Components: `orchestrator/review_schema.py`, `claude_reviewer_adapter.py`, `review_dispatcher.py`, `scripts/run_claude_reviewer.py`.
- Extended `scripts/run_orchestrator.py` for unified builders + `claude-reviewer`.
- Restricted tools, `permission-mode dontAsk`, strict JSON verdict schema, review leases (concurrency 1), idempotent review requests.
- Deterministic verdict application via `assignment_channel.resolve_assignment` only (Claude does not mutate assignment files via shell).
- Dashboard read-only Claude review table (PID, session, verdict, blocked reason).
- Docs + Windows runbook + security policy.
- Unit tests with fake Claude executable (15 OK).
- **Live probe:** real Claude process launched (PID **35176**), classified **`blocked_authentication`** (OAuth 401). Assignment left `awaiting_review`. No mock success.

## Claude preflight

| Item | Value |
|------|--------|
| Version | 2.1.150 (Claude Code) |
| Executable | `C:\Users\gabot\AppData\Roaming\npm\claude.CMD` |
| Auth mode | `claude_code_local_auth` |
| Probe | `claude -p "Return exactly: CLAUDE_REVIEWER_READY" --output-format json --allowedTools Read,Glob,Grep --permission-mode dontAsk` |
| Result | exit 1, 401 OAuth token revoked / invalid credentials |
| Session ID (probe) | present in earlier JSON envelope; live review run did not persist session on auth fail path |
| API mode | `ANTHROPIC_API_KEY` unset — not used |

## Command shapes

Supervisor:

```text
python scripts/run_orchestrator.py --agents composer,codex,claude-reviewer --poll-seconds 5 --max-concurrency 1 --review-concurrency 1
```

Claude reviewer argv (shell=False):

```text
claude -p <prompt> --output-format json --json-schema <schema> --permission-mode dontAsk --allowedTools <restricted> --disallowedTools Edit,Write,...
```

## How to Verify

```bash
cd C:/Users/gabot/agentic-os
git checkout agent/composer/T-CLAUDE-REVIEWER-ADAPTER
python scripts/validate.py
python -m unittest tests.test_claude_reviewer_adapter -v
# after claude auth login:
python scripts/run_claude_reviewer.py --assignment-id <awaiting_review_id>
```

## Verification Results

| Check | Result |
|-------|--------|
| validate.py | 0 |
| unittest test_claude_reviewer_adapter | 15 OK |
| compileall | 0 |
| git diff --check | clean |
| run_tests.py | not claimed green (existing Cognee/Cargo bootstrap blocker if still present) |
| live review | blocked_authentication, PID 35176, assignment remains awaiting_review |

## Live review evidence

- run_id: `review-2026-07-16T085252Z-9978ee2e`
- assignment: `assign-claude-review-live-fixture`
- PID: `35176`
- process_state: `blocked_authentication`
- verdict: **not applied** (auth failure)
- correction/next assignment: none
- composer wake: n/a
- evidence file: `runtime/claude_live_review_evidence.json`

## Remaining limitations

1. **Claude OAuth must be re-authenticated** (`claude auth login`) before live autonomous accept/request-changes works.
2. Optional API mode requires Gabriel-approved `ANTHROPIC_API_KEY`.
3. Full unittest discover not re-run end-to-end on this tip in this session (focused suite + validator used).
4. No automatic Windows service install (runbook only).

## Recommended Next Action for Receiver

1. Run `claude auth login` on the agent host.
2. Re-run `python scripts/run_claude_reviewer.py --assignment-id <awaiting_review_id>`.
3. Confirm structured verdict applies and dashboard shows the review.

## Repository Verification

repo_root: C:/Users/gabot/agentic-os
branch: agent/composer/T-CLAUDE-REVIEWER-ADAPTER
base_sha: 67a64aa696a327fa4eafbf27dc2be0470e5e4925
implementation_sha: 65e225a06697f566e2fb07370656313a6f94a55f
tests_commit_sha: 65e225a06697f566e2fb07370656313a6f94a55f
final_head_sha: 65e225a06697f566e2fb07370656313a6f94a55f
remote_head_sha: 65e225a06697f566e2fb07370656313a6f94a55f
git_status_clean: true
validator_commit_sha: 65e225a06697f566e2fb07370656313a6f94a55f
test_count: 15
test_exit_code: 0
validator_exit_code: 0
post_test_diff_policy: POST_TEST_ALLOWLIST_EXACT
post_test_files: handoffs/T-CLAUDE-REVIEWER-ADAPTER__composer__to__claude.md, runtime/unittest_last_run.txt
working_copy_path: C:/Users/gabot/agentic-os
