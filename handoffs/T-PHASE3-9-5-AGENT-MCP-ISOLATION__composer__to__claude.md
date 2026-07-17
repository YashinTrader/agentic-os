# Handoff: T-PHASE3-9-5-AGENT-MCP-ISOLATION

**From:** composer (Grok Build / Grok 4.5) — resumed from preserved worktree after Grok 402 quota stop  
**To:** claude  
**Date:** 2026-07-17T16:05:00Z  
**Task Status After Handoff:** review  
**Handoff Protocol:** v2  
**Assignment:** `assign-20260717T110640Z-T-PHASE3-9-5-AGENT-MCP-I-af4b49d4`

## What I Did

Resumed partial work in worktree  
`C:\Users\gabot\agentic-os-worktrees\t-phase3-9-5-agent-mcp-isolation\phys-2026071`  
after prior physical launch `phys-20260717T110653Z-T-PHASE3-9-5-AGENT-MCP-I-521f07c2` failed with **Grok 402 usage balance exhausted** (exit 1) after writing most of the implementation.

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
- **Tests** — `tests/test_mcp_isolation.py` (17 tests).

## What Remains

- Claude independent review.
- Optional: Grok CLI MCP isolation when xAI exposes a real flag.
- Live Codex zero-MCP smoke on a host with stale unused MCP tokens (unit simulation covers policy).

## Decisions Made

- Default empty `required_mcp_servers` means **zero** optional MCP connections for Codex.
- Per-invocation overrides only — never mutate `~/.codex/config.toml`.
- Grok isolation is a documented gap, not a fake flag.
- Resume from worktree after quota stop rather than discarding partial implementation.

## How to Verify

```bash
cd C:/Users/gabot/agentic-os-worktrees/t-phase3-9-5-agent-mcp-isolation/phys-2026071
# or checkout agent/composer/T-PHASE3-9-5-AGENT-MCP-ISOLATION in canonical clone after push
python scripts/validate.py
python -m unittest tests.test_mcp_isolation -v
python -m unittest discover -s tests -p "test_*.py"
```

## Verification Results

| Command | Result |
|---------|--------|
| `python scripts/validate.py` | exit 0 |
| `python -m unittest tests.test_mcp_isolation` | 17 OK |
| focused suite (mcp + local_builder + assignment_channel) | 81 OK |
| plain full discover | (recorded after suite completes) |
| prior Grok physical run | exit 1, 402 quota exhausted — implementation preserved in worktree |

## Risks / Caveats

- Grok cannot enforce zero-MCP by argv yet.
- Required-server rehydrate supports simple command/args/url shapes only.
- Assignment was `reviewable_failure` after quota stop; resume completed from worktree without re-running Grok.

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
final_head_sha: ecce2286a16a2096fbab0abb3b05324f019b3fc4
remote_head_sha: ecce2286a16a2096fbab0abb3b05324f019b3fc4
git_status_clean: true
validator_commit_sha: ecce2286a16a2096fbab0abb3b05324f019b3fc4
test_count: 81
test_exit_code: 0
validator_exit_code: 0
post_test_diff_policy: POST_TEST_ALLOWLIST_EXACT
post_test_files: handoffs/T-PHASE3-9-5-AGENT-MCP-ISOLATION__composer__to__claude.md, runtime/unittest_last_run.txt
working_copy_path: C:/Users/gabot/agentic-os-worktrees/t-phase3-9-5-agent-mcp-isolation/phys-2026071
