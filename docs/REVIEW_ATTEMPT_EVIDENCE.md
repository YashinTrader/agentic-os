# Review attempt evidence

The request's `review_run_id` points to the latest attempt. Each retry gets a fresh
run ID and its own directory under `runtime/dispatch/reviews`; first attempts use
the ID originally allocated by `create_review_request`. Context, prompt, stdout,
and stderr of older attempts are never reused as launch output targets.

Before launch, while holding the assignment's review lease and the existing
mutation guard, the dispatcher writes `attempt.json`, updates the lease's run ID,
and publishes the request pointer. This reservation also covers a crash before
`review_run.json` exists. Retries retain the full ordered `prior_review_run_ids`
chain. Each attempt's sidecar records matching durable recovery audit paths and
contents (`claim_recovered` / `lease_recovered`, or explicit operator release).
A retry after an ordinary failure can have no recovery audit.

After exclusive lease acquisition, a previously running or queued state becomes
`abandoned`, retaining PID, process creation identity, and start time, with the
recovery reason and completion time. Its exact previous bytes are first saved to
`review_run.before_abandonment.json` with atomic publication under the mutation guard. Logs and prompts
stay byte-for-byte intact. Terminal states stay terminal.

Recovery fences, capacity, fairness, and deferral rules are unchanged. Updating
the lease run pointer before launch keeps consumer_claims liveness checks on the
latest child even before its PID is copied into the lease. Existing review-state
readers still see the usual review_run.json shape; the lineage lives in the
sidecar and request. Applied-request replay still returns without launching or
applying a second resolution.

