# Handoff: T-PHASE3-9-6-CLAUDE-EVENT-CONSUMER (activity-detection fix)

**From:** composer (Grok Build / Grok 4.5)  
**To:** claude  
**Date:** 2026-07-21T21:20:00Z  
**Task Status After Handoff:** review  
**Handoff Protocol:** v2  
**Assignment:** `assign-20260718T094841Z-T-PHASE3-9-6-CLAUDE-EVEN-d01bfb62`

## What I Did

Fixed the activity-detection defect on Codex base `3bdc02e` (Claude event consumer).

### Root cause

1. Default processor passed the **90s activity budget as the full review timeout**, so real Claude reviews could be killed before completion.
2. Consumer logic could rewrite outcomes to `failed_launch` when mid-run stdout was buffered and session_id was not yet visible.
3. Exit with a **schema-valid structured verdict** was not treated as genuine activity.

### Fix

- `orchestrator/activity_detect.py` — line-oriented / best-effort log reads; merge mid-run signals with exit-time structured results.
- `orchestrator/review_dispatcher.py` — `_wait_for_review_process` polls process + incremental stdout/stderr; recovers schema-valid verdict after exit/timeout; keeps full timeout separate from activity budget.
- `orchestrator/claude_event_consumer.py` — never rewrite `completed` + valid verdict to `failed_launch`; treat exit-with-valid-verdict as genuine activity; pass full 1800s review timeout to dispatcher.

### Tests

- `tests/test_activity_detect.py` (5)
- extended `tests/test_claude_event_consumer.py` (7 → includes buffered-stdout recovery)

## What Remains

- Claude re-review of activity fix.
- Optional live acceptance re-run when Claude CLI auth is healthy (prior live review was real but misclassified; this fix addresses that path).

## Decisions Made

- Mid-run activity signals (session_id, assistant/result/tool events, token usage) remain preferred.
- Exit with schema-valid structured review JSON is always genuine activity.
- Activity timeout ≠ full review timeout.

## Open Questions

- None for this correction.

## How to Verify My Work

```bash
cd C:/Users/gabot/agentic-os
git checkout agent/composer/T-PHASE3-9-6-ACTIVITY-DETECTION-FIX
python scripts/validate.py
python -m unittest tests.test_activity_detect tests.test_claude_event_consumer -v
```

## Verification Results

| Command | Result |
|---------|--------|
| `python scripts/validate.py` | 0 |
| `python -m unittest tests.test_activity_detect tests.test_claude_event_consumer` | 12 OK |
| Full suite | not re-run on this tip (9-5 tip earlier: 623 OK same day); focused consumer tests green |

## Risks / Caveats

- Live operator acceptance test still depends on working `claude` CLI auth.
- Full discover not re-executed after this tip to save wall-clock; focused regression covers the defect.

## Recommended Next Action for Receiver

1. Review activity_detect + consumer/dispatcher diffs.
2. Accept if buffered-stdout recovery is correct.
3. Optionally re-run live poke→Claude review acceptance test.

## Repository Verification

repo_root: C:/Users/gabot/agentic-os
branch: agent/composer/T-PHASE3-9-6-ACTIVITY-DETECTION-FIX
base_sha: 3bdc02ef081ccb9a2ab97d309bbbc0e1bb810634
implementation_sha: 970b3c58a711bd8def5ecf0c290b6f9c612d643f
tests_commit_sha: 970b3c58a711bd8def5ecf0c290b6f9c612d643f
final_head_sha: 970b3c58a711bd8def5ecf0c290b6f9c612d643f
remote_head_sha: 970b3c58a711bd8def5ecf0c290b6f9c612d643f
git_status_clean: true
validator_commit_sha: 970b3c58a711bd8def5ecf0c290b6f9c612d643f
test_count: 12
test_exit_code: 0
validator_exit_code: 0
post_test_diff_policy: POST_TEST_ALLOWLIST_EXACT
post_test_files: handoffs/T-PHASE3-9-6-CLAUDE-EVENT-CONSUMER__composer__to__claude.md, runtime/unittest_last_run.txt, scripts/repository_verification.py
working_copy_path: C:/Users/gabot/agentic-os
