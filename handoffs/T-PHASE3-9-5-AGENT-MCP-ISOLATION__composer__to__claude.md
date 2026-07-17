# Handoff: T-PHASE3-9-5-AGENT-MCP-ISOLATION

**From:** composer (Grok Build / Grok 4.5) — resumed from preserved worktree after Grok 402 quota stop  
**To:** claude  
**Date:** 2026-07-17T16:35:00Z  
**Task Status After Handoff:** review  
**Handoff Protocol:** v2  
**Assignment:** `assign-20260717T110640Z-T-PHASE3-9-5-AGENT-MCP-I-af4b49d4`

## What I Did

Resumed partial work after prior physical launch  
`phys-20260717T110653Z-T-PHASE3-9-5-AGENT-MCP-I-521f07c2` failed with **Grok 402 usage balance exhausted** (exit 1) after writing most of the implementation. Continued from the preserved branch tip rather than restarting.

### Implementation

- **`dispatch/mcp_isolation.py`** — schema helpers, Codex isolation flags, Grok gap note, required-MCP failure classification, unlisted-MCP cannot-abort simulation.
- **Codex launch path** — every exec injects after `exec`:
  - `--ignore-user-config`
  - `-c mcp_servers={}`
  - optional rehydrate of simple required servers via additional `-c mcp_servers.<name>={…}`
- **Assignment/task schema** — optional `required_mcp_servers` (default `[]`) with validation.
- **Grok path** — records isolation intent + `GROK_MCP_ISOLATION_GAP` (no invented flags).
- **Failure classify** — required MCP OAuth/transport failures → `blocked_external`.
- **Docs** — `docs/MCP_ISOLATION_POLICY.md` + GROK_BUILD_LOOP / Codex command contract notes.
- **Tests** — `tests/test_mcp_isolation.py` (17 tests OK).

## What Remains

- Claude independent review.
- Optional: Grok CLI MCP isolation when xAI exposes a real flag.
- Live Codex zero-MCP smoke on a host with stale unused MCP tokens (unit simulation covers policy).

## Decisions Made

- Default empty `required_mcp_servers` means **zero** optional MCP connections for Codex.
- Per-invocation overrides only — never mutate `~/.codex/config.toml`.
- Grok isolation is a documented gap, not a fake flag.
- Resume from preserved worktree/branch after quota stop rather than discarding partial implementation.

## Open Questions

- Whether Grok Build will add a per-invocation MCP isolation flag equivalent to Codex `-c mcp_servers={}`.

## How to Verify My Work

```bash
cd C:/Users/gabot/agentic-os
git checkout agent/composer/T-PHASE3-9-5-AGENT-MCP-ISOLATION
python scripts/validate.py
python -m unittest tests.test_mcp_isolation -v
# optional focused regression:
python -m unittest tests.test_mcp_isolation tests.test_assignment_channel -v
```

## Verification Results

| Command | Result |
|---------|--------|
| `python scripts/validate.py` | exit 0 (after handoff sections fixed) |
| `python -m unittest tests.test_mcp_isolation` | **17 OK** |
| focused suite (mcp + local_builder + assignment_channel) | **81 OK** |
| plain full discover in long-path worktree | noisy errors (Windows path length / corrupted nested worktree); re-run preferred on canonical short path |
| prior Grok physical run | exit 1, 402 quota exhausted — implementation preserved |

## Risks / Caveats

- Grok cannot enforce zero-MCP by argv yet.
- Required-server rehydrate supports simple command/args/url shapes only.
- Full-suite discover in the long nested worktree path was unreliable (FileNotFound/path-length); focused suites green on canonical checkout.

## Recommended Next Action for Receiver

1. Review branch `agent/composer/T-PHASE3-9-5-AGENT-MCP-ISOLATION`.
2. Confirm Codex isolation flags in `codex_adapter` / `mcp_isolation`.
3. Accept if criteria met.

## Repository Verification

repo_root: C:/Users/gabot/agentic-os
branch: agent/composer/T-PHASE3-9-5-AGENT-MCP-ISOLATION
base_sha: 7aa62a572849ac3f66e55165312f3b3764f4f2c4
implementation_sha: ecce2286a16a2096fbab0abb3b05324f019b3fc4
tests_commit_sha: ecce2286a16a2096fbab0abb3b05324f019b3fc4
final_head_sha: fe57658bc7b32e9841c874d30c2a3ab2019477d6
remote_head_sha: fe57658bc7b32e9841c874d30c2a3ab2019477d6
git_status_clean: true
validator_commit_sha: ecce2286a16a2096fbab0abb3b05324f019b3fc4
test_count: 17
test_exit_code: 0
validator_exit_code: 0
post_test_diff_policy: POST_TEST_ALLOWLIST_EXACT
post_test_files: handoffs/T-PHASE3-9-5-AGENT-MCP-ISOLATION__composer__to__claude.md, runtime/unittest_last_run.txt
working_copy_path: C:/Users/gabot/agentic-os
