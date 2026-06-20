# Phase 3.4 — Approval Authenticity MVP

**Status:** implemented  
**Algorithm:** HMAC-SHA256 (version 2 records)

## Problem

Phase 3.2 approval JSON had no cryptographic binding. Records could be copied or edited without detection.

## Solution

Signed approval records bind to preview scope via HMAC over canonical JSON payload.

| Module | Role |
|--------|------|
| `dispatch/approval_signing.py` | Sign, verify, TTL enforcement |
| `dispatch/approval_replay.py` | Single-use claim before subprocess |
| `scripts/sign_approval.py` | Operator CLI: sign record |
| `scripts/verify_approval.py` | Operator CLI: verify record |
| `schemas/signed_approval_record.schema.json` | Record validation |

## Key model

Secrets read from environment (never stored in repo):

| Approver | Key env | Key ID env |
|----------|---------|------------|
| `reviewer` | `AGENTIC_OS_REVIEWER_APPROVAL_KEY` | `AGENTIC_OS_REVIEWER_APPROVAL_KEY_ID` |
| `human` | `AGENTIC_OS_HUMAN_APPROVAL_KEY` | `AGENTIC_OS_HUMAN_APPROVAL_KEY_ID` |

## What HMAC proves (and does not)

**Proves:** holder of the configured secret signed this exact approval payload at signing time.

**Does not prove:** legal identity, non-repudiation, or that a specific human physically approved. `approved_by` is an operator-supplied label, not a verified identity.

## Signed payload fields

Required: `approval_id`, `version`, `task_id`, `run_id`, `preview_id`, `preview_hash`, `adapter_id`, `approval_level`, `approver_type`, `approved_by`, `issued_at`, `expires_at`, `nonce`, `key_id`, `algorithm`, `allowed_command_hash`, `allowed_cwd`, `allowed_scope_paths`, `worktree_allocation_id`, `revoked`, `signature`.

Canonical form: sorted JSON keys, normalized paths, signature excluded from digest.

## Verification statuses

`valid`, `invalid`, `expired`, `revoked`, `stale`, `wrong_key`, `wrong_scope`, `replayed`, `malformed`

Gate blocks execution when `verify_signed_approval()` is not `valid` for version ≥ 2 records.

## Single-use anti-replay

Before subprocess, `try_claim_approval()` atomically creates `runtime/dispatch/approval_consumed/<approval_id>.json`.

- First claim succeeds → execution may proceed
- Second claim → `approval_replay_blocked` event, execution blocked
- Gate pre-check: `check_replay=True` blocks already-consumed approvals

## TTL caps

| Approver | Max TTL |
|----------|---------|
| `reviewer` | per `DEFAULT_REVIEWER_APPROVAL_TTL_MINUTES` |
| `human` | per `DEFAULT_HUMAN_APPROVAL_TTL_MINUTES` |

## Hard rules

- System approvals cannot satisfy `human` gates (unchanged from Phase 3.2)
- `secrets_required` requires `approver_type: human`
- Legacy unsigned records (version 1) still work when `require_signed_approval=False`; default gate path requires signing for reviewer/human levels
- No secrets in repository