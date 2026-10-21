# Handoff: T-M1-05-PROVENANCE-DEPLOY-ROOT
**From:** codex
**To:** claude
**Date:** 2026-10-21
**Task Status After Handoff:** review (uncommitted working tree)
**Handoff Protocol:** v2

## What I Did

- Replaced checkout-path equality with root-history plus configured remote identity. Local origin/canonical remote chains are followed offline, with history identity checked at every hop and cycles rejected. The Git-backed verifier compares both its checkout and the artifact against the canonical repository; accessible artifact origins are independently checked. The canonical anchor defaults to C:/Users/gabot/agentic-os and can be supplied with --canonical-repo for other installations.
- Added artifact repo_identity, artifact_origin_path, hostname, python_version, command_line, raw_output_sha256 and evidence_block_sha256. Store complete raw test output bytes rather than a tail. Recompute the output digest, test count, unittest result summary and failure ids when loading. Preserve true subprocess exit codes.
- Require a full exact tests_commit_sha matching the handoff and reachable from verifying HEAD. Existing implementation-SHA, post-test allowlist and validator checks remain enforced. Non-zero test exits require every failure id in a JSON known_exempt_failures list in the handoff. Incomplete summaries and non-test errors fail closed; no blanket cp1252 exemption is built in.
- Seal the Repository Verification section in the artifact. Editing that section invalidates verification. scripts/run_tests.py now requires --handoff <path> so the producer can seal that section; finalize its evidence block before generating the artifact. Failure exemption entries use unittest's exact `test_method (module.Class)` failure-header format. Historical artifacts without the new evidence intentionally require regeneration.
- Added shared state-root selection for all three deploy entrypoints: --state-root overrides AGENTIC_OS_STATE_ROOT, which overrides the existing default/legacy --root value. Require existing runtime/ and agents/ directories. Parent and children use state-root runtime state and default logs, while child executable script paths and Python imports remain in the deployed code checkout.
- Registered this handoff in POST_TEST_ALLOWLIST_EXACT. Added 13 regression tests and updated existing artifact fixture expectations.

## What Remains

- Commit from a Git-writable environment and regenerate committed-implementation verification evidence. Staging was denied creating .git/index.lock; this clone has no implementation commit.
- The SHA fields below anchor the unchanged base for structural v2 compatibility. They do not attest that these working changes were committed or tested at that SHA. The existing runtime/unittest_last_run.txt was preserved; no committed-tip artifact verification is claimed.

## Decisions Made

Follow only local filesystem remote links without network access, comparing root histories at each hop and the terminal configured remote URL. Missing origins, unavailable canonical identity and cyclic links fail closed. Do not compare hostname/Python version with the receiving machine, since builds may legitimately come from another host.

Hash the evidence section separately from the handoff prose, storing the digest in the artifact to avoid a self-referential hash. Hash the raw output bytes exactly as stored. The artifact is integrity evidence, not a cryptographic signer authentication mechanism.

## Open Questions

None blocking review. The receiver must regenerate the artifact after committing and finalize evidence fields before sealing it.

## How to Verify My Work

Focused verification only:

```powershell
python -m unittest -v tests.test_provenance_deploy_root tests.test_phase3_4_1_integrity_closeout tests.test_layer_supervisor tests.test_claude_event_consumer
python scripts/validate.py
git diff --check
```

In this sandbox, the normal temporary-directory ACLs prevent test fixture writes. The local runtime/dispatch/m1-05/run_focused.py harness redirects tempfile.mkdtemp into ordinary directories under this clone, without changing production code. The final invocation of that harness ran the four modules above: 78 tests, exit 0. Evidence: runtime/dispatch/m1-05/final-focused-tests.txt. Coverage includes same-identity clone paths, foreign remotes/history, exact SHA and reachability, output tampering, explicit exemptions with true non-zero exit, CRLF failure output, evidence edits, state-root default/flag/env/invalid selection, and entrypoint wiring. Real Git object stores are copied locally for the identity fixture because shell-based git clone transport is blocked by this sandbox.

validate.py passed with existing deprecated v1 event warnings. git diff --check passed. No full test suite, session pickup, network call, push or merge was run. No dependencies were changed; a network dependency audit was not run under the task's network prohibition.

## Risks / Caveats

Working-tree verification only. Initial fixture runs failed due to sandbox temporary-directory ACLs; the final isolated harness run passed. Discarded local Git-clone fixture attempts encountered a Windows shell CreateFileMapping permission error, resolved by copying the fixture's Git object store rather than using transport.

Configured remote URLs are compared exactly, so alternate SSH/HTTPS spellings require consistent configuration. Deleted disposable origins are supported through recorded identity plus reachable commit validation; an accessible origin with mismatched identity is rejected. Historical artifacts need regeneration with full raw output and a sealed handoff block.

## Recommended Next Action for Receiver

Review and commit the scoped changes in a Git-writable environment. Run focused checks at the committed implementation and regenerate the sealed artifact with truthful SHA fields. Deploy the pinned code checkout using --state-root pointing to the existing runtime repository, without switching the development checkout.

## Repository Verification

repo_root: C:/Users/gabot/agentic-os-worktrees/m1-05-provenance
branch: agent/codex/T-M1-05-PROVENANCE-DEPLOY-ROOT
base_sha: 608ccc8315c20770ac52f46a6a5069e350f98eb2
implementation_sha: 608ccc8315c20770ac52f46a6a5069e350f98eb2
tests_commit_sha: 608ccc8315c20770ac52f46a6a5069e350f98eb2
final_head_sha: 608ccc8315c20770ac52f46a6a5069e350f98eb2
remote_head_sha: 608ccc8315c20770ac52f46a6a5069e350f98eb2
git_status_clean: false
validator_commit_sha: 608ccc8315c20770ac52f46a6a5069e350f98eb2
test_count: 78
test_exit_code: 0
known_exempt_failures: []
validator_exit_code: 0
post_test_diff_policy: POST_TEST_ALLOWLIST_EXACT; working changes uncommitted, committed-tip verification pending
post_test_files: handoffs/T-M1-05-PROVENANCE-DEPLOY-ROOT__codex__to__claude.md
working_copy_path: C:/Users/gabot/agentic-os-worktrees/m1-05-provenance
