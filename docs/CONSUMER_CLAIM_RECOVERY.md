# Consumer fairness and abandoned review ownership

The event consumer scans builder completions in queue order. Resolved events are
archived even if an obsolete deferral exists. A claimed or ineligible deferred
event does not prevent later events from being reviewed. Each tick selects at
most one assignment for review. The existing pre-PID failed-launch watchdog
retry stays bounded to two attempts for that assignment. Once a child PID is
observed, the tick does not launch another child, even if activity is missing.

New claims in `runtime/dispatch/claude_event_consumer/claims` contain
`consumer_pid`, `consumer_start_time`, a unique `consumer_token`, and
`review_pid`/`review_start_time`. The dispatcher records child identity before
monitoring the review. Missing creation identity for a recorded PID or inaccessible
process information is unknown and prevents automatic release. PID reuse is checked against OS creation
time. Automatic recovery requires a provably dead consumer and either no recorded
review child or a provably dead recorded child, and no fingerprint resolution.
The consumer-owned KILL_ON_JOB_CLOSE job prevents an unrecorded child from
outliving its consumer. Acquisition and recovery share a short OS lock.
The token also fences child updates and normal claim cleanup.

Legacy claims remain in place. Consumer status exposes `stale_claims` with
fingerprint, assignment, age in seconds (null for unreadable timestamps), and
`stale_claim_alert_active`. Tokened claims owned by another consumer also alert
when their consumer liveness is dead or unknown. Idle ticks clear inherited review lifecycle fields;
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
nor a stale alert authorizes release. Legacy or unknown-owner leases still consume
capacity after claim recovery, so inspect both kinds before retrying.

Each consumer tick and each lease acquisition recover abandoned review leases
under the shared mutation guard, before checking capacity. The same recovery
helper checks consumer creation identity and every recorded child (including
review run state). A tokened lease is removed only when its consumer is provably
dead and all recorded children are provably dead, or no child was recorded.
The request remains intact; a retry updates its run ID to a fresh attempt and
preserves prior artifacts and recovery lineage (see [review attempt evidence](REVIEW_ATTEMPT_EVIDENCE.md)).
Fingerprint claims still serialize event processing, and resolved fingerprints
are archived without another launch.

Consumer status includes `stale_review_leases` (key, assignment, age, reason) and
`stale_review_lease_alert_active`. Legacy/unreadable and unknown owners alert;
live tokened owners do not. Capacity blocked by a stale lease reports
`blocked_stale_lease`. Review concurrency refusals defer on `capacity:review`
for ten seconds with attempt count zero. They bypass launch-failure retries and
failure fingerprints. The next tick retries immediately if no review leases
remain. Every deferral record and emitted `deferred` event includes its readable
`reason`; authentication and failure backoff retain their existing behavior.

Releases refuse fingerprint/assignment resolutions and any recorded live or
unknown owner/child identity. Lease checks include the referenced
`runtime/dispatch/reviews/<run>/review_run.json`; claim checks also inspect the
matching lease. A legacy record without process identity may be explicitly
released after operator investigation. A recorded child PID without creation
identity is unknown and prevents automatic recovery. A child PID that was never
recorded is covered by the consumer-owned KILL_ON_JOB_CLOSE job.

Every release/recovery writes an atomic, unique audit JSON under
`runtime/dispatch/claude_event_consumer/audit` **before** removing the record. It
contains the event (`claim_recovered`, `lease_recovered`, `claim_released`, or `lease_released`),
actor, reason, timestamp, and full prior owner. Recovery also emits the
`claim_recovered` or `lease_recovered` state event on consumer ticks. New leases record the dispatcher's owner identity,
protecting the interval before its review child is known. The consumer, lease
writer, and operator CLI serialize mutations using the same OS guard; a crash
releases that guard without expiring durable ownership.

For explicit operator release, a PID without creation identity is checked without
signaling it. OS-confirmed absence or exit proves death. If creation time is
readable and later than the PID-holding record's own started_at, claimed_at or
acquired_at, it proves PID reuse; earlier/equal or unreadable creation stays
unknown. Windows uses process handles/FILETIME; Linux uses /proc start ticks
and boot time. Missing timestamps never establish reuse. Automatic recovery
still requires consumer_token and recorded creation identities.

Operator release also finalizes referenced running/queued review states as
abandoned immediately, preserving the original state snapshot and all logs,
with the operator reason and durable audit reference in recovery_audits.
