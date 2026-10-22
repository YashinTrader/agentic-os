# Consumer fairness and abandoned claims

The event consumer scans builder completions in queue order. Resolved events are
archived even if an obsolete deferral exists. A claimed or ineligible deferred
event does not prevent later events from being reviewed. Each tick selects at
most one assignment for review. The existing pre-PID failed-launch watchdog
retry stays bounded to two attempts for that assignment. Once a child PID is
observed, the tick does not launch another child, even if activity is missing.

New claims in `runtime/dispatch/claude_event_consumer/claims` contain
`consumer_pid`, `consumer_start_time`, a unique `consumer_token`, and
`review_pid`/`review_start_time`. The dispatcher records child identity before
monitoring the review. Missing identity or inaccessible process information is
unknown and prevents automatic release. PID reuse is checked against OS creation
time. Automatic recovery requires both recorded identities to be provably dead,
and no fingerprint resolution; acquisition and recovery share a short OS lock.
The token also fences child updates and normal claim cleanup.

Legacy claims remain in place. Consumer status exposes `stale_claims` with
fingerprint, assignment, age in seconds (null for unreadable timestamps), and
`stale_claim_alert_active`. Idle ticks clear inherited review lifecycle fields;
an idle consumer with legacy claims reports `blocked_stale_claim`. A completed
review can still report `resolved` while the stale-claim alert remains active.

Inspect the selected **state root**, then explicitly release abandoned records:

```powershell
python scripts/consumer_claims.py --root <state-root> list
python scripts/consumer_claims.py --root <state-root> release <fingerprint> --actor <name> --reason "confirmed abandoned"
python scripts/consumer_claims.py --root <state-root> release review-<assignment-id> --kind lease --actor <name> --reason "confirmed abandoned review"
```

`list` includes both claims and review leases. A lease key is its basename without
`.json`. Claim and lease releases are separate explicit operations. Neither age
nor a stale alert authorizes release. A lease can still consume review capacity
after its claim is recovered, so inspect both kinds before retrying.

Releases refuse fingerprint/assignment resolutions and any recorded live or
unknown owner/child identity. Lease checks include the referenced
`runtime/dispatch/reviews/<run>/review_run.json`; claim checks also inspect the
matching lease. A legacy record without process identity may be explicitly
released after operator investigation. Missing child identity on a new claim is
unknown, not proof of death, and intentionally prevents automatic recovery.

Every release/recovery writes an atomic, unique audit JSON under
`runtime/dispatch/claude_event_consumer/audit` **before** removing the record. It
contains the event (`claim_recovered`, `claim_released`, or `lease_released`),
actor, reason, timestamp, and full prior owner. Recovery also emits the
`claim_recovered` state event. New leases record the dispatcher's owner identity,
protecting the interval before its review child is known. The consumer, lease
writer, and operator CLI serialize mutations using the same OS guard; a crash
releases that guard without expiring durable ownership.
