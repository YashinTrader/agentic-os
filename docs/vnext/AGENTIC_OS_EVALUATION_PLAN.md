# Agentic OS — Evaluation Plan

**Purpose:** Turn VNext claims (reliability, quality, cost, differentiation) into measurements. No metric may be reported without its raw source.

## Baseline (M1 start, 2026-10-21)

| Metric | Baseline | Source |
|---|---|---|
| Unattended uptime | Supervisor died 2026-10-20 21:46; not restarted | Task Scheduler + log |
| Manual state repairs / week | ≥5 (July–Aug incidents) | Audit §4 |
| Builder→verdict latency (live) | ~100 s review stage | Live run 2026-10-21 |
| Reviewer executed gates | 0 of 3 | Live run verdict |
| Duplicate builds | 1 known (9-6) | Branch audit |
| Closeout defects per handoff | 6 recurrences before gate | Ledger notes |

## Reliability metrics

| Metric | Definition | M1 target | M3 target |
|---|---|---|---|
| Unattended days | Consecutive days with a live heartbeat and no manual repair | 7 | 30 |
| Event latency p95 | Terminal poke → verdict recorded | < 10 min | < 5 min |
| Stuck events | Events non-terminal > 1 h without `blocked_on` | 0 | 0 |
| Duplicate work | Two active contracts for one task | 0 | 0 |
| Recovery without code | Incidents resolved by recovery verbs only | 80% | 95% |

## Quality metrics

| Metric | Definition |
|---|---|
| First-pass acceptance | % of builder submissions accepted without changes_requested |
| Escaped defects | Defects found after acceptance (e.g., later review or live test) per accepted task |
| Reviewer agreement | % agreement between headless reviewer and orchestrator spot-audit (sample 20%) |
| Gate re-execution | % of verdicts where the reviewer re-ran every deterministic gate (target 100%) |
| Honest-reporting rate | % of handoffs whose structured fields match independent verification |

## Cost metrics

| Metric | Definition |
|---|---|
| Cost per accepted task | Provider spend/quota consumed ÷ accepted tasks, per provider |
| Retry waste | Spend on runs ending failed_launch / blocked_external |
| Routing savings | Actual cost vs counterfactual "all tasks on top-tier model" |

## Differentiation experiments

1. **Cross-vendor review value.** For 20 tasks, record reviewer findings when builder ≠ reviewer vendor and compare with same-vendor self-review on a sample. Hypothesis: cross-vendor finds more real defects per review.
2. **Quota-aware routing.** Simulate exhausted quota on the primary provider and measure time-to-completion with automatic fallback versus waiting for the owner.
3. **Substrate spikes (M2-S1/S2).** Score each spike on the criteria below, 1–5 with notes:
   - Windows-native operation
   - Atomic claim under 4 concurrent writers
   - Crash recovery
   - Install friction
   - Maintenance surface
   - Grok support
   - Security isolation

## Evidence rules

- Every number links to a run ID, log file, or SHA.
- Fixture evidence and live evidence are labeled separately.
- Metrics are collected by scripts in `scripts/metrics/` (task M2-03), not by agent self-report.
- The weekly report is generated from the ledger. Claude reviews it, and Gabriel receives the summary.
