import json
from pathlib import Path
from unittest.mock import patch

import yaml

from dispatch.assignment_channel import read_assignment
from orchestrator.supervisor import process_once
from tests.test_builder_condition_retry import ConditionRetryFixture, _monitor


class SupervisorContractTests(ConditionRetryFixture):
    def run_builder(self, monitor):
        return process_once(self.root, config=self._config(), popen=self._popen,
                            launch_plan_builder=self._plan, monitor=monitor)

    def test_missing_relevant_file_routes_reviewable_failure_without_launch(self):
        task_path = self.root/'tasks/active/T-COND.yaml'
        task = yaml.safe_load(task_path.read_text())
        task['contract'] = {'objective': 'fixture', 'relevant_files': ['missing.py'],
            'allowed_edit_paths': ['docs/**'], 'acceptance_commands': [],
            'completion_condition': 'handoff and diff', 'handoff_path': 'handoffs/result.md'}
        task_path.write_text(yaml.safe_dump(task))
        with patch('orchestrator.supervisor.launch_process') as launch:
            result = self.run_builder(_monitor('', exit_code=0))
            launch.assert_not_called()
        self.assertIn('contract_files_missing', result['reason'])
        assignment, errors = read_assignment(self.root, self.assignment_id)
        self.assertEqual(errors, [])
        self.assertEqual(assignment.status, 'reviewable_failure')

    def test_unrelated_state_mutation_is_failure_with_one_alert(self):
        inbox = self.root/'runtime/dispatch/assignments/inbox/other.json'
        inbox.write_text('{"status":"changes_requested"}')
        blocked = self.root/'tasks/blocked/OTHER.yaml'
        blocked.parent.mkdir(parents=True)
        blocked.write_text('status: blocked\n')
        def monitor(*args, **kwargs):
            inbox.write_text('{"status":"claimed"}')
            claim = self.root/'runtime/dispatch/assignments/claims/other.json'
            claim.write_text('{}')
            blocked.rename(self.root/'tasks/active/OTHER.yaml')
            return _monitor('', exit_code=0)(*args, **kwargs)
        result = self.run_builder(monitor)
        self.assertEqual(result['process_state'], 'failed', result)
        assignment, _ = read_assignment(self.root, self.assignment_id)
        self.assertEqual(assignment.status, 'reviewable_failure')
        alerts = list((self.root/'runtime/dispatch/alerts').glob('*.json'))
        self.assertEqual(len(alerts), 1)
        alert = json.loads(alerts[0].read_text())
        self.assertEqual(alert['event'], 'isolation_violation')
        self.assertEqual(len(alert['diagnostic']['changed_state_paths']), 4)

    def test_supervisor_own_lock_heartbeat_does_not_flag(self):
        from dispatch import work_lock
        def monitor(*args, **kwargs):
            state = kwargs['state']
            work_lock.heartbeat(self.root, state.logical_task_id, run_id=state.run_id)
            return _monitor('', exit_code=0)(*args, **kwargs)
        result = self.run_builder(monitor)
        self.assertEqual(result['process_state'], 'completed', result)
        self.assertEqual(list((self.root/'runtime/dispatch/alerts').glob('*.json')), [])
