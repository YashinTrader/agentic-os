"""Completion checks run under the same OS boundary as untrusted builder code."""
from __future__ import annotations

import fnmatch
from pathlib import Path
import shlex
import shutil
import subprocess
import sys


def verify_completion(plan, contract, *, base_sha, evidence_dir):
    from orchestrator.agent_launcher import LaunchPlan, launch_process
    from orchestrator.builder_isolation import standalone_workspace
    from orchestrator.process_ownership import terminate_owned
    root = standalone_workspace(Path(plan.cwd))
    failures, evidence = [], []

    def run(argv, label):
        out, err = evidence_dir/f'{label}.stdout', evidence_dir/f'{label}.stderr'
        check = LaunchPlan('acceptance', 'isolated-acceptance', argv, str(root), argv[0],
                           contract_sha256=plan.contract_sha256, env=plan.env,
                           dispatch_root=plan.dispatch_root)
        handle, reason = launch_process(check, stdout_path=out, stderr_path=err)
        if handle is None:
            failures.append(label + ': ' + reason)
            return None
        try:
            code = handle.process.wait(timeout=600)
        except (subprocess.TimeoutExpired, OSError) as exc:
            failures.append(f'{label}: {exc}')
            return None
        finally:
            terminate_owned(handle.process)
            if hasattr(handle.process, 'drain_output'):
                handle.process.drain_output()
        evidence.append({'check': label, 'argv': argv, 'exit_code': code})
        if code:
            failures.append(f'{label}: exit {code}; see {err.name}')
            return None
        return out.read_text(encoding='utf-8', errors='replace')

    git = shutil.which('git')
    files = []
    if not git:
        failures.append('git unavailable for completion verification')
    else:
        for label, args in (
            ('completion-diff', ['diff', '--no-ext-diff', '--no-textconv', '--name-only', '-z', base_sha, '--']),
            ('completion-untracked', ['ls-files', '--others', '--exclude-standard', '-z']),
        ):
            output = run([git, '-c', 'core.fsmonitor=false', '--no-optional-locks', *args], label)
            if output:
                files.extend(name for name in output.split('\0') if name)
    allowed = [name for name in files if any(fnmatch.fnmatchcase(name, pattern)
                                             for pattern in contract['allowed_edit_paths'])]
    if not allowed:
        failures.append('completion_condition_unmet: no diff within allowed_edit_paths')
    unexpected = [name for name in files if name != contract['handoff_path'] and name not in allowed]
    if unexpected:
        failures.append('completion_condition_unmet: edits outside allowed paths: ' + ', '.join(unexpected))
    if not (root/contract['handoff_path']).is_file():
        failures.append('completion_condition_unmet: handoff missing at ' + contract['handoff_path'])
    for index, command in enumerate(contract['acceptance_commands']):
        argv = shlex.split(command)
        if argv and argv[0] in {'python', 'python3', 'python.exe'}:
            argv[0] = sys.executable
        if not argv:
            failures.append(f'acceptance-{index}: empty command')
            continue
        run(argv, f'acceptance-{index}')
    return failures, evidence
