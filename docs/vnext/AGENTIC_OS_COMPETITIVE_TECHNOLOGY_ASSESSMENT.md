# Agentic OS — Competitive Technology Assessment

**Date:** 2026-10-21 · **Author:** Claude (Development Director)

## Method and limits

Facts come from each project's primary source (GitHub README or official site) fetched on 2026-10-21, supplemented by third-party write-ups only where marked. **No prototype was run for this document.** Prototype spikes are scheduled as roadmap tasks (M2-S1, M2-S2). Treat capability claims as vendor statements until a spike confirms them.

Deciding constraints for Agentic OS:

1. **Windows 11 is the primary host.** WSL 2 (Ubuntu) is available.
2. Must run **Claude Code, Codex, and Grok Build** (plus cheap analysis models).
3. **One owner of orchestration state.** No stacked orchestrators.
4. Unattended operation with evidence-gated completion.

## Comparison

| Project | Category | License | Windows | Claude / Codex / Grok | State store | Maturity signal |
|---|---|---|---|---|---|---|
| **Omnigent** | Meta-harness runtime | Apache-2.0 | *"Runs natively on Windows in a degraded mode"* — no native terminal wrappers for `claude`/`codex`/`cursor` (use WSL); Windows sandbox = Job Object only, *"not isolate the filesystem or network"* | Yes / Yes / Yes (`--harness grok`) | `~/.omnigent` + DB options | Alpha badge; ~11k stars; 868 open issues; telemetry on by default |
| **Gas City** | Declarative orchestration (Go) | MIT | Not stated; install docs macOS/Linux only | Yes / Yes / not mentioned | Beads (Dolt) or file store | 1.4k stars; 967 open issues; Bazel CI |
| **Beads (`bd`)** | Durable agent task graph | MIT | Listed (Windows 11 install via `install.ps1`) | Agent-agnostic CLI + `bd setup` hooks | Dolt (embedded single-writer; server mode for concurrent writers) | v1.0 reported; atomic `--claim`, `bd ready` |
| **Archon** | YAML workflow/DAG engine | MIT | PowerShell installer; support level not stated | Yes / Yes / No (Pi as third) | SQLite (default) / Postgres | 23.7k stars; deterministic gates, approval waits, merge-queue gate |
| **AionUi** | Desktop GUI (Electron) | Apache-2.0 | Yes (third-party) | Yes / Yes / not confirmed | Local app | ~29.5k stars (third-party); leader/teammate mode over ACP |
| **Conductor** | Mac app, worktree workspaces | Proprietary | **No** (Apple Silicon only) | Yes / Yes / No | App-managed | Vendor claims only |
| **Nimbalyst** | Desktop workspace | Unconfirmed | Yes | Yes / Yes / unknown | App-managed | Vendor/directory sources only |
| **Polygraph** | Cross-repo memory meta-harness | Unknown | Unknown | Agent-agnostic (claimed) | Hosted | Product Hunt / marketing only — **unverified** |

## Evaluation of the three architecture options

### Option 1 — Continue with the hardened Agentic OS runtime

- **For:** It is the only option verified working on this machine today: the live builder→reviewer→verdict loop, Windows-native supervisor, Grok support, per-assignment MCP isolation, and the evidence-gate discipline. It needs no migration.
- **Against:** File-based state is the root cause of most incidents. It has a 40k-line maintenance burden for one owner, and integration debt.
- **Verdict:** **Recommended.** Keep it as the sole control plane. Replace the state layer, not the runtime. Stop building commodity UI and workspace features.

### Option 2 — Omnigent as the runtime substrate

- **For:** It has a strong policy model (allow/block/ask; `cost_budget`, `max_tool_calls_per_session` at server, agent, and session scope), first-class Grok support, live shared sessions, cloud sandboxes, and corporate backing.
- **Against:** It is **alpha**. On our host OS it is **degraded exactly where we need it**: no native Claude/Codex wrappers, and Windows isolation does not restrict the filesystem or network. Running it in WSL moves the agents away from Windows-native tooling and doubles the environment surface. It owns its own session state, so adopting it means migrating our ledger semantics into it.
- **Verdict:** **Not now.** Re-evaluate at day 90 via spike M2-S2 in WSL. Borrow its three-level policy design now.

### Option 3 — Gas City / Beads as the durable orchestration substrate

- **Gas City** has no stated Windows support, is tmux-centric, and does not mention Grok. Adopting it means running orchestration inside WSL and rewriting adapters. The stack's creator was reported (one source, August 2026) to have abandoned his own Gas Town workflow. That is unverified, but it is a caution. **Rejected as substrate.**
- **Beads alone** is the interesting component. It is a ledger, not an orchestrator: Windows-listed, MIT, with an atomic claim and a dependency graph (`bd ready`). That directly addresses our duplicate-work and stuck-claim failures. Its cost is a Dolt dependency and a single writer in embedded mode.
- **Verdict:** **Evaluate Beads as a ledger backend** behind a `TaskLedger` interface (spike M2-S1), compared against a stdlib SQLite WAL store. Agentic OS must keep **sole ownership** of orchestration decisions. Beads would only persist work items.

### Not substrates — design references

- **Archon** is the closest match to our "deterministic gates around AI judgment" thesis. Borrow the workflow-as-data idea (nodes, `until_bash` loops, approval waits). Do not run it alongside our supervisor.
- **AionUi / Nimbalyst / Conductor** are operator UIs. They are evidence that a kanban-of-sessions UX is table stakes. Conductor is excluded (no Windows).
- **Polygraph** is unverifiable today. Cross-agent memory is a real gap for us; start with Beads-style `remember`/`prime` semantics or our own project memory before buying.

## Where Agentic OS can genuinely differentiate

Most tools above are **single-vendor-agnostic launchers or UIs**. None that we verified combines:

1. **Cross-vendor independent verification:** the builder and the reviewer are always different vendors, and the reviewer re-executes the gates.
2. **Subscription and quota-aware routing** across Claude, Grok, Codex, and cheap models, with spend visible per outcome.
3. **Evidence-gated completion:** SHA reachability, closeout gates, and honest handoffs as hard invariants.
4. **Windows-native unattended operation.**

These are hypotheses, not proven advantages. The Evaluation Plan defines how to measure them.

## Sources

- Omnigent — https://github.com/omnigent-ai/omnigent
- Beads — https://github.com/gastownhall/beads
- Gas City — https://github.com/gastownhall/gascity, https://gascity.com/
- Archon — https://github.com/coleam00/archon
- AionUi — https://recca0120.github.io/en/2026/04/07/aionui-ai-cowork-app/ (third-party)
- Conductor — https://www.conductor.build/docs/concepts/git-worktrees, https://www.morphllm.com/conductor-ai-coding
- Nimbalyst — https://www.sitepoint.com/nimbalyst-the-visual-workspace-for-building-with-claude-code-and-codex/
- Polygraph — https://www.producthunt.com/p/polygraph
- Gas Town context — https://ascii.co.uk/news/article/news-20260102-190a5f9f/steve-yegge-releases-gas-town-multi-agent-orchestrator-for-c
