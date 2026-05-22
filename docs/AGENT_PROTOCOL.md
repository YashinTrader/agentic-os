# Agent Protocol v1

This document defines **the contract every agent must follow** to participate
in the Agentic OS. If you are an LLM agent reading this: these rules are
binding for every action you take in this repo.

## 1. Identity
Each agent has a stable lowercase identifier:
`codex`, `claude`, `cursor`, `gemini`, `hermes`, `human`.

Always identify yourself in commits, logs, and handoffs using this exact string.

## 2. Branching
- Work on `agent/<your-id>/<task-id>`.
- Never commit directly to `main`.
- Never merge a PR. Humans merge.

## 3. The Read–Plan–Act–Log–Handoff Loop
Every work session **must** follow this loop:

1. **READ**
   - Pull latest `main`.
   - Read your assigned task: `tasks/active/<id>.yaml`.
   - Read any referenced inputs and the latest handoff (if any).
   - Read recent entries of `logs/agent-events.jsonl` for context.

2. **PLAN**
   - If the task is unclear or risky, **stop** and open an ADR draft in
     `decisions/` with `status: proposed`. Do not act.

3. **ACT**
   - Make changes only inside your branch.
   - Update the task YAML's `status` field as you progress.

4. **LOG**
   - Append at least one event to `logs/agent-events.jsonl` per significant
     action (started, blocked, decision_needed, finished).
   - See §6 for the event schema.

5. **HANDOFF**
   - Before ending your session, write a handoff file (see `HANDOFF_PROTOCOL.md`).
   - Update task `status` to `review`, `blocked`, or `done`.
   - Open a PR with a clear title: `[<agent-id>] <task-id>: <summary>`.

## 4. Task Status Machine
```
todo → in_progress → review → done
                  ↘ blocked ↗
```
Allowed transitions only. Any other transition is invalid.

## 5. Risky Actions (Require Human Approval)
An agent **must not** perform any of the following without an approved ADR:
- Deleting files outside `tasks/active/` (archival to `tasks/done/` is fine).
- Modifying `docs/AGENT_PROTOCOL.md`, `docs/ARCHITECTURE.md`, or any schema doc.
- Installing new top-level dependencies or changing build/CI config.
- Running anything that touches the network beyond fetching documented inputs.
- Force-pushing, rebasing shared branches, or rewriting history.
- Editing another agent's in-progress task or handoff.

To request approval: write an ADR with `status: proposed` and `approval: human`,
then log a `decision_needed` event. Wait.

## 6. Event Log Format (`logs/agent-events.jsonl`)
One JSON object per line. Append only. Never edit prior lines.

```json
{"ts":"2026-05-22T10:14:03Z","agent":"codex","task":"T-0007","event":"started","detail":"picked up task from todo"}
{"ts":"2026-05-22T10:32:11Z","agent":"codex","task":"T-0007","event":"progress","detail":"scaffolded tasks/ directory"}
{"ts":"2026-05-22T10:48:55Z","agent":"codex","task":"T-0007","event":"decision_needed","detail":"naming convention for handoff files","ref":"decisions/ADR-0003-handoff-naming.md"}
{"ts":"2026-05-22T11:05:02Z","agent":"codex","task":"T-0007","event":"handoff","detail":"to claude for review","ref":"handoffs/T-0007__codex__to__claude.md"}
```

**Required fields:** `ts` (ISO-8601 UTC), `agent`, `task`, `event`.
**Allowed `event` values:** `started`, `progress`, `blocked`, `decision_needed`,
`handoff`, `finished`, `error`.
**Optional fields:** `detail`, `ref` (path to related file).

## 7. Commit Message Convention
```
[<agent-id>] <task-id>: <imperative summary>

<optional body>

Refs: handoffs/<file>, decisions/ADR-####
```

## 8. When in Doubt
- Stop. Log a `decision_needed` event. Write a draft ADR. Hand off to `claude`
  or `human`. Never guess on architecture, security, or scope.
