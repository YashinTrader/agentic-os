# Protocol Recommendation: Dashboard & Coordination Gaps

While implementing the V0 local-first dashboard, we identified several structural gaps in the Phase 1 file-based coordination protocol. Below are specific recommendations for Phase 2 to improve the accuracy, efficiency, and depth of the dashboard.

---

## 1. Task Handoff Traceability
* **The Gap:** The `TASK_SCHEMA.md` does not maintain a list of past handoffs. To reconstruct the handoff history for a task, the dashboard must scan the entire `handoffs/` directory and parse all filename prefixes.
* **Recommendation:** Add a `handoff_history` list field to the task schema.
  ```yaml
  handoff_history:
    - from: codex
      to: claude
      date: 2026-05-23T00:10:00Z
      ref: handoffs/T-0001__codex__to__claude.md
  ```

---

## 2. Event Log Sequence & Ordering
* **The Gap:** In a high-concurrency multi-agent run, multiple events can log at the exact same ISO-8601 second, leading to ordering ambiguities in the dashboard's timeline view.
* **Recommendation:** Include an atomic incremental sequence number (`seq`) in every JSONL log event:
  ```json
  {"seq": 142, "ts": "2026-05-23T08:00:00Z", "agent": "gemini", "task": "T-TEST", "event": "started"}
  ```

---

## 3. Inline State History
* **The Gap:** The task YAML file only retains the *current* state. Finding when a task transitioned status or changed owners requires full-scan search of `logs/agent-events.jsonl`.
* **Recommendation:** Embed a state transition log directly inside the task file:
  ```yaml
  state_transitions:
    - status: todo
      updated: 2026-05-23T05:55:16Z
      owner: gemini
    - status: in_progress
      updated: 2026-05-23T05:55:22Z
      owner: gemini
  ```

---

## 4. Git Metadata Integration
* **The Gap:** Since the Control Plane runs on a Git repository, there's no coupling between the task file and the Git state. The dashboard cannot show which Git branch holds a task or which commit landed it.
* **Recommendation:** Add optional fields in the schema to record active Git context:
  ```yaml
  git_branch: agent/gemini/T-DASHBOARD-V0
  last_commit: a8c7f12
  ```
