# Claude Review Security Policy

Claude is a **reviewer**, not a builder.

## Allowed tools

- Read, Glob, Grep
- Narrow Bash patterns only:
  - `git status|diff|log|show|rev-parse|merge-base|ls-remote`
  - `python -m unittest …`
  - `python scripts/validate.py`
  - `python scripts/handoff_closeout_gate.py …`
  - `python scripts/verify_repository_verification.py …`

## Denied

- Edit / Write / MultiEdit / NotebookEdit
- Unrestricted Bash
- `git push`, `git merge`, `git rebase`
- `gh`, `curl`, `wget`, `rm`
- WebSearch / WebFetch
- `--dangerously-skip-permissions` / `bypassPermissions`
- Credential reading or secret logging
- Direct assignment-channel mutation via shell

## Permission mode

`dontAsk` — unapproved actions fail closed (no interactive prompts).

## Auth

Default `claude_code_local_auth`. API mode optional via `ANTHROPIC_API_KEY` (never persisted).
