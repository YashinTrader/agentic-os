"""Materialize and verify the supervisor-owned, self-contained builder contract."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PureWindowsPath
import re
import subprocess


class ContractError(ValueError):
    def __init__(self, reason, detail):
        self.reason = reason
        super().__init__(f'{reason}: {detail}')


def relative_path(value):
    if (not isinstance(value, str) or not value or '\\' in value or
            Path(value).is_absolute() or PureWindowsPath(value).drive or
            any(part in {'..', ''} for part in value.split('/')) or ':' in value):
        raise ContractError('contract_invalid', f'unsafe relative path: {value!r}')
    return value


def _validate_schema(value, schema, location='contract'):
    """Validate the exact stdlib-only subset used by the checked-in schema."""
    kind = schema['type']
    types = {'object': dict, 'array': list, 'string': str, 'integer': int, 'boolean': bool}
    if type(value) is not types[kind]:
        raise ContractError('contract_invalid', f'{location}: expected {kind}')
    if kind == 'object':
        if set(schema.get('required', [])) - value.keys():
            raise ContractError('contract_invalid', f'{location}: required fields missing')
        if schema.get('additionalProperties') is False and value.keys() - schema['properties'].keys():
            raise ContractError('contract_invalid', f'{location}: unknown fields')
        for key, item in value.items():
            _validate_schema(item, schema['properties'][key], location + '.' + key)
    elif kind == 'array':
        if len(value) < schema.get('minItems', 0):
            raise ContractError('contract_invalid', f'{location}: empty list')
        for item in value:
            _validate_schema(item, schema['items'], location)
    elif kind == 'string' and len(value.strip()) < schema.get('minLength', 0):
        raise ContractError('contract_invalid', f'{location}: empty string')
    elif kind == 'integer' and not schema.get('minimum', value) <= value <= schema.get('maximum', value):
        raise ContractError('contract_invalid', f'{location}: out of bounds')


def validate_contract(contract, root):
    schema = json.loads((Path(__file__).resolve().parents[1] / 'schemas/task_contract.schema.json').read_text())
    _validate_schema(contract, schema)
    root = root.resolve()
    for key in ('relevant_files', 'allowed_edit_paths'):
        for value in contract[key]:
            relative_path(value)
    relative_path(contract['handoff_path'])
    missing = []
    for name in contract['relevant_files']:
        path = root / name
        if not path.resolve().is_relative_to(root) or not path.is_file():
            missing.append(name)
    if missing:
        raise ContractError('contract_files_missing', ', '.join(missing))


def prepare_contract(root, task_bytes, *, turn_budget=30, handoff_path=None):
    import yaml
    root = Path(root).resolve()
    task = yaml.safe_load(task_bytes)
    if not isinstance(task, dict):
        raise ContractError('contract_invalid', 'task must be a mapping')
    source = task.get('contract')
    if source is not None and not isinstance(source, dict):
        raise ContractError('contract_invalid', 'contract must be a mapping')
    if source is None:
        # Acceptance prose is not safe to execute as a shell command.
        source = dict(objective=task.get('objective') or task.get('title'),
                      relevant_files=['.agentic/task.yaml'],
                      allowed_edit_paths=task.get('allowed_paths') or (task.get('execution') or {}).get('allowed_paths') or [],
                      acceptance_commands=task.get('verification_commands') or [],
                      completion_condition='Allowed diff non-empty; all acceptance commands exit 0; handoff exists.')
    contract = {**source, 'derived': task.get('contract') is None}
    contract.setdefault('turn_budget', turn_budget)
    if contract['turn_budget'] != turn_budget:
        raise ContractError('contract_invalid', 'contract turn budget differs from launcher budget')
    contract.setdefault('handoff_path', handoff_path or task.get('handoff_path'))
    contract.setdefault('forbidden_actions', ['session pickup', 'assignment/lock CLIs', 'access outside workspace',
                                               'network', 'secrets', 'deployment'])
    meta = root / '.agentic'
    meta.mkdir(parents=True, exist_ok=True)
    (meta / 'task.yaml').write_bytes(task_bytes)
    if '.agentic/task.yaml' not in contract.get('relevant_files', []):
        contract['relevant_files'] = [*contract.get('relevant_files', []), '.agentic/task.yaml']
    validate_contract(contract, root)
    exclude = root / '.git/info/exclude'
    exclude.parent.mkdir(parents=True, exist_ok=True)
    with exclude.open('a', encoding='utf-8') as stream:
        stream.write('\n/.agentic/\n')
    tracked = subprocess.run(['git', '-C', str(root), 'ls-files', '--', '.agentic'],
                             capture_output=True, text=True, timeout=15, check=False)
    if tracked.returncode or tracked.stdout.strip():
        raise ContractError('contract_invalid', '.agentic must not be tracked')
    data = json.dumps(contract, indent=2, sort_keys=True).encode('utf-8') + b'\n'
    (meta / 'TASK_CONTRACT.json').write_bytes(data)
    rendered = '# Builder task contract\n\n```json\n' + data.decode() + '```\n'
    (meta / 'TASK_CONTRACT.md').write_text(rendered, encoding='utf-8')
    return contract, hashlib.sha256(data).hexdigest()


def verify_contract(root, expected_hash):
    if not expected_hash:
        raise ContractError('contract_invalid', 'supervisor contract hash missing')
    root = Path(root).resolve()
    try:
        data = (root / '.agentic/TASK_CONTRACT.json').read_bytes()
        contract = json.loads(data)
    except (OSError, ValueError) as exc:
        raise ContractError('contract_invalid', str(exc)) from exc
    if hashlib.sha256(data).hexdigest() != expected_hash:
        raise ContractError('contract_invalid', 'contract hash mismatch')
    if not (root / '.agentic/TASK_CONTRACT.md').is_file():
        raise ContractError('contract_files_missing', '.agentic/TASK_CONTRACT.md')
    validate_contract(contract, root)
    return contract


def contract_prompt(contract):
    summary = json.dumps(contract, ensure_ascii=True, sort_keys=True)
    if re.search(r'[A-Za-z]:[\\/]|(?<![\w.])/\w', summary):
        raise ContractError('contract_invalid', 'absolute path reference in prompt contract')
    return ('You are already assigned. Read .agentic/TASK_CONTRACT.json, .agentic/TASK_CONTRACT.md '
            'and .agentic/task.yaml. Do not run session pickup or any assignment/lock CLI. '
            'Do not access paths outside the worktree. If the contract is insufficient, stop and write '
            'the handoff with a blocked reason. Contract summary: ' + summary)
