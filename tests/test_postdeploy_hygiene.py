"""Offline regressions for post-deployment hygiene."""
import ast
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import assignments, consumer_claims, work_lock
from tests.test_import_guard import run_import_batch
from orchestrator.claude_event_consumer import ClaudeEventConsumer

ROOT = Path(__file__).resolve().parents[1]


class PostdeployTests(unittest.TestCase):
    def test_cognee_is_optional_and_never_imported(self):
        self.assertNotIn('cognee', (ROOT / 'requirements.txt').read_text().lower())
        self.assertIn('cognee==1.1.0', (ROOT / 'requirements-memory.txt').read_text())
        for folder in ('orchestrator', 'dispatch', 'scripts'):
            for path in (ROOT / folder).rglob('*.py'):
                tree = ast.parse(path.read_text(encoding='utf-8-sig'))
                for node in ast.walk(tree):
                    names = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                             else [node.module or ''] if isinstance(node, ast.ImportFrom) else [])
                    self.assertFalse(any(name.split('.')[0] == 'cognee' for name in names), str(path))

    def test_status_ignores_unowned_pokes_but_alerts_on_old_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            consumer = ClaudeEventConsumer(root)
            old = '2020-01-01T00:00:00+00:00'
            ignored = [dict(event=event, source=source, created_at=old) for event, source in (
                ('assignment_accepted', 'claude'), ('assignment_changes_requested', 'claude'),
                ('assignment_failed', 'composer'), ('assignment_completed', 'claude'))]
            with patch('orchestrator.claude_event_consumer.list_orchestrator_pokes', return_value=(ignored, [])):
                status = consumer._status()
            self.assertEqual(status['ignored_pending_poke_count'], 4)
            self.assertEqual(status['oldest_pending_poke_age_seconds'], 0)
            self.assertFalse(status['alert_active'])
            recent = dict(event='assignment_completed', source='composer', created_at=consumer.now().isoformat())
            with patch('orchestrator.claude_event_consumer.list_orchestrator_pokes', return_value=(ignored + [recent], [])):
                status = consumer._status()
            self.assertFalse(status['alert_active'])
            self.assertLess(status['oldest_pending_poke_age_seconds'], 10)
            eligible = dict(event='assignment_completed', source='composer', created_at=old)
            with patch('orchestrator.claude_event_consumer.list_orchestrator_pokes', return_value=(ignored + [eligible], [])):
                status = consumer._status()
            self.assertTrue(status['alert_active'])
            self.assertGreater(status['oldest_pending_poke_age_seconds'], 60)
            self.assertEqual(status['ignored_pending_poke_count'], 4)

    def test_cli_root_precedence_and_config_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            envroot, explicit, config = (base / name for name in ('state', 'explicit', 'config'))
            (envroot / 'runtime').mkdir(parents=True)
            explicit.mkdir()  # Explicit legacy roots need not already contain runtime/.
            for folder in ('agents', 'config'):
                (config / folder).mkdir(parents=True)
            for cli, arguments, target in (
                (assignments, ['pokes', '--json'], 'scripts.assignments.list_orchestrator_pokes'),
                (work_lock, ['status'], 'scripts.work_lock.work_lock.status'),
                (consumer_claims, ['list'], 'scripts.consumer_claims.list_records'),
            ):
                for choice, expected in ((None, ROOT), ('env', envroot), ('explicit', explicit)):
                    with self.subTest(cli=cli.__name__, choice=choice), patch.dict(os.environ, {}, clear=True):
                        os.environ['AGENTIC_OS_CONFIG_ROOT'] = str(config)
                        if choice:
                            os.environ['AGENTIC_OS_STATE_ROOT'] = str(envroot)
                        argv = (['--root', str(explicit)] if choice == 'explicit' else []) + arguments
                        captured = {}
                        def inspect_roots(*args, **kwargs):
                            captured.update(os.environ)
                            return ([], []) if cli is assignments else []
                        before = dict(os.environ)
                        with patch(target, side_effect=inspect_roots) as operation:
                            with contextlib.redirect_stdout(io.StringIO()), patch('sys.argv', ['cli'] + argv):
                                self.assertEqual(cli.main(), 0)
                        self.assertEqual(operation.call_args.args[0], expected.resolve())
                        self.assertEqual(captured['AGENTIC_OS_CONFIG_ROOT'], str(config.resolve()))
                        self.assertEqual(captured['AGENTIC_OS_STATE_ROOT'], str(expected.resolve()))
                        self.assertEqual(dict(os.environ), before)

    def test_cli_config_fallback_preserves_explicit_legacy_root(self):
        for cli, arguments, target in (
            (assignments, ['pokes', '--json'], 'scripts.assignments.list_orchestrator_pokes'),
            (work_lock, ['status'], 'scripts.work_lock.work_lock.status'),
            (consumer_claims, ['list'], 'scripts.consumer_claims.list_records'),
        ):
            for explicit in (False, True):
                with self.subTest(cli=cli.__name__, explicit=explicit), tempfile.TemporaryDirectory() as directory:
                    selected = Path(directory).resolve() if explicit else ROOT
                    argv = (['--root', str(selected)] if explicit else []) + arguments
                    captured = {}
                    def inspect_roots(*args, **kwargs):
                        from root_paths import resolve_config_root
                        captured['config'] = resolve_config_root(args[0])
                        return ([], []) if cli is assignments else []
                    with patch.dict(os.environ, {}, clear=True), patch(target, side_effect=inspect_roots):
                        with contextlib.redirect_stdout(io.StringIO()), patch('sys.argv', ['cli'] + argv):
                            self.assertEqual(cli.main(), 0)
                        self.assertEqual(captured['config'], selected)
                        self.assertNotIn('AGENTIC_OS_CONFIG_ROOT', os.environ)
                        self.assertNotIn('AGENTIC_OS_STATE_ROOT', os.environ)

    def test_batch_guard_reproduces_loaders_cycle_after_warm_import(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'orchestrator').mkdir()
            (root / 'dispatch').mkdir()
            (root / 'orchestrator/__init__.py').write_text('')
            (root / 'dispatch/__init__.py').write_text('')
            (root / 'orchestrator/loaders.py').write_text('from dispatch.channel import value\ndef load(): pass\n')
            (root / 'dispatch/channel.py').write_text('value = 1\nfrom orchestrator.loaders import load\n')
            result = run_import_batch(root, ['dispatch.channel', 'orchestrator.loaders', 'missing_module'])
            self.assertNotEqual(result.returncode, 0)
            failures = json.loads(result.stdout)
            self.assertNotIn('dispatch.channel', failures)
            self.assertIn('partially initialized', failures['orchestrator.loaders'])
            self.assertIn('missing_module', failures)
