#!/usr/bin/env python3
"""Inspect/release consumer claims and review leases using an explicit audit trail."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from root_paths import operator_roots

from orchestrator.consumer_claims import list_records, release
from dispatch.work_lock import WorkLockError


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=None)
    parser.add_argument('verb', choices=['list', 'release'])
    parser.add_argument('key', nargs='?')
    parser.add_argument('--kind', choices=['claim', 'lease'], default='claim')
    parser.add_argument('--actor')
    parser.add_argument('--reason')
    args = parser.parse_args(argv)
    if args.verb == 'release' and not (args.key and args.actor and args.reason):
        parser.error('release requires key, --actor and --reason')
    try:
        with operator_roots(Path(__file__).resolve().parents[1], args.root) as root:
            result = (list_records(root) if args.verb == 'list' else
                      release(root, args.key, actor=args.actor, reason=args.reason, kind=args.kind))
    except (OSError, ValueError, WorkLockError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    if __package__:
        from ._console import configure_console
    else:
        from _console import configure_console

    configure_console()
    raise SystemExit(main())
