"""Offline tests: fake distributions, processes, and Authenticode results."""
import base64
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / 'packaging/windows/build_runtime.py'
spec = importlib.util.spec_from_file_location('runtime_builder', MODULE)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
SIGNED = {'status': 'Valid', 'subject': 'CN=Python Software Foundation, O=Python Software Foundation, C=US'}


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.site = self.root / 'site'
        self.site.mkdir()
        self.home = self.root / 'python'
        self.home.mkdir()
        (self.home / 'python.exe').write_bytes(b'MZsigned')
        self.requirements = self.root / 'requirements.txt'
        self.requirements.write_text('demo\n')
        self.dist('demo')

    def dist(self, name, requires=(), files=None):
        metadata = self.site / (name + '-1.0.dist-info')
        metadata.mkdir(exist_ok=True)
        (metadata / 'METADATA').write_text('Metadata-Version: 2.1\nName: ' + name + '\nVersion: 1.0\n' + ''.join('Requires-Dist: ' + r + '\n' for r in requires))
        (metadata / 'WHEEL').write_text('Tag: py3-none-any\n')
        (metadata / 'top_level.txt').write_text(name + '\n')
        payload = {name + '/__init__.py': b'', **(files or {})}
        for path in list(metadata.iterdir()):
            if path.name == 'RECORD':
                continue
            payload[path.relative_to(self.site).as_posix()] = path.read_bytes()
        rows = []
        for relative, data in payload.items():
            path = self.site / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip('=')
            rows.append([relative, 'sha256=' + digest, str(len(data))])
        rows.append([metadata.name + '/RECORD', '', ''])
        with (metadata / 'RECORD').open('w', newline='') as stream:
            csv.writer(stream).writerows(rows)

    def runner(self, command):
        if '-m' in command:
            target = Path(command[-1]) / 'Scripts'
            target.mkdir(parents=True)
            (target / 'python.exe').write_bytes(b'MZlauncher')
            return subprocess.CompletedProcess(command, 0, '')
        if 'python_full_version' in command[-1]:
            return subprocess.CompletedProcess(command, 0, json.dumps({'python_full_version': '3.11.9', 'sys_platform': 'win32', 'extra': ''}))
        return subprocess.CompletedProcess(command, 0, '')

    def checker(self, path):
        return {'status': 'NotSigned', 'subject': None} if path.suffix == '.pyd' else dict(SIGNED)

    def build(self, name='out', **kwargs):
        return builder.build(self.home, self.site, self.requirements, self.root / name,
                             checker=self.checker, runner=self.runner, **kwargs)

    def test_closure_missing_markers_and_extras(self):
        self.dist('demo', ['dep>=1', 'absent; sys_platform == "linux"', 'optional; extra == "test"'])
        self.dist('dep')
        seen = []
        def evaluate(markers, env):
            seen.extend(markers)
            return [False] * len(markers)
        result = builder.closure(self.site, ['DEMO'], {'extra': ''}, evaluate)
        self.assertEqual([d.metadata['Name'] for d in result], ['demo', 'dep'])
        self.assertEqual(len(seen), 2)
        with self.assertRaisesRegex(builder.BuildError, 'missing distribution'):
            builder.closure(self.site, ['missing'], {}, evaluate)

    def test_source_packaging_markers_and_conservative_fallback(self):
        # Fake source package implements the small interface; no external imports/network.
        package = self.site / 'packaging'
        package.mkdir()
        (package / '__init__.py').write_text('')
        (package / 'markers.py').write_text('class Marker:\n def __init__(self, text): self.text=text\n def evaluate(self, env): return eval(self.text, {}, env)\ndef default_environment(): return {}\n')
        evaluate = builder.marker_evaluator(self.site)
        self.assertEqual(evaluate(['sys_platform == "win32"', 'extra == "test"'], {'sys_platform': 'win32', 'extra': ''}), [True, False])
        with patch.object(builder, 'run', side_effect=subprocess.CalledProcessError(1, [], stderr="ModuleNotFoundError: No module named 'packaging'")):
            self.assertEqual(evaluate(['unknown'], {}), [True])

    def test_record_hash_mismatch_and_missing(self):
        (self.site / 'demo/__init__.py').write_bytes(b'changed')
        with self.assertRaisesRegex(builder.BuildError, 'hash mismatch'):
            self.build()
        (self.site / 'demo/__init__.py').unlink()
        with self.assertRaisesRegex(builder.BuildError, 'missing file'):
            self.build('missing')

    def test_exclusions_and_unsafe_paths(self):
        self.dist('demo', files={'demo/omit.txt': b'a', 'demo/__pycache__/bad.pyc': b'b'})
        (self.site / 'demo/omit.txt').write_bytes(b'tampered')
        manifest = self.build(excludes=['*/omit.txt'])
        self.assertFalse(any('omit' in f['path'] or '.pyc' in f['path'] for f in manifest['files']))
        with self.assertRaisesRegex(builder.BuildError, 'unsafe path'):
            builder.safe_path(self.site, '../escape')

    def test_base_interpreter_exclusion(self):
        (self.home / 'optional.dll').write_bytes(b'MZoptional')
        manifest = self.build(excludes=['cpython/optional.dll'])
        self.assertFalse(any(f['path'] == 'cpython/optional.dll' for f in manifest['files']))

    def test_unsigned_pe_allowlist(self):
        self.dist('demo', files={'demo/native.pyd': b'MZnative'})
        with self.assertRaisesRegex(builder.BuildError, 'demo/native.pyd'):
            self.build('denied')
        manifest = self.build('allowed', allow_unsigned=['venv/Lib/site-packages/demo/*.pyd'])
        native = [p for p in manifest['pe_inventory'] if p['path'].endswith('.pyd')]
        self.assertEqual(native[0]['origin'], 'demo')
        self.assertEqual(native[0]['status'], 'NotSigned')

    def test_manifest_determinism_and_verify(self):
        self.build('one')
        self.build('two')
        self.assertEqual((self.root / 'one/runtime-manifest.json').read_bytes(), (self.root / 'two/runtime-manifest.json').read_bytes())
        self.assertEqual(builder.verify(self.root / 'one', self.checker), [])
        (self.root / 'one/venv/Lib/site-packages/demo/__init__.py').write_bytes(b'changed')
        self.assertIn('hash changed: venv/Lib/site-packages/demo/__init__.py', builder.verify(self.root / 'one', self.checker))

    def test_config_tampering_is_detected(self):
        self.build()
        cfg = self.root / 'out/venv/pyvenv.cfg'
        cfg.write_text(cfg.read_text().replace(str(self.root / 'out'), '${RUNTIME}'))
        self.assertIn('hash changed: venv/pyvenv.cfg', builder.verify(self.root / 'out', self.checker))

    def test_smoke_failure_is_recorded(self):
        def runner(command):
            if command[-1] == 'import demo':
                raise subprocess.CalledProcessError(7, command, stderr='broken import')
            return self.runner(command)
        with self.assertRaisesRegex(builder.BuildError, 'smoke import failed'):
            builder.build(self.home, self.site, self.requirements, self.root / 'bad-smoke', checker=self.checker, runner=runner)
        self.assertEqual(json.loads((self.root / 'bad-smoke/build-info.json').read_text())['smoke']['returncode'], 7)
        self.assertFalse((self.root / 'bad-smoke/runtime-manifest.json').exists())

    def test_signer_change_and_added_file(self):
        self.build()
        (self.root / 'out/extra.dll').write_bytes(b'MZ')
        changes = builder.verify(self.root / 'out', lambda p: {'status': 'NotSigned', 'subject': None})
        self.assertIn('added: extra.dll', changes)
        self.assertTrue(any('signature changed' in c for c in changes))

    def test_nonempty_output_and_invalid_interpreter(self):
        output = self.root / 'occupied'
        output.mkdir()
        (output / 'keep').write_text('keep')
        with self.assertRaisesRegex(builder.BuildError, 'new or empty'):
            self.build('occupied')
        with self.assertRaisesRegex(builder.BuildError, 'Foundation signature'):
            builder.build(self.home, self.site, self.requirements, self.root / 'invalid', checker=lambda p: {'status': 'Valid', 'subject': 'O=Other'})

    def test_invalid_signature_cannot_be_allowed(self):
        self.dist('demo', files={'demo/native.pyd': b'MZ'})
        def checker(path):
            return {'status': 'HashMismatch', 'subject': None} if path.suffix == '.pyd' else SIGNED
        with self.assertRaisesRegex(builder.BuildError, 'untrusted PE'):
            builder.build(self.home, self.site, self.requirements, self.root / 'out', allow_unsigned=['*'], checker=checker, runner=self.runner)


if __name__ == '__main__':
    unittest.main()
