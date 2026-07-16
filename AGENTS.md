# Agentic OS — agent session rules (Grok Build / Composer)

## Builder identity

- Display: **Grok Build (Grok 4.5)**
- Stable ids: adapter `composer-restricted`, agent `composer` (do not rename)

## Session start (mandatory)

Before any other work in this repo, pick up Claude-posted assignments:

```bash
cd C:/Users/gabot/agentic-os
python scripts/session_pickup.py
```

If an assignment is claimed, follow its contract (`new_branch`, `base_sha`,
`acceptance_criteria`, `verification_commands`, `handoff_path`). Do not wait for
Gabriel or chat relay of the task text — the inbox JSON is authoritative.

Operating contract: `docs/GROK_BUILD_LOOP.md`.

## After build

```bash
python scripts/assignments.py complete <assignment_id> \
  --handoff <handoff_path> \
  --branch <new_branch> \
  --branch-tip-sha "$(git rev-parse HEAD)" \
  --summary "…" \
  --outbox-status awaiting_review
git push -u origin HEAD
```

Claude reviews via `python scripts/assignments.py ingest` + handoff + branch.

## Forbidden without Gabriel gate

- Adding `composer-restricted` to `config/execution-policy.yaml` `enabled_adapters`
- Secrets / Grok API network calls for automatic execution
- Merge to protected branches; dashboard write/execute controls
