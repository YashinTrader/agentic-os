"""Stdlib-only launch classification, executable identity and deduplicated alerts."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from dispatch.atomic_io import atomic_write_json
from orchestrator.layer_heartbeat import timestamp

POLICY_MARKERS = ('application control policy has blocked', 'blocked by group policy',
                  'code integrity', 'did not meet the enterprise signing level')


def classify_launch_failure(exc=None, stderr="") -> str:
    if (isinstance(exc, OSError) and getattr(exc, 'winerror', None) in {4551, 1260, 4556, 225}
            or any(marker in (stderr + ' ' + str(exc or '')).lower() for marker in POLICY_MARKERS)):
        return 'BLOCKED_SECURITY_POLICY'
    if isinstance(exc, FileNotFoundError) or getattr(exc, 'winerror', None) in {2, 3}:
        return 'CONFIG'
    return 'TRANSIENT'


def executable_identity(command: str, root: Path, previous=None) -> dict:
    candidate = Path(command)
    if not candidate.is_absolute():
        candidate = root / candidate if candidate.parent != Path('.') else Path(shutil.which(command) or root / candidate)
    path = candidate.resolve()
    result = {'path': str(path), 'size': None, 'mtime': None, 'sha256': None}
    try:
        stat = path.stat()
        result.update(size=stat.st_size, mtime=stat.st_mtime_ns)
        if previous and all(result[k] == previous.get(k) for k in ('path', 'size', 'mtime')):
            result['sha256'] = previous.get('sha256')
        else:
            with path.open('rb') as stream:
                result['sha256'] = hashlib.file_digest(stream, 'sha256').hexdigest()
    except OSError:
        pass
    return result


def alert_once(root: Path, key, **payload) -> str:
    identifier = hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()
    path = root / 'runtime/dispatch/alerts' / (identifier + '.json')
    if not path.exists():
        atomic_write_json(path, {'id': identifier, 'at': timestamp(), **payload})
    return identifier
