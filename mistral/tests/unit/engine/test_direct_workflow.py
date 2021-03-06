# Copyright 2014 - Mirantis, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

import mock
from oslo_config import cfg
from oslo_log import log as logging

from mistral.db.v2 import api as db_api
from mistral.engine import default_engine as de
from mistral import exceptions as exc
from mistral.services import workflows as wf_service
from mistral.tests.unit.engine import base
from mistral.workflow import states


LOG = logging.getLogger(__name__)

# Use the set_default method to set value otherwise in certain test cases
# the change in value is not permanent.
cfg.CONF.set_default('auth_enable', False, group='pecan')


class DirectWorkflowEngineTest(base.EngineTestCase):
    def _run_workflow(self, workflow_yaml):
        wf_service.create_workflows(workflow_yaml)

        wf_ex = self.engine.start_workflow('wf', {})

        self._await(lambda: self.is_execution_error(wf_ex.id))

        return db_api.get_workflow_execution(wf_ex.id)

    def test_direct_workflow_on_closures(self):
        wf_text = """
        version: '2.0'

        wf:
          # type: direct - 'direct' is default

          tasks:
            task1:
              description: |
                Explicit 'fail' command should lead to workflow failure.
              action: std.echo output="Echo"
              on-success:
                - task2
                - succeed
              on-complete:
                - task3
                - task4
                - fail
                - never_gets_here

            task2:
              action: std.noop

            task3:
              action: std.noop

            task4:
              action: std.noop

            never_gets_here:
              action: std.noop
        """

        wf_ex = self._run_workflow(wf_text)

        tasks = wf_ex.task_executions

        task1 = self._assert_single_item(tasks, name='task1')
        task3 = self._assert_single_item(tasks, name='task3')
        task4 = self._assert_single_item(tasks, name='task4')

        self.assertEqual(3, len(tasks))

        self._await(lambda: self.is_task_success(task1.id))
        self._await(lambda: self.is_task_success(task3.id))
        self._await(lambda: self.is_task_success(task4.id))

        self.assertTrue(wf_ex.state, states.ERROR)

    def test_direct_workflow_wrong_task_name(self):
        wf_text = """
        version: '2.0'

        wf:
          tasks:
            task1:
              action: std.echo output="Echo"
              on-success:
                - wrong_name
        """

        wf_service.create_workflows(wf_text)
        wf_ex = self.engine.start_workflow('wf', {})

        self._await(lambda: self.is_execution_error(wf_ex.id))
        wf_ex = db_api.get_workflow_execution(wf_ex.id)

        self.assertIn("'wrong_name' not found", wf_ex.state_info)

    def test_direct_workflow_change_state_after_success(self):
        wf_text = """
        version: '2.0'

        wf:
          tasks:
            task1:
              action: std.echo output="Echo"
              on-success:
                - task2

            task2:
              action: std.noop
        """

        wf_service.create_workflows(wf_text)
        wf_ex = self.engine.start_workflow('wf', {})

        self._await(lambda: self.is_execution_success(wf_ex.id))

        self.assertEqual(
            states.SUCCESS,
            self.engine.resume_workflow(wf_ex.id).state
        )
        self.assertRaises(
            exc.WorkflowException,
            self.engine.pause_workflow, wf_ex.id
        )
        self.assertEqual(
            states.SUCCESS,
            self.engine.stop_workflow(wf_ex.id, states.ERROR).state
        )

    def test_wrong_task_input(self):
        wf_text = """
        version: '2.0'

        wf:
          type: direct

          tasks:
            task1:
              action: std.echo output="Echo"
              on-complete:
                - task2

            task2:
              description: Wrong task output should lead to workflow failure
              action: std.echo wrong_input="Hahaha"
        """

        wf_ex = self._run_workflow(wf_text)

        self.assertIn(
            'Invalid input',
            wf_ex.state_info
        )

        self.assertTrue(wf_ex.state, states.ERROR)

    def test_wrong_first_task_input(self):
        wf_text = """
        version: '2.0'

        wf:
          type: direct

          tasks:
            task1:
              action: std.echo wrong_input="Ha-ha"
        """

        self.assertRaises(
            exc.InputException,
            self._run_workflow,
            wf_text
        )

    def test_wrong_action(self):
        wf_text = """
        version: '2.0'

        wf:
          type: direct

          tasks:
            task1:
              action: std.echo output="Echo"
              on-complete:
                - task2

            task2:
              action: action.doesnt_exist
        """

        wf_ex = self._run_workflow(wf_text)

        # TODO(dzimine): Catch tasks caused error, and set them to ERROR:
        # TODO(dzimine): self.assertTrue(task_ex.state, states.ERROR)

        self.assertTrue(wf_ex.state, states.ERROR)
        self.assertIn("Failed to find action", wf_ex.state_info)

    def test_wrong_action_first_task(self):
        wf_text = """
        version: '2.0'

        wf:
          type: direct

          tasks:
            task1:
              action: wrong.task
        """

        wf_service.create_workflows(wf_text)

        with mock.patch.object(de.DefaultEngine, '_fail_workflow') as mock_fw:
            self.assertRaises(
                exc.InvalidActionException,
                self.engine.start_workflow, 'wf', None)

            self.assertEqual(1, mock_fw.call_count)

            self.assertTrue(
                issubclass(
                    type(mock_fw.call_args[0][1]),
                    exc.InvalidActionException
                ),
                "Called with a right exception"
            )

    def test_messed_yaql(self):
        wf_text = """
        version: '2.0'

        wf:
          type: direct

          tasks:
            task1:
              action: std.echo output="Echo"
              on-complete:
                - task2

            task2:
              action: std.echo output=<% wrong(yaql) %>
        """

        wf_ex = self._run_workflow(wf_text)

        self.assertTrue(wf_ex.state, states.ERROR)

    def test_messed_yaql_in_first_task(self):
        wf_text = """
        version: '2.0'

        wf:
          type: direct
          tasks:
            task1:
              action: std.echo output=<% wrong(yaql) %>
        """

        wf_service.create_workflows(wf_text)

        with mock.patch.object(de.DefaultEngine, '_fail_workflow') as mock_fw:
            self.assertRaises(
                exc.YaqlEvaluationException,
                self.engine.start_workflow, 'wf', None
            )

            self.assertEqual(1, mock_fw.call_count)
            self.assertTrue(
                issubclass(
                    type(mock_fw.call_args[0][1]),
                    exc.YaqlEvaluationException
                ),
                "Called with a right exception"
            )

    def test_mismatched_yaql_in_first_task(self):
        wf_text = """
        version: '2.0'

        wf:
          input:
            - var
          tasks:
            task1:
              action: std.echo output=<% $.var + $.var2 %>
        """

        wf_service.create_workflows(wf_text)

        exception = self.assertRaises(
            exc.YaqlEvaluationException,
            self.engine.start_workflow, 'wf', {'var': 2}
        )

        self.assertIn("Can not evaluate YAQL expression", exception.message)

    def test_one_line_syntax_in_on_clauses(self):
        wf_text = """
        version: '2.0'

        wf:
          type: direct

          tasks:
            task1:
              action: std.echo output=1
              on-success: task2

            task2:
              action: std.echo output=1
              on-complete: task3

            task3:
              action: std.fail
              on-error: task4

            task4:
              action: std.echo output=4
        """

        wf_service.create_workflows(wf_text)

        wf_ex = self.engine.start_workflow('wf', {})

        self._await(lambda: self.is_execution_success(wf_ex.id))
