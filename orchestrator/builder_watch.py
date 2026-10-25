"""Task-aware progress and state mutation evidence, independent of CLI claims."""
from __future__ import annotations

from collections import Counter, deque
import fnmatch
import json
from pathlib import Path, PureWindowsPath
import re

from orchestrator.run_deadlines import worktree_snapshot


def state_snapshot(root):
    result = {}
    for rel in ('runtime/dispatch/assignments/inbox', 'runtime/dispatch/assignments/claims',
                'runtime/dispatch/locks', 'tasks'):
        directory = root / rel
        if directory.exists():
            for path in directory.rglob('*'):
                if path.is_file():
                    stat = path.stat()
                    result[path.relative_to(root).as_posix()] = (stat.st_size, stat.st_mtime_ns)
    return result


def changed_state(before, after, supervisor_paths=()):
    excluded = set(supervisor_paths)
    return sorted(path for path in before.keys() | after.keys()
                  if before.get(path) != after.get(path) and path not in excluded)


class BuilderWatch:
    def __init__(self, worktree, contract, *, notify):
        self.root = Path(worktree).resolve()
        self.contract, self.notify = contract, notify
        self.initial = worktree_snapshot(self.root)
        self.histogram = Counter()
        self.targets = deque(maxlen=10)
        self.seen = set()
        self.turns = 0
        self.outside = []
        self.reads = set()
        self.early = False
        self.offset = 0
        self.partial = ''

    def touched(self):
        current = worktree_snapshot(self.root)
        return sorted(Path(p).relative_to(self.root).as_posix()
                      for p in current.keys() | self.initial.keys()
                      if current.get(p) != self.initial.get(p))

    def allowed_changes(self):
        return [path for path in self.touched()
                if any(fnmatch.fnmatchcase(path, pattern) for pattern in self.contract['allowed_edit_paths'])]

    def _outside(self, value):
        # Absolute references anywhere in commands or structured path fields.
        value = re.sub(r'https?://\S+', '', value)
        candidates = re.findall(r'[A-Za-z]:[\\/][^\s"\'|;<>]+|(?<![\w.:])/(?:[^\s"\'|;<>]+)', value)
        for candidate in candidates:
            candidate = candidate.rstrip('),')
            if PureWindowsPath(candidate).drive:
                base = str(self.root).replace('\\', '/').casefold().rstrip('/')
                normalized = candidate.replace('\\', '/').casefold()
                # Resolve .. lexically even when replaying Windows events on Linux.
                import ntpath
                normalized = ntpath.normpath(normalized).replace('\\', '/')
                if normalized != base and not normalized.startswith(base + '/'):
                    return True
            elif not Path(candidate).resolve().is_relative_to(self.root):
                return True
        return bool(re.search(r'(^|[\s"\'=])\.\.[\\/]', value))

    def event(self, event):
        kind = event.get('type')
        if kind == 'usage':
            self.turns += 1
        if kind == 'tool_call':
            identifier = event.get('toolCallId')
            if identifier and identifier in self.seen:
                return
            self.seen.add(identifier)
            tool = str(event.get('toolName') or event.get('title') or 'unknown')
            self.histogram[tool] += 1
            raw = event.get('rawInput') or {}
            target = json.dumps(raw, ensure_ascii=False) if isinstance(raw, dict) else str(raw)
            self.targets.append(target[:500])
            for path in ('.agentic/TASK_CONTRACT.json', '.agentic/TASK_CONTRACT.md', '.agentic/task.yaml',
                         *self.contract['relevant_files']):
                if tool in {'read_file', 'run_terminal_command'} and path in target.replace('\\\\', '/'):
                    self.reads.add(path)
            # Decode JSON escaping before checking Windows path references.
            values = list(raw.values()) if isinstance(raw, dict) else [raw]
            if any(self._outside(value) for value in values if isinstance(value, str)):
                self.outside.append({'tool': tool, 'target': target[:500]})
                if len(self.outside) == 1:
                    self.notify('isolation_violation', self.diagnostic())
        if (not self.early and self.turns >= self.contract['turn_budget'] * .4
                and not self.allowed_changes() and not (self.root/'.agentic/PLAN.md').is_file()):
            self.early = True
            self.notify('no_early_progress', self.diagnostic())

    def poll(self, path):
        if not path.exists():
            return
        with path.open(encoding='utf-8', errors='replace') as stream:
            stream.seek(self.offset)
            text = self.partial + stream.read()
            self.offset = stream.tell()
        lines = text.split('\n')
        self.partial = lines.pop()
        for line in lines:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict):
                self.event(event)

    def diagnostic(self):
        return {'turns_used': self.turns, 'tool_calls': sum(self.histogram.values()),
                'tool_histogram': dict(self.histogram), 'last_10_targets': list(self.targets),
                'files_touched': self.touched(), 'contract_files_read': sorted(self.reads),
                'out_of_worktree_accesses': self.outside}
