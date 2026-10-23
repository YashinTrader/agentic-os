"""Offline Windows runtime assembly. See README.md for the trust boundary."""
from __future__ import annotations

import argparse
import base64
import csv
from datetime import datetime, timezone
import fnmatch
import hashlib
from importlib.metadata import distributions
import json
from pathlib import Path, PureWindowsPath
import re
import shutil
import subprocess
import sys

DEFAULT_EXCLUDES = ('*/__pycache__/*', '*.pyc', '../*')
PE_SUFFIXES = {'.exe', '.dll', '.pyd'}


class BuildError(ValueError):
    pass


def run(command):
    return subprocess.run(command, check=True, capture_output=True, text=True,
                          encoding='utf-8', errors='replace')


def signature(path):
    literal = str(path).replace("'", "''")
    script = ("$s=Get-AuthenticodeSignature -LiteralPath '" + literal + "'; "
              "@{status=$s.Status.ToString();subject=$s.SignerCertificate.Subject}"
              " | ConvertTo-Json -Compress")
    return json.loads(run(['powershell', '-NoProfile', '-NonInteractive',
                          '-Command', script]).stdout.lstrip('\ufeff'))


def signature_batch(paths):
    """One PowerShell process per inventory; no stale cross-build trust cache."""
    if not paths:
        return {}
    script = ("$paths=([Console]::In.ReadToEnd() | ConvertFrom-Json); "
              "@($paths | ForEach-Object { $s=Get-AuthenticodeSignature -LiteralPath $_; "
              "@{path=$_;status=$s.Status.ToString();subject=$s.SignerCertificate.Subject} }) "
              "| ConvertTo-Json -Compress")
    result = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', script],
                            input=json.dumps([str(p) for p in paths]), check=True,
                            capture_output=True, text=True, encoding='utf-8', errors='replace')
    entries = json.loads(result.stdout.lstrip('\ufeff'))
    if isinstance(entries, dict):
        entries = [entries]
    return {entry['path']: {k: entry[k] for k in ('status', 'subject')} for entry in entries}


def normalize(name):
    return re.sub(r'[-_.]+', '-', name).lower()


def matches(path, patterns):
    return any(fnmatch.fnmatchcase(path.lower(), p.lower()) for p in patterns)


def safe_path(root, relative):
    windows = PureWindowsPath(relative)
    if windows.is_absolute() or windows.drive or '..' in windows.parts or ':' in relative:
        raise BuildError(f'unsafe path: {relative}')
    result = root.joinpath(*windows.parts)
    if not result.resolve().is_relative_to(root.resolve()):
        raise BuildError(f'path escapes root: {relative}')
    return result


def marker_evaluator(site):
    """Use source packaging in isolation; otherwise conservatively include all markers.

    Fallback can over-include optional dependencies and fail if they are missing;
    it never silently drops an unknown condition. With packaging, extra='' skips
    extras while preserving non-extra branches of compound predicates.
    """
    script = ("import sys,json;sys.path.insert(0,sys.argv[1]);"
              "from packaging.markers import Marker,default_environment;"
              "e=default_environment();e.update(json.loads(sys.argv[2]));"
              "print(json.dumps([Marker(m).evaluate(e) for m in json.loads(sys.argv[3])]))")

    def evaluate(markers, environment):
        if not markers:
            return []
        try:
            return json.loads(run([sys.executable, '-I', '-B', '-c', script, str(site),
                                   json.dumps(environment), json.dumps(markers)]).stdout)
        except subprocess.CalledProcessError as exc:
            if 'No module named' in (exc.stderr or '') and 'packaging' in exc.stderr:
                return [True] * len(markers)
            raise BuildError(f'cannot evaluate dependency markers: {exc.stderr}') from exc
    return evaluate


def closure(site, roots, environment, evaluate=None):
    installed = {}
    for dist in distributions(path=[str(site)]):
        name = normalize(dist.metadata['Name'])
        if name in installed:
            raise BuildError(f'duplicate distribution: {name}')
        installed[name] = dist
    evaluate = evaluate or marker_evaluator(site)
    selected, pending = {}, list(roots)
    while pending:
        name = normalize(pending.pop())
        if name in selected:
            continue
        if name not in installed:
            raise BuildError(f'missing distribution: {name}')
        dist = selected[name] = installed[name]
        requirements = []
        for requirement in dist.requires or []:
            spec, _, marker = requirement.partition(';')
            match = re.match(r'^\s*([A-Za-z0-9][A-Za-z0-9._-]*)', spec)
            if not match:
                raise BuildError(f'invalid Requires-Dist: {requirement}')
            requirements.append((match[1], marker.strip()))
        decisions = iter(evaluate([m for _, m in requirements if m], environment))
        for dependency, marker in requirements:
            if not marker or next(decisions):
                pending.append(dependency)
    return [selected[name] for name in sorted(selected)]


