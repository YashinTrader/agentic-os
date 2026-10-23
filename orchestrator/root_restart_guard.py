"""Durable root-start budget, called under the supervisor control lock."""
from __future__ import annotations

import time
import uuid
from pathlib import Path

from dispatch.atomic_io import atomic_write_json
from orchestrator.layer_heartbeat import read_heartbeat
from orchestrator.launch_failures import alert_once
from orchestrator.supervisor_control import control_dir

ROOT_WINDOW = 1800
ROOT_COOLDOWN = 1800
ROOT_COOLDOWN_CAP = 8 * 3600


class RootRestartGuard:
    def __init__(self, root: Path, clock=time.time):
        self.root, self.clock = root, clock
        self.path = control_dir(root) / 'root_starts.json'
        self.token = uuid.uuid4().hex

    def start(self) -> bool:
        now = self.clock()
        data = read_heartbeat(self.path)
        if now < data.get('next_probe_at', 0):
            return False
        starts = [s for s in data.get('starts', []) if now - s['at'] < ROOT_WINDOW]
        if len(starts) >= 3 or data.get('probe_pending'):
            cooldown = min(ROOT_COOLDOWN_CAP, data.get('cooldown', ROOT_COOLDOWN // 2) * 2)
            data.update(starts=starts, cooldown=cooldown, next_probe_at=now + cooldown, probe_pending=False)
            data['alert'] = alert_once(self.root, ['root_restart_guard'], kind='root_restart_guard',
                                      action='Inspect root failures; use --reset-root-guard --actor --reason after remediation.')
            atomic_write_json(self.path, data)
            return False
        # A cooldown expiry admits exactly one root probe.
        if data.get('next_probe_at'):
            data.update(probe_pending=True, next_probe_at=0)
        starts.append({'at': now, 'token': self.token})
        data['starts'] = starts
        atomic_write_json(self.path, data)
        return True

    def healthy(self):
        atomic_write_json(self.path, {'starts': [], 'healthy_at': self.clock()})

    def planned_stop(self):
        data = read_heartbeat(self.path)
        data['starts'] = [s for s in data.get('starts', []) if s['token'] != self.token]
        data['probe_pending'] = False
        atomic_write_json(self.path, data)
