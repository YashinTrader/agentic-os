# Phase 3.7B Human Approval Request

## For Gabriel

**This request does not authorize execution.**

- Activation: `activation-phase37b-preflight`
- Task: `T-PHASE3-7B-CODEX-CANARY`
- Run ID: `canary-20260629T204243Z-45a06a4c`
- Reviewed commit: `dd186e795e8ba414f2023129782420ade0328a1a`
- Codex version: `0.136.0`
- Worktree: `C:\Users\gabot\agentic-os-worktrees\t-phase3-7b-codex-canary\canary-20260`
- Expected file: `docs/codex-canary-canary-20260629T204243Z-45a06a4c.md`
- Maximum runs: **1**
- Timeout: **10 minutes**
- Approval expiry once signed: **30 minutes**

## Exposure

- Possible Codex/OpenAI API token usage for one bounded prompt
- No MCP, merge, push, or deployment
- Failed or timed-out run still consumes the one-shot approval
- Activation suspended after attempt; Claude post-run review required

## Future live command (do not run until authorized)

```text
python scripts/run_codex_canary.py --execute-canary --activation-id activation-phase37b-preflight --manifest runtime/dispatch/codex_activation/activation-phase37b-preflight/activation_manifest.json --allocation runtime/dispatch/codex_activation/activation-phase37b-preflight/worktree_allocation.json --approval runtime/approvals/<signed-human-approval>.json --reviewed-sha <reviewed-sha>
```

## Emergency disable

```text
python scripts/disable_codex_canary.py --activation activation-phase37b-preflight --reason "operator emergency stop"
```
