# Phase 1.5 CLI Task Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add minimal file-based CLI helpers for creating, listing, updating, logging, and handoff creation.

**Architecture:** Five standalone Python scripts operate directly on the approved Phase 1 repository files. They use the existing PyYAML dependency for task YAML and Python standard library for paths, argparse, JSONL, timestamps, and file movement.

**Tech Stack:** Python 3, PyYAML, unittest, existing Phase 1 file protocol.

---

### Task 1: Add CLI Behavior Tests

**Files:**
- Create: `tests/test_phase15_cli.py`

- [ ] **Step 1: Write failing tests**

Create tests that copy the repo to a temporary directory, invoke each script with `--root`, and assert the expected file side effects.

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m unittest tests.test_phase15_cli`

Expected: FAIL because the Phase 1.5 scripts do not exist yet.

### Task 2: Implement Five Scripts

**Files:**
- Create: `scripts/create_task.py`
- Create: `scripts/list_tasks.py`
- Create: `scripts/update_task.py`
- Create: `scripts/append_log.py`
- Create: `scripts/create_handoff.py`

- [ ] **Step 1: Implement minimal script behavior**

Implement only file-based operations:
- create task YAML in `tasks/active/`
- list tasks from `tasks/active/`, `tasks/done/`, `tasks/blocked/`
- update task status/owner and move task files for `done` or `blocked`
- append one JSON object per line to `logs/agent-events.jsonl`
- create handoff Markdown with required sections

- [ ] **Step 2: Run tests**

Run: `python -m unittest tests.test_phase15_cli`

Expected: PASS.

### Task 3: Verify and Publish

**Files:**
- Modify: `tasks/PHASE_1_TASKS.md`
- Modify: `logs/agent-events.jsonl`
- Create: `tasks/done/T-0012.yaml`
- Create: `handoffs/T-0012__codex__to__claude.md`

- [ ] **Step 1: Run full verification**

Run:
```powershell
python -m unittest
python scripts/validate.py
```

Expected: both exit 0.

- [ ] **Step 2: Publish to GitHub**

Upload all repository files except `.codex/`, `__pycache__/`, and `.pyc` to `YashinTrader/agentic-os`.
