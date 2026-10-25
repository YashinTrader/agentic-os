"""Boundary evidence uses real Windows tokens and subprocesses, never a fake OS."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

from orchestrator.agent_launcher import LaunchPlan, launch_process, build_grok_launch_plan, UNSAFE_GROK_FLAGS
from orchestrator.builder_isolation import IsolationError, builder_environment, standalone_workspace, _label
from orchestrator.task_contract import ContractError, prepare_contract, verify_contract, contract_prompt

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = r'''
import json, subprocess, sys, winreg
from pathlib import Path
outside = Path(sys.argv[1])
root = Path.cwd()
other = Path(sys.argv[2])
probe = sys.argv[3]
results = {}
def attempt(name, operation):
    try:
        operation()
        results[name] = 'UNEXPECTED_WRITE'
    except OSError as exc:
        # open() reports an access denial as errno 13 (no winerror); os-level calls as winerror 5.
        results[name] = 'denied' if isinstance(exc, PermissionError) or exc.winerror == 5 else repr(exc)
attempt('create', lambda: (outside/'new').write_text('bad'))
attempt('append', lambda: (outside/'victim').open('a').write('bad'))
attempt('rename', lambda: (outside/'rename').rename(outside/'renamed'))
attempt('delete', lambda: (outside/'delete').unlink())
attempt('inbox', lambda: (outside/'state/inbox.json').write_text('bad'))
attempt('claim_delete', lambda: (outside/'state/claim.json').unlink())
attempt('claim_create', lambda: (outside/'state/new-claim.json').write_text('bad'))
attempt('task_move', lambda: (outside/'task.yaml').rename(outside/'moved.yaml'))
attempt('other_builder', lambda: (other/'victim').write_text('bad'))
attempt('registry', lambda: winreg.CreateKey(winreg.HKEY_CURRENT_USER, 'Software\\' + probe))
task = subprocess.run(['schtasks.exe', '/create', '/tn', probe, '/tr', 'cmd /c exit 0',
                       '/sc', 'ONLOGON', '/f'], capture_output=True)
results['scheduled_task'] = 'denied' if task.returncode else 'UNEXPECTED_WRITE'
attempt('git', lambda: (outside/'.git/config').write_text('bad'))
for name, command in (
    ('absolute_script', [sys.executable, str(outside/'writer.py')]),
    ('descendant', [sys.executable, '-c', "from pathlib import Path; Path(" + repr(str(outside/'state/child.json')) + ").write_text('bad')"]),
):
    child = subprocess.run(command, capture_output=True, text=True)
    results[name] = 'denied' if child.returncode != 0 and 'PermissionError' in child.stderr else 'UNEXPECTED_WRITE'
(root/'inside').write_text('ok')
(root/'.git/inside').write_text('ok')
(root/'.agentic/profile/inside').write_text('ok')
results['inside'] = 'ok'
print(json.dumps(results), flush=True)
sys.exit(0 if all(v in ('denied', 'ok') for v in results.values()) else 1)
'''


class WorkspaceFixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)

    def prepare(self, **changes):
        task = {'objective': 'Fix fixture', 'allowed_paths': ['src/**'],
                'handoff_path': 'handoffs/result.md', **changes}
        return prepare_contract(self.root, json.dumps(task).encode())


class ContractTests(WorkspaceFixture, unittest.TestCase):
    def test_schema_hash_and_ignored_materialized_files(self):
        contract, digest = self.prepare()
        self.assertTrue(contract['derived'])
        self.assertEqual(verify_contract(self.root, digest), contract)
        self.assertIn('already assigned', contract_prompt(contract))
        self.assertIn('Do not run session pickup', contract_prompt(contract))
        self.assertEqual(subprocess.run(['git', '-C', str(self.root), 'check-ignore',
                                        '.agentic/TASK_CONTRACT.json'], capture_output=True).returncode, 0)
        (self.root/'.agentic/TASK_CONTRACT.json').write_text('{}')
        with self.assertRaisesRegex(ContractError, 'hash mismatch'):
            verify_contract(self.root, digest)

    def test_invalid_schema_and_missing_files_refuse_before_launch(self):
        for budget in (True, 0, 201):
            with self.assertRaises(ContractError):
                prepare_contract(self.root, b'{"contract": {}}', turn_budget=budget)
        task = {'contract': {'objective': 'Fix', 'relevant_files': ['missing.py'],
                'allowed_edit_paths': ['src/**'], 'acceptance_commands': [],
                'completion_condition': 'handoff', 'handoff_path': 'handoffs/result.md'}}
        with self.assertRaisesRegex(ContractError, 'contract_files_missing'):
            prepare_contract(self.root, json.dumps(task).encode())
        plan = LaunchPlan('composer', 'composer-restricted', ['unused'], str(self.root), 'unused')
        with patch('orchestrator.builder_isolation.launch_isolated') as launch:
            handle, reason = launch_process(plan, stdout_path=self.root/'out', stderr_path=self.root/'err')
            self.assertIsNone(handle)
            self.assertIn('contract_invalid', reason)
            launch.assert_not_called()

    def test_reject_shared_git_and_escape_paths(self):
        (self.root/'.git/commondir').write_text('../other')
        with self.assertRaises(IsolationError):
            standalone_workspace(self.root)
        for path in ('../outside', 'C:/outside', '/outside', 'src/../../other'):
            with self.assertRaises(ContractError):
                self.prepare(allowed_paths=[path])

    def test_env_uses_only_private_profile(self):
        with patch.dict(os.environ, {'AGENTIC_OS_STATE_ROOT': 'live', 'AGENTIC_OS_CONFIG_ROOT': 'deploy',
                                     'GIT_DIR': 'outside', 'SECRET_TOKEN': 'secret'}):
            env = builder_environment(self.root, self.root/'profile', 'test')
        for name in ('AGENTIC_OS_STATE_ROOT', 'AGENTIC_OS_CONFIG_ROOT', 'GIT_DIR', 'SECRET_TOKEN'):
            self.assertNotIn(name, env)
        self.assertEqual(env['AGENTIC_BUILDER_RUN_ID'], 'test')
        self.assertEqual(env['TEMP'], str(self.root/'profile'))

    def test_grok_deny_plan_keeps_30_turns_without_unverified_sandbox(self):
        with patch.dict(os.environ, {'AGENTIC_OS_STATE_ROOT': 'C:/fake-live',
                                     'AGENTIC_OS_DEPLOY_ROOT': 'C:/fake-deploy'}):
            plan = build_grok_launch_plan(worktree=self.root, prompt='fixture',
                grok_executable=sys.executable,
                version_runner=lambda *a, **k: subprocess.CompletedProcess([], 0, 'fixture', ''))
        self.assertEqual(plan.argv[plan.argv.index('--max-turns') + 1], '30')
        self.assertNotIn('--sandbox', plan.argv)
        for name in ('session_pickup', 'assignments', 'work_lock', 'consumer_claims'):
            self.assertTrue(any(name + '.py' in arg for arg in plan.argv))
        self.assertIn('C:/fake-live/**', plan.argv)
        self.assertIn('C:/fake-deploy/**', plan.argv)
        self.assertFalse(UNSAFE_GROK_FLAGS.intersection(plan.argv))

    def test_labelling_failure_is_fatal(self):
        with patch('orchestrator.builder_isolation.subprocess.run',
                   return_value=subprocess.CompletedProcess([], 5, '', 'access denied')):
            with self.assertRaisesRegex(IsolationError, 'labelling failed'):
                _label(self.root)

    def test_cli_guards_and_supervisor_exemption(self):
        for name in ('session_pickup', 'assignments', 'work_lock', 'consumer_claims'):
            result = subprocess.run([sys.executable, str(ROOT/'scripts'/f'{name}.py'), '--help'],
                                    env={**os.environ, 'AGENTIC_BUILDER_RUN_ID': 'test'},
                                    capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertIn('forbidden', result.stderr)
            normal_env = {k: v for k, v in os.environ.items() if k != 'AGENTIC_BUILDER_RUN_ID'}
            normal = subprocess.run([sys.executable, str(ROOT/'scripts'/f'{name}.py'), '--help'],
                                    env=normal_env, capture_output=True, text=True, timeout=15)
            self.assertEqual(normal.returncode, 0, normal.stderr)
        self.assertIn('Supervisor exemption', (ROOT/'AGENTS.md').read_text())


class LabelLifecycleTests(WorkspaceFixture, unittest.TestCase):
    def test_mandatory_label_aliases_and_numeric_levels(self):
        from orchestrator.builder_isolation import _has_low_label
        for sid in ('LW', 'UN', 'S-1-16-4096', 'S-1-16-0', 'S-1-16-2048'):
            self.assertTrue(_has_low_label('S:(ML;OICI;NW;;;' + sid + ')'))
        for sid in ('ME', 'HI', 'S-1-16-8192'):
            self.assertFalse(_has_low_label('S:(ML;OICI;NW;;;' + sid + ')'))

    def test_stale_inventory_refuses_launch(self):
        from orchestrator.builder_isolation import _check_workspaces
        with patch('orchestrator.builder_isolation.assert_medium_tree', side_effect=IsolationError('stale Low')):
            with self.assertRaisesRegex(IsolationError, 'stale Low'):
                _check_workspaces(self.root, self.root.parent)

    def test_stale_child_label_is_detected(self):
        from orchestrator.builder_isolation import assert_medium_tree
        child = self.root/'stale'
        child.write_text('stand-in')
        with patch('orchestrator.builder_isolation._is_low', side_effect=lambda path: path == child):
            with self.assertRaisesRegex(IsolationError, 'stale Low'):
                assert_medium_tree(self.root)

    @unittest.skipUnless(os.name == 'nt', 'Windows kernel required')
    def test_reentrant_gate_is_refused(self):
        import ctypes
        from orchestrator import builder_isolation as b
        def existing(*args):
            ctypes.set_last_error(183)
            return 12
        with patch.object(b.kernel, 'CreateMutexW', side_effect=existing), \
             patch.object(b.kernel, 'CloseHandle') as close, \
             patch.object(b.kernel, 'WaitForSingleObject') as wait:
            with self.assertRaisesRegex(IsolationError, 'another builder'):
                b._acquire_builder_gate()
            wait.assert_not_called()
            close.assert_called_once_with(12)

    @unittest.skipUnless(os.name == 'nt', 'Windows kernel required')
    def test_tree_exit_precedes_medium_restoration_and_gate_release(self):
        from orchestrator import builder_isolation as b
        from types import SimpleNamespace
        events = []
        owner = SimpleNamespace(job=12, close=lambda: events.append('close'))
        proc = b.IsolatedProcess(SimpleNamespace(pid=1, process=2), owner, self.root, 3)
        def exit_code(handle, code):
            import ctypes
            from ctypes import wintypes
            ctypes.cast(code, ctypes.POINTER(wintypes.DWORD))[0] = 0
            return True
        with patch.object(b.kernel, 'WaitForSingleObject', return_value=0), \
             patch.object(b.kernel, 'GetExitCodeProcess', side_effect=exit_code), \
             patch('orchestrator.process_ownership.kernel.TerminateJobObject', return_value=True), \
             patch.object(b, '_wait_tree', side_effect=lambda job: events.append('tree')), \
             patch.object(b, '_label', side_effect=lambda root, level: events.append(level)), \
             patch.object(b, 'assert_medium_tree', side_effect=lambda root: events.append('verify')), \
             patch.object(b.kernel, 'ReleaseMutex', side_effect=lambda h: events.append('release') or True), \
             patch.object(b.kernel, 'CloseHandle'):
            self.assertEqual(proc.poll(), 0)
        self.assertEqual(events, ['tree', 'medium', 'verify', 'close', 'release'])
        proc._handle = None


@unittest.skipUnless(os.name == 'nt', 'real Windows kernel required')
class WindowsBoundaryTests(WorkspaceFixture, unittest.TestCase):
    def test_real_adversarial_builder_and_descendants(self):
        outside = self.root/'protected'
        outside.mkdir()
        (outside/'.git').mkdir()
        (outside/'state').mkdir()
        for name in ('victim', 'rename', 'delete', '.git/config', 'state/inbox.json', 'state/claim.json', 'task.yaml'):
            (outside/name).write_text('original')
        (outside/'writer.py').write_text("from pathlib import Path\nPath(__file__).with_name('state').joinpath('inbox.json').write_text('bad')\n")
        other = self.root/'other-builder'
        other.mkdir()
        (other/'victim').write_text('original')
        before = {p.relative_to(outside): p.read_bytes() for p in outside.rglob('*') if p.is_file()}
        probe = 'AgenticIsolation-' + uuid.uuid4().hex
        import winreg
        def cleanup_probes():
            exists = subprocess.run(['schtasks.exe', '/query', '/tn', probe], capture_output=True)
            if exists.returncode == 0:
                subprocess.run(['schtasks.exe', '/delete', '/tn', probe, '/f'],
                               capture_output=True, check=True)
                self.assertNotEqual(subprocess.run(
                    ['schtasks.exe', '/query', '/tn', probe], capture_output=True).returncode, 0)
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, 'Software\\' + probe)
            except FileNotFoundError:
                pass
        self.addCleanup(cleanup_probes)
        workspace = self.root/'builder'
        workspace.mkdir()
        subprocess.run(['git', 'init', '-q', str(workspace)], check=True)
        (workspace/'fixture.py').write_text(FIXTURE)
        contract, digest = prepare_contract(workspace, json.dumps({
            'objective': 'adversarial fixture', 'allowed_paths': ['inside'],
            'handoff_path': 'handoffs/result.md'}).encode())
        plan = LaunchPlan('composer', 'composer-restricted',
                          [sys.executable, 'fixture.py', str(outside), str(other), probe], str(workspace), sys.executable,
                          contract_sha256=digest)
        stdout, stderr = self.root/'stdout', self.root/'stderr'
        handle, reason = launch_process(plan, stdout_path=stdout, stderr_path=stderr)
        self.assertIsNotNone(handle, 'OS boundary could not be exercised; fail-closed launcher: ' + reason)
        self.addCleanup(handle.process.terminate)
        self.assertEqual(handle.process.wait(30), 0, stderr.read_text())
        # Relay may finish just after process exit.
        import time
        for _ in range(100):
            if stdout.read_text().strip():
                break
            time.sleep(.01)
        results = json.loads(stdout.read_text())
        self.assertEqual(results['inside'], 'ok')
        self.assertTrue(all(v == 'denied' for k, v in results.items() if k != 'inside'), results)
        self.assertEqual(before, {p.relative_to(outside): p.read_bytes()
                                  for p in outside.rglob('*') if p.is_file()})
        self.assertEqual(list(other.iterdir()), [other/'victim'])
        self.assertEqual((other/'victim').read_text(), 'original')
        from orchestrator.builder_isolation import assert_medium_tree
        assert_medium_tree(workspace)
        query = subprocess.run(['schtasks.exe', '/query', '/tn', probe], capture_output=True)
        self.assertNotEqual(query.returncode, 0, 'scheduled task survived probe')
        with self.assertRaises(FileNotFoundError):
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Software\\' + probe):
                pass


@unittest.skipUnless(os.name == 'nt', 'Windows token setup required')
class WindowsSetupFaultTests(WorkspaceFixture, unittest.TestCase):
    """Inject setup faults only; these are not evidence of write denial."""
    def assert_setup_refused(self, stage):
        import ctypes as C
        from ctypes import wintypes as W
        from orchestrator.builder_isolation import adv, kernel
        create_mutex = kernel.CreateMutexW
        gate_name = 'Local\\AgenticIsolationSetupTest-' + uuid.uuid4().hex
        adv.DuplicateTokenEx.argtypes = [W.HANDLE, W.DWORD, C.c_void_p, C.c_int, C.c_int, C.POINTER(W.HANDLE)]
        adv.DuplicateTokenEx.restype = W.BOOL
        def duplicate(original, flags, disabled_count, disabled, deleted_count, deleted, sid_count, sids, output):
            # An actual duplicate lets this unit test reach the injected setup
            # fault even when the host rejects restricted-token creation.
            self.assertEqual((flags, sid_count, sids), (1, 0, None))
            return adv.DuplicateTokenEx(original, 0xF01FF, None, 2, 1, output)
        _, digest = self.prepare()
        plan = LaunchPlan('composer', 'composer-restricted', [sys.executable, '-c', 'print("must not run")'],
                          str(self.root), sys.executable, contract_sha256=digest)
        def deny(*args):
            C.set_last_error(5)
            return False
        fault = (patch('orchestrator.builder_isolation.adv.SetTokenInformation', side_effect=deny)
                 if stage == 'integrity' else
                 patch('orchestrator.builder_isolation._label', side_effect=lambda root, level='low':
                       (_ for _ in ()).throw(IsolationError('labelling injected failure')) if level == 'low' else None))
        with patch.object(kernel, 'CreateMutexW', side_effect=lambda security, owner, name:
                          create_mutex(security, owner, gate_name)), \
                patch('orchestrator.builder_isolation._check_workspaces'), \
                patch('orchestrator.builder_isolation.adv.CreateRestrictedToken', side_effect=duplicate), fault, \
                patch('orchestrator.builder_isolation.adv.CreateProcessAsUserW') as spawn:
            handle, reason = launch_process(plan, stdout_path=self.root/'out', stderr_path=self.root/'err')
            self.assertIsNone(handle)
            spawn.assert_not_called()
        self.assertIn('lower integrity' if stage == 'integrity' else 'labelling', reason)

    def test_lowering_failure_refuses_process_creation(self):
        self.assert_setup_refused('integrity')

    def test_labelling_failure_refuses_process_creation(self):
        self.assert_setup_refused('label')


if __name__ == '__main__':
    unittest.main()
