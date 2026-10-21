# Integration Dependency Graph (SHA-based)

Maintained by the Director. Every node shows its commit SHA, base, status, and GitHub verification. A branch may only be built on a node marked **accepted**. Superseded nodes are preserved and never deleted.

**Status values**
- `accepted`: independently reviewed, with gates evidenced
- `in-review`: under review
- `building`: builder dispatched
- `superseded`: replaced by another node, kept for the record
- `stale`: no longer in the active path

`GitHub ✓` means `git ls-remote origin` returned the same SHA.

## Main line

```
ee7d1ea  origin/main (Phase 3.3.2)                                [main — 6 months behind]
   ⋮  (Phases 3.4–3.7 lineage, unmerged)
bfcfe55  T-PHASE3-9-1 physical launcher                           accepted   GitHub ✓
7aa62a5  T-PHASE3-9-4E supervisor hardening        ← bfcfe55      accepted   GitHub ✓
2358b24  T-PHASE3-9-5 MCP isolation                ← 7aa62a5      accepted   GitHub ✓
3bdc02e  T-PHASE3-9-6 Claude event consumer        ← 7aa62a5      accepted*  GitHub ✓
c374da7  T-PHASE3-9-6C verdict selection           ← 3bdc02e      accepted   GitHub ✓
918b49b  T-PHASE3-9-6C closeout                    ← c374da7      accepted   GitHub ✓ (2026-10-21)
5538455  VNext assessment docs                     ← 918b49b      accepted   GitHub ✓
cc7430a  T-M1-02 deferred re-eval / logging        ← 5538455      in-review  local clone only
8f7ff19  T-M1-02B Windows auth probe fix           ← cc7430a      in-review  local clone only
(next)   T-M1-04 child supervision                 ← 8f7ff19      building
```

\* `3bdc02e` was accepted with `9-6B`/`9-6C` follow-ups, which have since been accepted.

## Superseded and stale nodes

| SHA | Branch | Status | Reason |
|---|---|---|---|
| `dee4e9c` | `agent/composer/T-PHASE3-9-6-ACTIVITY-DETECTION-FIX` | superseded | Duplicate Grok implementation from `3bdc02e`. Codex `918b49b` has live acceptance evidence. Motivates M1-08 (work locking). |
| `db0bbcd` | `agent/composer/T-CLAUDE-REVIEWER-ADAPTER` (PR #40) | superseded | Replaced by the 9-6 event-consumer lineage. |
| `e5b328f` | `agent/composer/T-PHASE3-9-2-CLI-ENCODING-SAFE` | stale | Off-scope content. M1-06 rebuilds the encoding fix. |

## Known merge debt

The `2358b24` line (MCP isolation) and the `3bdc02e` line (event consumer) both descend from `7aa62a5` and **have not been merged together**. M1-09 must reconcile them into one integration candidate before the PR to `main`.

## Update rules

1. Add the node when a builder is dispatched, with status `building` and its base SHA.
2. On acceptance, record the reviewed SHA and run `git ls-remote` to verify GitHub.
3. Never re-point an accepted node. Corrections become new child nodes.
