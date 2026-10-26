"""Fail-safe operator pause for automatic builder launches."""
import json
from pathlib import Path
from orchestrator.supervisor_control import control_dir
from orchestrator.launch_failures import alert_once


def dispatch_status(root: Path) -> dict:
    path = control_dir(root) / 'control/builder_dispatch.json'
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if (not isinstance(data, dict) or type(data.get('paused')) is not bool
                or any(not isinstance(data.get(k), str) or not data[k].strip()
                       for k in ('actor', 'reason', 'at'))):
            raise ValueError('invalid builder dispatch control')
        return dict(paused=data['paused'], since=data['at'], actor=data['actor'], reason=data['reason'])
    except FileNotFoundError:
        return dict(paused=True, since=None, actor=None, reason="no control state (fail closed)")
    except (OSError, ValueError):
        alert_once(root, ['invalid_builder_dispatch_control'], kind='invalid_builder_dispatch_control',
                   reason='Unreadable or invalid builder dispatch control; dispatch paused')
        return dict(paused=True, since=None, actor=None, reason='invalid builder dispatch control')
