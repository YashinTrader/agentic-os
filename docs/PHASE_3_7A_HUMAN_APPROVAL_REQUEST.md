# Phase 3.7A Human Approval Request

## For Gabriel

This document describes the human decision package for the first Codex canary. **This request does not itself authorize execution.**

## Request artifact

Path: `runtime/dispatch/codex_activation/<activation_id>/human_approval_request.json`

Status: `awaiting_human_decision`

## What you are approving (after Claude 3.7A review)

- Exactly **one** Codex canary run inside an isolated worktree
- Exactly **one** new file: `docs/codex-canary-<run-id>.md`
- Bounded timeout and network exposure via installed Codex CLI
- Automatic suspension after the single run

## What is not included

- No approval signature in this milestone
- No Phase 3.7B authorization artifact
- No live run until Phase 3.7B records `phase3_7b_authorization.json`

## Decision checklist

1. Confirm Claude approved Phase 3.7A branch
2. Confirm `reviewed_commit_sha` matches reviewed branch HEAD
3. Confirm `canary_contract_hash` and `command_contract_hash` in request
4. Confirm worktree will be operator-allocated before live run
5. Issue human-signed approval only in Phase 3.7B milestone

## Required statement

**This request does not itself authorize execution.**