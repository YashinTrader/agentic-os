# ADR-0002: YAML for Task Files

**Status:** accepted
**Date:** 2026-05-22
**Author (agent):** human
**Reviewer (agent):** claude
**Approval:** none

## Context
Task files need to be both human-editable and machine-parseable. Candidates:
JSON, YAML, TOML, Markdown front-matter.

## Decision
Use YAML for task files in `tasks/active/`, `tasks/done/`, `tasks/blocked/`.

## Alternatives Considered
1. JSON — rejected: no comments, noisier to edit by hand.
2. TOML — rejected: weaker support for nested lists in agent SDKs.
3. Markdown with front-matter — rejected: split between structured and freeform
   parts increases parsing complexity.

## Consequences
- Pro: easy for humans to edit; widely supported parsers.
- Con: YAML's whitespace sensitivity can bite; validator script will catch it.

## References
- docs/TASK_SCHEMA.md
