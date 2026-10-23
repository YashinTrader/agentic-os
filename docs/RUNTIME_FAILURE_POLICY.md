# Runtime failure policy

Every child exit or failed launch records `failure_class`. Existing exit history,
ownership identities and graceful stop controls remain available.

| Class | Evidence | Action and resume condition |
| --- | --- | --- |
| `BLOCKED_SECURITY_POLICY` | WinError 4551, 1260, 4556, 225; Application Control, group policy, Code Integrity or Enterprise signing stderr | Immediately block the child and open its circuit. Switch to a permitted signed runtime or ask the operator; do not disable Smart App Control. One probe is allowed after executable path or SHA-256 changes, or an audited operator reset. |
| `CONFIG` | FileNotFoundError or WinError 2/3 | Immediately block and alert. Restore the missing executable; its appearance permits one probe. An audited reset also permits a probe. |
| `TRANSIENT` | Other failures, process exits or heartbeat hangs | Retry with uniform full jitter between the two-second floor and an exponential ceiling capped at 300 seconds. More than five exits in 600 seconds opens the circuit. |

Executable evidence includes resolved path, size, nanosecond mtime and SHA-256.
Blocked executables are checked at most once per 60 seconds. Unchanged size and
mtime reuse the cached hash. Alerts live in `runtime/dispatch/alerts/`; child alert
IDs derive from layer, executable path and SHA-256. Repeated denials of the same
identity do not rewrite the alert. A different identity has its own alert.

Transient circuits permit one half-open probe after 15 minutes. Failed probes
double the cooldown to a four-hour maximum. Ten minutes of sustained child
operation clears its failure backoff. Probe deadlines and cooldowns survive root
restarts; persisted deadlines use Unix wall time, local scheduling uses monotonic
time. A successful launch must still produce a valid heartbeat to be running.

When all children have open circuits and no live processes, the root publishes
`state: parked`, `parked_reason`, and one root park alert. It stays alive, checks
controls and sleeps five seconds. Normally it sleeps one second; while any child
is starting it sleeps 0.25 seconds. Status writes occur on content changes
(ignoring `updated_at`) or a liveness deadline: 30 seconds normally, 60 seconds
while parked. Stable healthy idle is below 0.2 writes/second; stable parked idle
is at most one write/minute. Heartbeat-only counters and tick timestamps are
batched into five-second status updates, so continuously ticking idle children
also stay within the healthy budget. Failures, state transitions, progress
changes and control acknowledgements are persisted immediately.

The launcher enables a root-start guard under the existing instance/control
locks. `runtime/dispatch/layer_supervisor/root_starts.json` records starts. The
fourth start within 30 minutes is refused with exit 78 and one stable alert.
Cooldown begins at 30 minutes and doubles on failed root probes to eight hours.
After cooldown one root probe may start. Both children continuously running for
ten minutes reset the guard. A completed planned shutdown removes its own start
from the crash budget. A duplicate live root or maintenance refusal consumes no
start. State and alerts are local files; no remote notification is implied.

Operator commands (use the permitted signed Python runtime):

```powershell
$runtimePython = "C:\Users\gabot\agentic-os-runtime\py311\Scripts\python.exe"
& $runtimePython scripts/stop_supervisor.py --state-root <root> --reset-circuit builder --actor <operator> --reason <remediation>
& $runtimePython scripts/run_supervisor_layers.py --state-root <root> --reset-root-guard --actor <operator> --reason <remediation>
& $runtimePython scripts/stop_supervisor.py --state-root <root> --actor <operator> --reason <planned-stop>
```

Resets serialize through `operator.lock` and `control.lock`, record durable audit
intent and outcome under `layer_supervisor/audit/`, and require a nonblank actor
and reason. Child resets are consumed once via a durable token, including across
root restarts. Root reset clears the root guard only; it does not unblock children.
Stop requests remain identity-fenced and work while parked.
