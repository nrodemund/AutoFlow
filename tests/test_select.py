import unittest

from autoflow.engine import Engine, GraphError
from autoflow.registry import discover


def project(inputs, nodes=None):
    return {'version': 1, 'schema_revision': 3, 'main': 'Main', 'graphs': {
        'Main': {'entry': 'start', 'parameters': {},
                 'outputs': {'result': {'ref': ['select', 'result']}},
                 'nodes': {'start': {'type': 'Start', 'inputs': {}},
                           'select': {'type': 'Select', 'inputs': inputs}} | (nodes or {})}}}


class SelectTests(unittest.TestCase):
    def test_select_preserves_value_types(self):
        for condition in (True, False):
            for value in ('hello', 42, 1.5, False, None, [1, 2], {'key': 'value'}):
                with self.subTest(condition=condition, value=value):
                    inputs = {'condition': condition, 'when_true': value, 'when_false': value}
                    inputs['when_false' if condition else 'when_true'] = 'other'
                    result = Engine(project(inputs), discover()).run()['result']
                    self.assertEqual(result, value)
                    self.assertIs(type(result), type(value))

    def test_only_selected_input_is_evaluated(self):
        for condition in (True, False):
            with self.subTest(condition=condition):
                inputs = {'condition': condition, 'when_true': 'safe', 'when_false': 'safe'}
                inputs['when_false' if condition else 'when_true'] = {'ref': ['bad', 'result']}
                p = project(inputs, {'bad': {'type': 'DivideInt', 'inputs': {'a': 1, 'b': 0}}})
                self.assertEqual(Engine(p, discover()).run(), {'result': 'safe'})
                p['graphs']['Main']['nodes']['select']['inputs']['condition'] = not condition
                with self.assertRaisesRegex(GraphError, 'zero'):
                    Engine(p, discover()).run()

    def test_condition_must_be_bool(self):
        for condition in (1, 'true', None):
            with self.subTest(condition=condition), self.assertRaisesRegex(GraphError, 'bool'):
                Engine(project({'condition': condition}), discover()).run()

    def test_result_can_feed_typed_input(self):
        p = project({'condition': True, 'when_true': 'chosen', 'when_false': 42}, {
            'append': {'type': 'StringAppend', 'inputs': {'a': {'ref': ['select', 'result']}, 'b': '!'}}})
        p['graphs']['Main']['outputs'] = {'result': {'ref': ['append', 'result']}}
        self.assertEqual(Engine(p, discover()).run(), {'result': 'chosen!'})
