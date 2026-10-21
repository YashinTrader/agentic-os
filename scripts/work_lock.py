#!/usr/bin/env python3
"""Manual dispatch must acquire against the canonical repository before launch."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dispatch import work_lock


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('acquire', 'release', 'status', 'supersede'):
        command = sub.add_parser(name)
        command.add_argument('logical_task_id', nargs='?' if name == 'status' else None)
        if name in ('release', 'supersede'):
            command.add_argument('--actor', required=True)
            command.add_argument('--reason', required=True)
        if name in ('acquire', 'supersede'):
            command.add_argument('--holder-agent', required=True)
            command.add_argument('--route', default='manual_orchestrator')
            command.add_argument('--assignment-id', default='')
            command.add_argument('--run-id', default='')
            command.add_argument('--base-sha', default='')
            command.add_argument('--branch', default='')
    args = vars(parser.parse_args())
    root = args.pop('root').resolve()
    command = args.pop('command')
    logical_id = args.pop('logical_task_id')
    try:
        result = getattr(work_lock, command)(root, logical_id, **args)
        print(json.dumps(result, indent=2))
        return 0
    except (work_lock.WorkLockError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    if __package__:
        from ._console import configure_console
    else:
        from _console import configure_console

    configure_console()
    raise SystemExit(main())
