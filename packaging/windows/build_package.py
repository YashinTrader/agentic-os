"""Assemble a deterministic offline, per-user Windows installation ZIP."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import zipfile

import build_runtime


def digest(data):
    return hashlib.sha256(data).hexdigest()


def assemble(runtime, repo, sha, version, out, *, verifier=build_runtime.verify):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}', version) or version.endswith('.'):
        raise ValueError('version must be a safe directory name')
    runtime, repo, out = Path(runtime), Path(repo), Path(out)
    differences = verifier(runtime)
    if differences:
        raise ValueError('runtime verification failed: ' + '; '.join(differences))
    revision = subprocess.run(['git', '-C', str(repo), 'rev-parse', '--verify', sha + '^{commit}'],
                              check=True, capture_output=True, text=True).stdout.strip()
    archive = subprocess.run(['git', '-C', str(repo), 'archive', revision],
                             check=True, capture_output=True).stdout
    payload = {}
    with tarfile.open(fileobj=io.BytesIO(archive)) as source:
        for entry in source:
            if entry.isdir():
                continue
            path = PurePosixPath(entry.name)
            build_runtime.safe_path(Path('code'), str(path))
            if not entry.isfile():
                raise ValueError(f'archive contains non-regular file: {entry.name}')
            payload['code/' + entry.name] = source.extractfile(entry).read()
    for path in sorted(runtime.rglob('*')):
        if path.is_symlink():
            raise ValueError(f'runtime symlink: {path}')
        if path.is_file() and path.name != 'build-info.json':
            payload['runtime/' + path.relative_to(runtime).as_posix()] = path.read_bytes()
    for name in ('AgenticOS.cmd', 'Launch-AgenticOS.ps1', 'Install-AgenticOS.ps1',
                 'Uninstall-AgenticOS.ps1', 'Package-Common.ps1'):
        payload[name] = (Path(__file__).parent / name).read_bytes()
    runtime_manifest = json.loads(payload['runtime/runtime-manifest.json'])
    manifest = {'schema_version': 1, 'version': version, 'code_sha': revision,
                'runtime_manifest_sha256': digest(payload['runtime/runtime-manifest.json']),
                'pe_inventory': runtime_manifest['pe_inventory'],
                'files': [{'path': name, 'sha256': digest(data)} for name, data in sorted(payload.items())]}
    payload['package-manifest.json'] = (json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode()
    out.mkdir(parents=True, exist_ok=True)
    target = out / f'AgenticOS-{version}.zip'
    if target.exists():
        raise ValueError(f'refusing to overwrite {target}')
    with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as package:
        for name, data in sorted(payload.items()):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            package.writestr(info, data, compresslevel=9)
    (out / 'SHA256SUMS').write_text(f'{digest(target.read_bytes())}  {target.name}\n', encoding='ascii')
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('runtime', 'repo', 'sha', 'version', 'out'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    try:
        print(assemble(args.runtime, args.repo, args.sha, args.version, args.out))
        return 0
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f'ERROR: {exc}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
