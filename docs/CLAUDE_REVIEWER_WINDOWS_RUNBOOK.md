# Claude Reviewer Windows Runbook

## Foreground supervisor (builders + reviewer)

```powershell
cd C:\Users\gabot\agentic-os
python scripts/run_orchestrator.py `
  --agents composer,codex,claude-reviewer `
  --poll-seconds 5 `
  --max-concurrency 1 `
  --review-concurrency 1 `
  --auth-mode claude_code_local_auth
```

One-shot review only:

```powershell
python scripts/run_claude_reviewer.py --once --assignment-id <id>
```

## Clean shutdown

Ctrl+C in the supervisor terminal. SIGINT sets stop flag; no Windows service is installed.

## Check PID / logs

```powershell
Get-Process claude -ErrorAction SilentlyContinue
Get-ChildItem runtime\dispatch\reviews -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 5
Get-Content runtime\dispatch\reviews\<run_id>\stdout.log -Tail 40
Get-Content runtime\dispatch\reviews\<run_id>\review_run.json
```

## Restart

Re-run the same `run_orchestrator.py` command. Review requests are idempotent per assignment; active review leases prevent duplicate concurrent reviews.

## Auth recovery

If reviews show `blocked_authentication`:

```powershell
claude auth login
claude -p "Return exactly: CLAUDE_REVIEWER_READY" --output-format json --allowedTools "Read,Glob,Grep" --permission-mode dontAsk
```

Do not paste tokens into repo files.

## Optional Task Scheduler

Create a task that runs the supervisor in the user session after login. Do not install as LocalSystem service (auth/session isolation risks).
