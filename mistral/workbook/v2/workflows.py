# Copyright 2015 - Mirantis, Inc.
# Copyright 2015 - StackStorm, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

from mistral import exceptions as exc
from mistral import utils
from mistral.workbook import types
from mistral.workbook.v2 import base
from mistral.workbook.v2 import task_defaults
from mistral.workbook.v2 import tasks


class WorkflowSpec(base.BaseSpec):
    # See http://json-schema.org

    _polymorphic_key = ('type', 'direct')

    _task_defaults_schema = task_defaults.TaskDefaultsSpec.get_schema(
        includes=None)

    _meta_schema = {
        "type": "object",
        "properties": {
            "type": types.WORKFLOW_TYPE,
            "task-defaults": _task_defaults_schema,
            "input": types.UNIQUE_STRING_OR_ONE_KEY_DICT_LIST,
            "output": types.NONEMPTY_DICT,
            "vars": types.NONEMPTY_DICT
        },
        "required": ["tasks"],
        "additionalProperties": False
    }

    def __init__(self, data):
        super(WorkflowSpec, self).__init__(data)

        self._name = data['name']
        self._description = data.get('description')
        self._tags = data.get('tags', [])
        self._type = data['type'] if 'type' in data else 'direct'
        self._input = utils.get_input_dict(data.get('input', []))
        self._output = data.get('output', {})
        self._vars = data.get('vars', {})

        self._task_defaults = self._spec_property(
            'task-defaults',
            task_defaults.TaskDefaultsSpec
        )

        # Inject 'type' here, so instantiate_spec function can recognize the
        # specific subclass of TaskSpec.
        for task in self._data.get('tasks').itervalues():
            task['type'] = self._type

        self._tasks = self._spec_property('tasks', tasks.TaskSpecList)

    def validate_schema(self):
        super(WorkflowSpec, self).validate_schema()

        if not self._data.get('tasks'):
            raise exc.InvalidModelException(
                "Workflow doesn't have any tasks [data=%s]" % self._data
            )

        # Validate YAQL expressions.
        self.validate_yaql_expr(self._data.get('output', {}))
        self.validate_yaql_expr(self._data.get('vars', {}))

    def validate_semantics(self):
        # Doesn't do anything by default.
        pass

    def get_name(self):
        return self._name

    def get_description(self):
        return self._description

    def get_tags(self):
        return self._tags

    def get_type(self):
        return self._type

    def get_input(self):
        return self._input

    def get_output(self):
        return self._output

    def get_vars(self):
        return self._vars

    def get_task_defaults(self):
        return self._task_defaults

    def get_tasks(self):
        return self._tasks


class DirectWorkflowSpec(WorkflowSpec):
    _polymorphic_value = 'direct'

    _schema = {
        "properties": {
            "tasks": {
                "type": "object",
                "minProperties": 1,
                "patternProperties": {
                    "^\w+$":
                        tasks.DirectWorkflowTaskSpec.get_schema(includes=None)
                }
            },
        }
    }

    def validate_semantics(self):
        # Check if there are start tasks.
        if not self.find_start_tasks():
            raise exc.DSLParsingException(
                'Failed to find start tasks in direct workflow. '
                'There must be at least one task without inbound transition.'
                '[workflow_name=%s]' % self._name
            )

    def find_start_tasks(self):
        return [
            t_s for t_s in self.get_tasks()
            if not self.has_inbound_transitions(t_s)
        ]

    def find_inbound_task_specs(self, task_spec):
        return [
            t_s for t_s in self.get_tasks()
            if self.transition_exists(t_s.get_name(), task_spec.get_name())
        ]

    def find_outbound_task_specs(self, task_spec):
        return [
            t_s for t_s in self.get_tasks()
            if self.transition_exists(task_spec.get_name(), t_s.get_name())
        ]

    def has_inbound_transitions(self, task_spec):
        return len(self.find_inbound_task_specs(task_spec)) > 0

    def has_outbound_transitions(self, task_spec):
        return len(self.find_outbound_task_specs(task_spec)) > 0

    def transition_exists(self, from_task_name, to_task_name):
        t_names = set()

        for tup in self.get_on_error_clause(from_task_name):
            t_names.add(tup[0])

        for tup in self.get_on_success_clause(from_task_name):
            t_names.add(tup[0])

        for tup in self.get_on_complete_clause(from_task_name):
            t_names.add(tup[0])

        return to_task_name in t_names

    def get_on_error_clause(self, t_name):
        result = self.get_tasks()[t_name].get_on_error()

        if not result:
            t_defaults = self.get_task_defaults()

            if t_defaults:
                result = self._remove_task_from_clause(
                    t_defaults.get_on_error(),
                    t_name
                )

        return result

    def get_on_success_clause(self, t_name):
        result = self.get_tasks()[t_name].get_on_success()

        if not result:
            t_defaults = self.get_task_defaults()

            if t_defaults:
                result = self._remove_task_from_clause(
                    t_defaults.get_on_success(),
                    t_name
                )

        return result

    def get_on_complete_clause(self, t_name):
        result = self.get_tasks()[t_name].get_on_complete()

        if not result:
            t_defaults = self.get_task_defaults()

            if t_defaults:
                result = self._remove_task_from_clause(
                    t_defaults.get_on_complete(),
                    t_name
                )

        return result

    @staticmethod
    def _remove_task_from_clause(on_clause, t_name):
        return filter(lambda tup: tup[0] != t_name, on_clause)


class ReverseWorkflowSpec(WorkflowSpec):
    _polymorphic_value = 'reverse'

    _schema = {
        "properties": {
            "tasks": {
                "type": "object",
                "minProperties": 1,
                "patternProperties": {
                    "^\w+$":
                        tasks.ReverseWorkflowTaskSpec.get_schema(includes=None)
                }
            },
        }
    }


class WorkflowSpecList(base.BaseSpecList):
    item_class = WorkflowSpec


class WorkflowListSpec(base.BaseListSpec):
    item_class = WorkflowSpec

    def get_workflows(self):
        return self.get_items()
