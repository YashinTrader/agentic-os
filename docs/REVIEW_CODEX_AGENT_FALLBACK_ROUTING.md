# Review: Codex fallback-routing contribution

Reviewed on 2026-07-15 while integrating `T-PHASE3-9-AGENT-WAKE-POKE`.

## Accepted

- Builder profiles and Grok-to-Composer alias normalization.
- Reassignment lineage (`reassigned_from`, reason, replacement id).
- Superseding the old assignment while preserving its audit record.
- Orchestrator-only assignment creation and builder-specific claim checks.
- Read-only dashboard display of fallback lineage.

## Altered during integration

- Preserved the prerequisite reviewer-resolution lifecycle: `changes_requested`
  remains re-claimable and `superseded` is terminal.
- Replaced the generic notification-only `--poke` idea for new work with
  adapter-declared `--wake` delivery and a separate orchestrator poke-back queue.
- Kept Composer automatic execution disabled. The detected Grok headless CLI is
  documented, but wake delivery uses the bounded watcher until Gabriel approves
  that execution surface.

## Rejected

- No agent-to-agent poke topology.
- No direct Grok/xAI invocation, credentials, or network dependency.
- No second Codex execution path; Codex wake reuses worker eligibility.
