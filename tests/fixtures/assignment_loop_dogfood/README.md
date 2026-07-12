# Assignment loop dogfood fixtures

Captured from a real local run of `scripts/assignments.py` for
`T-PHASE3-8B-DOGFOOD` on 2026-07-12.

| File | Source |
|------|--------|
| assignment.json | runtime/dispatch/assignments/inbox/assign-20260712T154435Z-T-PHASE3-8B-DOGFOOD-39c5a953.json |
| claim.json | runtime/dispatch/assignments/claims/assign-20260712T154435Z-T-PHASE3-8B-DOGFOOD-39c5a953.json |
| result.json | runtime/dispatch/assignments/outbox/assign-20260712T154435Z-T-PHASE3-8B-DOGFOOD-39c5a953.json |
| ingest.json | runtime/dispatch/assignments/ingest/latest_ingest.json |
| HANDOFF.md | handoffs/T-PHASE3-8B-DOGFOOD__composer__to__claude.md |

Commands used:
```
python scripts/assignments.py create --from-task tasks/active/T-PHASE3-8B-DOGFOOD.yaml ...
python scripts/assignments.py claim assign-20260712T154435Z-T-PHASE3-8B-DOGFOOD-39c5a953
python scripts/assignments.py complete assign-20260712T154435Z-T-PHASE3-8B-DOGFOOD-39c5a953 --handoff ... --branch-tip-sha ...
python scripts/assignments.py ingest
```
