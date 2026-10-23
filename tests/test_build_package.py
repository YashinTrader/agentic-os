"""Offline package lifecycle tests using real Windows PowerShell and temporary roots."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

WINDOWS = Path(__file__).resolve().parents[1] / 'packaging/windows'
sys.path.insert(0, str(WINDOWS))
spec = importlib.util.spec_from_file_location('package_builder', WINDOWS / 'build_package.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
sys.path.remove(str(WINDOWS))


@unittest.skipUnless(os.name == 'nt', 'Windows PowerShell lifecycle')
class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.runtime = self.root / 'runtime'
        (self.runtime / 'venv').mkdir(parents=True)
        (self.runtime / 'venv/pyvenv.cfg').write_text('home = old\ninclude-system-site-packages = false\n')
        normalized = b'home = ${RUNTIME}/cpython\ninclude-system-site-packages = false\n'
        (self.runtime / 'runtime-manifest.json').write_text(json.dumps({'pe_inventory': [], 'files': [
            {'path': 'venv/pyvenv.cfg', 'hash_encoding': 'runtime-path-template',
             'sha256': hashlib.sha256(normalized).hexdigest()}]}))
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode='w') as archive:
            for name, text in {'scripts/run_supervisor_layers.py': 'raise SystemExit(1)\n',
                               'scripts/stop_supervisor.py': 'raise SystemExit(0)\n'}.items():
                entry = tarfile.TarInfo(name)
                payload = text.encode()
                entry.size = len(payload)
                archive.addfile(entry, io.BytesIO(payload))
        self.archive = data.getvalue()
        self.package = self.make_package('1', 'one')
        self.apps = self.root / 'apps'
        self.state = self.root / 'state'
        self.projects = self.root / 'projects'

    def tearDown(self):
        # Restore owner access before TemporaryDirectory cleanup of immutable versions.
        if self.apps.exists():
            for path in self.apps.iterdir():
                if path.is_dir():
                    subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command',
                                    f". '{WINDOWS / 'Package-Common.ps1'}'; Set-AppAccess '{path}' $true"],
                                   capture_output=True)
        self.temp.cleanup()

    def make_package(self, version, name):
        def git(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, 'a' * 40 + '\n' if 'rev-parse' in command else self.archive)
        with patch.object(builder.subprocess, 'run', side_effect=git):
            path = builder.assemble(self.runtime, self.root, 'HEAD', version, self.root / name,
                                    verifier=lambda runtime: [])
        destination = self.root / (name + '-unpacked')
        with zipfile.ZipFile(path) as package:
            package.extractall(destination)
        return destination

    def ps(self, script, *args):
        return subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script),
                               *map(str, args)], capture_output=True, text=True, errors='replace')

    def install(self, package=None, *args):
        result = self.ps((package or self.package) / 'Install-AgenticOS.ps1', '-AppRoot', self.apps,
                         '-StateRoot', self.state, '-ProjectsRoot', self.projects, *args)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads((self.apps / 'current.json').read_text())

    def test_deterministic_zip_and_checksums(self):
        self.make_package('1', 'two')
        self.assertEqual((self.root / 'one/AgenticOS-1.zip').read_bytes(),
                         (self.root / 'two/AgenticOS-1.zip').read_bytes())
        self.assertEqual((self.root / 'one/SHA256SUMS').read_bytes(), (self.root / 'two/SHA256SUMS').read_bytes())
        checksum = (self.root / 'one/SHA256SUMS').read_text().split()[0]
        self.assertEqual(checksum, hashlib.sha256((self.root / 'one/AgenticOS-1.zip').read_bytes()).hexdigest())

    def test_tamper_refuses_before_activation(self):
        (self.package / 'code/scripts/stop_supervisor.py').write_text('tampered')
        result = self.ps(self.package / 'Install-AgenticOS.ps1', '-AppRoot', self.apps,
                         '-StateRoot', self.state, '-ProjectsRoot', self.projects)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('hash mismatch', result.stderr)
        self.assertFalse((self.apps / 'current.json').exists())

    def test_install_upgrade_rollback_and_prune(self):
        current = self.install()
        self.assertEqual(current['version'], '1')
        for name in ('runtime', 'tasks', 'logs'):
            self.assertTrue((self.state / name).is_dir())
        self.assertTrue(self.projects.is_dir())
        self.assertIsNone(current['task_name'])
        with self.assertRaises(PermissionError):
            (self.apps / '1/AgenticOS.cmd').write_text('should be read-only')
        cfg = (self.apps / '1/runtime/venv/pyvenv.cfg').read_text()
        self.assertIn(str(self.apps / '1/runtime/cpython'), cfg)
        two = self.make_package('2', 'two')
        self.install(two)
        self.assertTrue((self.apps / '1/install.json').exists())
        current = self.install(two, '-Rollback')
        self.assertEqual(current['version'], '1')
        current = self.install(self.make_package('3', 'three'))
        self.assertEqual(current['previous'], str(self.apps / '1'))
        self.assertFalse((self.apps / '2').exists())

    def test_uninstall_keeps_state_projects_and_reinstall(self):
        self.install()
        (self.state / 'keep').write_text('state')
        (self.projects / 'keep').write_text('project')
        result = self.ps(self.package / 'Uninstall-AgenticOS.ps1', '-AppRoot', self.apps)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.apps / 'current.json').exists())
        self.assertFalse((self.apps / '1').exists())
        self.assertEqual((self.state / 'keep').read_text(), 'state')
        self.assertEqual((self.projects / 'keep').read_text(), 'project')
        self.install()
        result = self.ps(self.package / 'Uninstall-AgenticOS.ps1', '-AppRoot', self.apps,
                         '-RemoveState', '-RemoveProjects')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.state.exists())
        self.assertFalse(self.projects.exists())

    def test_protected_and_nested_paths_refused(self):
        for state in ('C:/Users/gabot/agentic-os', 'C:/Users/gabot/agentic-os-deploy/unsafe', str(self.apps / 'state')):
            result = self.ps(self.package / 'Install-AgenticOS.ps1', '-AppRoot', self.apps,
                             '-StateRoot', state, '-ProjectsRoot', self.projects)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((self.apps / 'current.json').exists())

    def test_launcher_crash_guard_and_status(self):
        self.install()
        launcher = self.apps / '1/Launch-AgenticOS.ps1'
        fake_python = self.root / 'fake-python.cmd'
        fake_python.write_bytes(b'@echo off\r\nexit /b 1\r\n')
        for _ in range(3):
            result = self.ps(launcher, '-PythonExecutable', fake_python)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        result = self.ps(launcher, '-PythonExecutable', fake_python)
        self.assertEqual(result.returncode, 78, result.stdout + result.stderr)
        self.assertIn('Inspect', result.stdout)
        self.assertEqual(len(json.loads((self.state / 'launcher_crashes.json').read_text())['crashes']), 3)
        result = subprocess.run([str(self.apps / '1/AgenticOS.cmd'), 'status'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('has not started', result.stdout)
        (self.state / 'launcher_crashes.json').write_text(json.dumps({'crashes': [0, 0, 0]}))
        result = self.ps(launcher, '-PythonExecutable', fake_python)
        self.assertEqual(result.returncode, 1)


if __name__ == '__main__':
    unittest.main()
