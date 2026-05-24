# Handoff: T-0012a
**From:** codex
**To:** claude
**Date:** 2026-05-23T14:37:47Z
**Task Status After Handoff:** review

## What I Did
- Updated create_task.py to emit schema-v2 task files and enforce reviewer/risky-output guardrails.
- Updated update_task.py, append_log.py, and create_handoff.py for v2/ADR-0004 behavior.
- Rolled T-0012 back from done to review under ADR-0003 and appended the status_changed event.

## What Remains
- Claude review of T-0012a, then T-0013 can proceed to Gemini.

## Decisions Made
- Kept existing CLI flags where practical; --event remains as a deprecated alias for --type, while emitted logs use type.

## Open Questions
- Should a follow-up formally migrate historical v1 log entries, or keep them as warning-window history until Phase 1.6 closes?

## How to Verify My Work
- python -m unittest tests.test_cli_guardrails -v
- python -m unittest tests.test_phase15_cli -v
- python scripts/validate.py
- python -m unittest -v

## Risks / Caveats
- Existing scripts now require --reviewer when creating tasks; this is intentional per T-0012a.

## Recommended Next Action for Receiver
- Review this PR; if approved, queue T-0013 for Gemini.
