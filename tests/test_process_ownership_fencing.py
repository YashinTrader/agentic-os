import ast
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, Mock

from dispatch import work_lock
from dispatch.assignment_channel import write_assignment, claim_assignment, complete_assignment, write_outbox_result
from dispatch.orchestrator_pokes import list_orchestrator_pokes
from orchestrator.event_router import route_completion
from orchestrator.runtime_store import RunState
from orchestrator.process_ownership import owned_popen, terminate_owned, process_start_time, pid_is_alive, ProcessOwner


class ProcessOwnershipTests(unittest.TestCase):
    def test_real_grandchild_terminated(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / 'grandchild.json'
            code = ('import subprocess,sys,time,json; from pathlib import Path; '
                    'p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(120)"]); '
                    f'Path({str(marker)!r}).write_text(json.dumps(p.pid)); time.sleep(120)')
            proc = owned_popen([sys.executable, '-c', code],
                               popen=lambda *args, **kwargs: subprocess.Popen(*args, **kwargs), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                deadline = time.monotonic() + 15
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(.05)
                self.assertTrue(marker.exists(), 'child never wrote grandchild PID')
                grandchild = json.loads(marker.read_text())
                start = process_start_time(grandchild)
                self.assertTrue(start)
                self.assertTrue(terminate_owned(proc))
                proc.wait(timeout=5)
                deadline = time.monotonic() + 5
                while pid_is_alive(grandchild, start) and time.monotonic() < deadline:
                    time.sleep(.05)
                self.assertFalse(pid_is_alive(grandchild, start))
            finally:
                terminate_owned(proc)
                proc.wait(timeout=5)

    def test_reused_pid_is_gone_and_never_signaled(self):
        proc = Mock()
        proc._agentic_owner = ProcessOwner(123, 'old', 'pgid:123')
        with patch('orchestrator.process_ownership.process_start_time', return_value='new'), \
             patch('orchestrator.process_ownership.os.killpg', create=True) as signal_group:
            self.assertFalse(pid_is_alive(123, 'old'))
            self.assertFalse(terminate_owned(proc))
            signal_group.assert_not_called()
            proc.kill.assert_not_called()

    def test_inventory_records_are_immutable_and_detached(self):
        from dataclasses import FrozenInstanceError
        from orchestrator.process_inventory import legacy_process_inventory
        args = ['python', 'run_orchestrator.py', '--root', '.']
        process = Mock(pid=123, info={'name': 'python'})
        process.cmdline.return_value = args
        process.create_time.return_value = 12.5
        process.cwd.return_value = str(Path.cwd())
        process.environ.return_value = {'AGENTIC_OS_STATE_ROOT': 'state'}
        with patch('psutil.process_iter', return_value=[process]):
            records = legacy_process_inventory()
        self.assertIsInstance(records, tuple)
        record = records[0]
        self.assertEqual((record.pid, record.start_time, record.state_root_evidence),
                         (123, 12.5, 'state'))
        args.append('changed')
        self.assertNotIn('changed', record.command_line)
        with self.assertRaises(FrozenInstanceError):
            record.pid = 456

    def test_inventory_unreadable_candidates_fail_closed(self):
        import psutil
        from orchestrator.process_inventory import legacy_process_inventory
        process = Mock(pid=123, info={'name': 'python'})
        process.cmdline.side_effect = psutil.AccessDenied(123)
        with patch('psutil.process_iter', return_value=[process]):
            with self.assertRaises(ValueError):
                legacy_process_inventory()
        process.cmdline.side_effect = None
        process.cmdline.return_value = ['python', 'run_orchestrator.py']
        process.create_time.side_effect = psutil.AccessDenied(123)
        with patch('psutil.process_iter', return_value=[process]):
            with self.assertRaises(ValueError):
                legacy_process_inventory()
        process.create_time.side_effect = psutil.NoSuchProcess(123)
        with patch('psutil.process_iter', return_value=[process]):
            self.assertEqual(legacy_process_inventory(), ())

    def test_no_name_based_kills(self):
        root = Path(__file__).resolve().parents[1]
        forbidden = re.compile(r'taskkill[^\r\n]*?/im\b|Stop-Process[^\r\n]*?-Name\b', re.I)
        inventory = root / 'orchestrator/process_inventory.py'
        enumeration = re.compile(
            r'\b(?:process_iter|pids|EnumProcesses|CreateToolhelp32Snapshot|Process32FirstW?|'
            r'Process32NextW?|NtQuerySystemInformation)\s*\(|'
            r'Get-Process\b|Win32_Process\b|\btasklist\b', re.I)
        for path in root.rglob('*.py'):
            if any(part.startswith('.') for part in path.relative_to(root).parts):
                continue
            tree = ast.parse(path.read_text(encoding='utf-8-sig'))
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    names = [alias.name for alias in node.names]
                    module = getattr(node, 'module', '') or ''
                    if 'process_inventory' in module or any('process_inventory' in n for n in names):
                        self.assertTrue(path == root / 'orchestrator/supervisor_control.py'
                                        or path.is_relative_to(root / 'tests'), str(path))
                        if path == root / 'orchestrator/supervisor_control.py':
                            legacy = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                                          and n.name == 'legacy_process_blockers')
                            self.assertIn(node, list(ast.walk(legacy)))
        dangerous = re.compile(
            r'\b(?:terminate|kill|killpg|send_signal|TerminateProcess|TerminateJobObject)\s*\('
            r'|\btaskkill\b|Stop-Process\b', re.I)
        self.assertIsNone(dangerous.search(inventory.read_text(encoding='utf-8')))
        for directory in ('orchestrator', 'dispatch', 'scripts'):
            for path in (root / directory).rglob('*'):
                if path.suffix in {'.py', '.ps1', '.sh', '.cmd', '.bat'}:
                    source = path.read_text(encoding='utf-8')
                    self.assertIsNone(forbidden.search(source), str(path))
                    if path != inventory:
                        self.assertIsNone(enumeration.search(source), str(path))


class CompletionFenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        _, errors = write_assignment(self.root, assignment_id='a1', task_id='T-FENCE',
                                     title='Fencing', goal='Fencing', base_branch='main',
                                     base_sha='a'*40, new_branch='agent/test',
                                     allowed_paths=['docs/**'], acceptance_criteria=['safe'],
                                     verification_commands=['python scripts/validate.py'])
        self.assertEqual(errors, [])
        _, errors = claim_assignment(self.root, 'a1', sync_task_yaml=False)
        self.assertEqual(errors, [])
        record = work_lock.status(self.root, 'T-FENCE')[0]
        work_lock.acquire(self.root, 'T-FENCE', holder_agent=record['holder_agent'],
                          route='test', assignment_id='a1', run_id='old', resume=True)
        self.state = RunState('old', 'a1', 'T-FENCE', 'composer', 'composer-restricted',
                              logical_task_id='T-FENCE', process_state='completed',
                              worktree='preserved-worktree', branch='preserved-branch')

    def supersede(self):
        work_lock.supersede(self.root, 'T-FENCE', actor='claude', reason='replacement',
                            holder_agent='codex', route='test', assignment_id='a1', run_id='new')

    def test_superseded_completion_is_fenced_every_entry(self):
        self.supersede()
        lock_before = work_lock.lock_path(self.root, 'T-FENCE').read_bytes()
        inbox = self.root / 'runtime/dispatch/assignments/inbox/a1.json'
        before = inbox.read_bytes()
        outbox = self.root / 'runtime/dispatch/assignments/outbox/a1.json'
        outbox.parent.mkdir(parents=True, exist_ok=True)
        outbox.write_text('{"evidence":"existing"}')
        for status in ('completed', 'failed', 'blocked_external'):
            self.state.process_state = status
            result, errors = route_completion(self.root, self.state)
            self.assertEqual(result['process_state'], 'fenced')
            self.assertTrue(errors)
        out, errors = complete_assignment(self.root, 'a1', run_id='old', sync_task_yaml=False)
        self.assertIsNone(out)
        self.assertIn('fenced', errors[0])
        out, errors = write_outbox_result(self.root, assignment_id='a1', task_id='T-FENCE', run_id='old')
        self.assertIsNone(out)
        # A missing run id cannot bypass a running holder either.
        self.assertIsNone(complete_assignment(self.root, 'a1')[0])
        self.assertEqual(lock_before, work_lock.lock_path(self.root, 'T-FENCE').read_bytes())
        self.assertEqual(before, inbox.read_bytes())
        self.assertEqual(outbox.read_text(), '{"evidence":"existing"}')
        self.assertEqual(list_orchestrator_pokes(self.root)[0], [])
        audits = list((self.root / 'runtime/dispatch/fenced').glob('*.json'))
        self.assertEqual(len(audits), 6)
        self.assertIn('preserved-worktree', audits[0].read_text() + ''.join(p.read_text() for p in audits))

    def test_holder_completes_normally(self):
        out, errors = complete_assignment(self.root, 'a1', run_id='old', sync_task_yaml=False)
        self.assertEqual(errors, [])
        self.assertEqual(out.run_id, 'old')
        self.assertEqual(out.status, 'awaiting_review')
        self.assertEqual(work_lock.status(self.root, 'T-FENCE')[0]['run_id'], 'old')

    def test_holder_routes_normally(self):
        result, errors = route_completion(self.root, self.state)
        self.assertEqual(result['outbox_status'], 'awaiting_review')
        self.assertFalse(any('fenced' in error for error in errors))
        self.assertEqual(len(list_orchestrator_pokes(self.root)[0]), 1)

    def test_stale_runtime_outcome_is_audited(self):
        from orchestrator.runtime_store import save_run_state
        self.supersede()
        with self.assertRaises(work_lock.WorkLockError):
            save_run_state(self.root, self.state)
        audits = list((self.root / 'runtime/dispatch/fenced').glob('*.json'))
        self.assertEqual(json.loads(audits[0].read_text())['status'], 'fenced')
        self.assertEqual(work_lock.status(self.root, 'T-FENCE')[0]['run_id'], 'new')

    def test_supersede_cannot_race_outbox_and_poke_transaction(self):
        import threading
        from dispatch.atomic_io import atomic_write_json
        attempts = []
        def transfer():
            try:
                self.supersede()
                attempts.append('transferred')
            except work_lock.WorkLockError:
                attempts.append('busy')
        def write(path, payload):
            if path.parent.name == 'outbox':
                worker = threading.Thread(target=transfer)
                worker.start()
                worker.join(timeout=5)
                self.assertFalse(worker.is_alive())
            atomic_write_json(path, payload)
        with patch('dispatch.assignment_channel.atomic_write_json', side_effect=write):
            out, errors = complete_assignment(self.root, 'a1', run_id='old', sync_task_yaml=False)
        self.assertEqual(errors, [])
        self.assertIsNotNone(out)
        self.assertEqual(attempts, ['busy'])
        self.assertEqual(work_lock.status(self.root, 'T-FENCE')[0]['run_id'], 'old')

    def test_same_run_release_allowed_but_older_release_is_not(self):
        work_lock.release(self.root, 'T-FENCE', actor='composer', reason='finished', run_id='old')
        self.assertIsNotNone(complete_assignment(self.root, 'a1', run_id='old', sync_task_yaml=False)[0])
        work_lock.acquire(self.root, 'T-FENCE', holder_agent='codex', route='test', assignment_id='a1', run_id='new')
        work_lock.release(self.root, 'T-FENCE', actor='codex', reason='finished', run_id='new')
        self.assertIsNone(complete_assignment(self.root, 'a1', run_id='old', sync_task_yaml=False)[0])