def copy_distributions(site, destination, selected, excludes):
    origins, verified, info = {}, {}, []
    for dist in selected:
        name = dist.metadata['Name']
        record = dist.read_text('RECORD')
        if record is None:
            raise BuildError(f'{name}: missing RECORD')
        tags = sorted(line[5:].strip() for line in (dist.read_text('WHEEL') or '').splitlines()
                      if line.startswith('Tag:'))
        info.append({'name': name, 'version': dist.version, 'wheel_tags': tags})
        for row in csv.reader(record.splitlines()):
            if not row:
                continue
            relative = row[0].replace('\\', '/')
            if matches(relative, excludes):
                continue
            source, target = safe_path(site, relative), safe_path(destination, relative)
            if not source.is_file():
                raise BuildError(f'{name}: missing file {relative}')
            data = source.read_bytes()
            digest = row[1] if len(row) > 1 else ''
            if digest:
                algorithm, expected = digest.split('=', 1)
                actual = base64.urlsafe_b64encode(hashlib.new(algorithm, data).digest()).decode().rstrip('=')
                if actual != expected:
                    raise BuildError(f'{name}: hash mismatch {relative}')
            if len(row) > 2 and row[2] and int(row[2]) != len(data):
                raise BuildError(f'{name}: size mismatch {relative}')
            if target.exists() and target.read_bytes() != data:
                raise BuildError(f'conflicting RECORD ownership: {relative}')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            origins.setdefault(relative, set()).add(name)
            verified[relative] = verified.get(relative, True) and bool(digest)
    return origins, verified, sorted(info, key=lambda d: normalize(d['name']))


def import_names(selected):
    names = set()
    for dist in selected:
        declared = dist.read_text('top_level.txt')
        if declared:
            names.update(line.strip() for line in declared.splitlines() if line.strip())
            continue
        for entry in dist.files or []:
            parts = str(entry).replace('\\', '/').split('/')
            first = parts[0]
            if first.endswith(('.dist-info', '.data')) or first.startswith('.'):
                continue
            if len(parts) > 1 or first.endswith(('.py', '.pyd')):
                names.add(first.split('.')[0])
    if not names or any(not name.isidentifier() for name in names):
        raise BuildError(f'invalid or unavailable top-level import names: {sorted(names)}')
    return sorted(names)


def file_digest(path, root):
    data, encoding = path.read_bytes(), 'bytes'
    if path == root / 'venv' / 'pyvenv.cfg':
        prefix = f"home = {root / 'cpython'}\n".encode('utf-8')
        if data.startswith(prefix):
            data = b'home = ${RUNTIME}/cpython\n' + data[len(prefix):]
        encoding = 'runtime-path-template'
    return hashlib.sha256(data).hexdigest(), encoding


def inventory(root, origins, verified, checker):
    files, pe = [], []
    if checker is signature:
        statuses = signature_batch(sorted(p for p in root.rglob('*') if p.is_file() and p.suffix.lower() in PE_SUFFIXES))
        checker = lambda path: statuses[str(path)]
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise BuildError(f'symlink not permitted in runtime: {path}')
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative in {'runtime-manifest.json', 'build-info.json'}:
            continue
        vendor = relative.removeprefix('venv/Lib/site-packages/')
        origin = ','.join(sorted(origins.get(vendor, {'cpython'})))
        digest, encoding = file_digest(path, root)
        files.append({'path': relative, 'sha256': digest, 'hash_encoding': encoding,
                      'verified': verified.get(vendor, False), 'origin': origin})
        if path.suffix.lower() in PE_SUFFIXES:
            pe.append({'path': relative, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                       'size': path.stat().st_size, 'origin': origin, **checker(path)})
    return files, pe


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n', encoding='utf-8', newline='\n')


