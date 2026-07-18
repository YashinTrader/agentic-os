# Claude Event Consumer

`python scripts/run_claude_event_consumer.py` is the persistent local watcher for terminal builder events. It polls the on-disk orchestrator poke queue and invokes no model while idle.

Only non-Claude `assignment_completed` events are eligible. The consumer fingerprints the stable event identity, creates an exclusive claim, and records `pending -> claimed -> review_starting -> review_running -> resolved`. `review_running` requires a real PID plus either a Claude session id or a schema-valid structured verdict. A missing PID or activity is classified `failed_launch`; the launch is retried once. Failed reviews retain the original poke.

The resolved fingerprint is transactionally persisted before the poke is moved to `runtime/dispatch/pokes/consumed`. This ordering makes crash recovery safe and deduplicates repeated terminal events. Changes-requested verdict handling remains in `review_dispatcher.apply_verdict`, which resolves the original assignment and queues the selected builder wake immediately.

Watcher health is stored at `runtime/dispatch/claude_event_consumer/status.json`: heartbeat, oldest pending age, active assignment, PID, Claude session, attempt count, last verdict, and blocker. The dashboard loader surfaces a system alert after five minutes.

Run composer and reviewer as separate persistent supervisor layers:

```powershell
python scripts/run_orchestrator.py
python scripts/run_claude_event_consumer.py
```

Live acceptance requires local Claude authentication and network access. It was not executed in the restricted build because this task explicitly forbids external network use; `tests/fixtures/claude_event_consumer/evidence.json` is deterministic fixture evidence, not a claim of a live review.