def build(python_home, site, requirements, out, allow_unsigned=(), excludes=(),
          checker=signature, runner=run, evaluate=None):
    python_home, site, out = (Path(p).resolve() for p in (python_home, site, out))
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise BuildError(f'output must be new or empty: {out}')
    if out.is_relative_to(python_home) or out.is_relative_to(site):
        raise BuildError('output must be outside both input directories')
    signed = checker(python_home / 'python.exe')
    if signed['status'] != 'Valid' or not re.search(r'(?:^|,\s*)O=Python Software Foundation(?:,|$)', signed.get('subject') or ''):
        raise BuildError(f'python.exe must have a valid Python Software Foundation signature: {signed}')
    roots = sorted(set(line.split('#', 1)[0].strip() for line in Path(requirements).read_text(encoding='utf-8-sig').splitlines()) - {''})
    if not roots or any(not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', name) for name in roots):
        raise BuildError('requirements must contain one bare distribution name per line')
    probe = ("import json,sys,os,platform;print(json.dumps(dict(python_version=platform.python_version(),"
             "python_full_version=platform.python_version(),sys_platform=sys.platform,os_name=os.name,"
             "platform_machine=platform.machine(),platform_system=platform.system(),"
             "platform_release=platform.release(),platform_version=platform.version(),"
             "platform_python_implementation=platform.python_implementation(),implementation_name=sys.implementation.name,"
             "implementation_version=platform.python_version(),extra='')))")
    environment = json.loads(runner([str(python_home / 'python.exe'), '-I', '-c', probe]).stdout)
    environment['python_version'] = '.'.join(environment['python_full_version'].split('.')[:2])
    selected = closure(site, roots, environment, evaluate)
    out.mkdir(parents=True, exist_ok=True)
    excludes = tuple(sorted(set(DEFAULT_EXCLUDES + tuple(excludes))))
    def ignore(directory, names):
        return [name for name in names if name in {'site-packages', '__pycache__', 'ensurepip'}
                or name.endswith('.pyc')
                or matches('cpython/' + (Path(directory) / name).relative_to(python_home).as_posix(), excludes)]
    shutil.copytree(python_home, out / 'cpython', ignore=ignore)
    runner([str(python_home / 'python.exe'), '-I', '-m', 'venv', '--without-pip', str(out / 'venv')])
    scripts = out / 'venv' / 'Scripts'
    for path in scripts.iterdir():
        if path.suffix.lower() != '.exe':
            path.unlink()
    cfg = f"home = {out / 'cpython'}\ninclude-system-site-packages = false\nversion = {environment['python_full_version']}\n"
    (out / 'venv' / 'pyvenv.cfg').write_text(cfg, encoding='utf-8', newline='\n')
    origins, verified, dists = copy_distributions(site, out / 'venv/Lib/site-packages', selected, excludes)
    files, pe = inventory(out, origins, verified, checker)
    rejected = [entry['path'] for entry in pe if entry['status'] != 'Valid'
                and not (entry['status'] == 'NotSigned' and matches(entry['path'], allow_unsigned))]
    if rejected:
        raise BuildError('untrusted PE files (only NotSigned can be allowed); exact allow globs:\n' +
                         '\n'.join(f'--allow-unsigned "{path}"' for path in rejected))
    root_dists = [dist for dist in selected if normalize(dist.metadata['Name']) in {normalize(r) for r in roots}]
    imports = import_names(root_dists)
    try:
        runner([str(scripts / 'python.exe'), '-I', '-B', '-c', ';'.join('import ' + name for name in imports)])
    except subprocess.CalledProcessError as exc:
        write_json(out / 'build-info.json', {'smoke': {'returncode': exc.returncode, 'stderr': exc.stderr}})
        raise BuildError(f'smoke import failed: {exc.stderr}') from exc
    manifest = {'schema_version': 1, 'python_version': environment['python_full_version'],
                'python_home': str(python_home), 'dists': dists, 'files': files, 'pe_inventory': pe,
                'inputs': {'requirements': roots, 'excludes': list(excludes),
                           'allow_unsigned': sorted(set(allow_unsigned))},
                'smoke': {'imports': imports, 'returncode': 0}}
    write_json(out / 'runtime-manifest.json', manifest)
    write_json(out / 'build-info.json', {'built_at': datetime.now(timezone.utc).isoformat(), 'runtime': str(out)})
    return manifest


def verify(runtime, checker=signature):
    root = Path(runtime).resolve()
    manifest = json.loads((root / 'runtime-manifest.json').read_text(encoding='utf-8'))
    differences = []
    if checker is signature:
        statuses = signature_batch([safe_path(root, e['path']) for e in manifest['pe_inventory'] if safe_path(root, e['path']).is_file()])
        checker = lambda path: statuses[str(path)]
    expected = {entry['path'] for entry in manifest['files']}
    for entry in manifest['files']:
        path = safe_path(root, entry['path'])
        if not path.is_file():
            differences.append(f"missing: {entry['path']}")
        elif path.is_symlink() or file_digest(path, root) != (entry['sha256'], entry['hash_encoding']):
            differences.append(f"hash changed: {entry['path']}")
    for entry in manifest['pe_inventory']:
        path = safe_path(root, entry['path'])
        if path.is_file():
            current = checker(path)
            if any(current.get(key) != entry.get(key) for key in ('status', 'subject')):
                differences.append(f"signature changed: {entry['path']}")
    for path in root.rglob('*'):
        relative = path.relative_to(root).as_posix()
        if path.is_file() and relative not in expected | {'runtime-manifest.json', 'build-info.json'}:
            differences.append(f'added: {relative}')
    return sorted(differences)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    assemble = commands.add_parser('build')
    for argument in ('python-home', 'site-packages', 'requirements', 'out'):
        assemble.add_argument('--' + argument, required=True, type=Path)
    assemble.add_argument('--allow-unsigned', action='append', default=[])
    assemble.add_argument('--exclude', action='append', default=[])
    check = commands.add_parser('verify')
    check.add_argument('--runtime', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'verify':
            differences = verify(args.runtime)
            print('\n'.join(differences) if differences else 'Runtime verified')
            return int(bool(differences))
        build(args.python_home, args.site_packages, args.requirements, args.out,
              args.allow_unsigned, args.exclude)
        print(f'Runtime built: {args.out}')
        return 0
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
