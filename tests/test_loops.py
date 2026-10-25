import unittest
from autoflow.engine import Engine, GraphError
from autoflow.registry import discover, NodeType
from autoflow.migrations import upgrade_project
from autoflow.datasets import get_dataset


def project(nodes, outputs=None, datasets=None):
    return {'version': 1, 'schema_revision': 3, 'main': 'Main', 'datasets': datasets or {},
            'graphs': {'Main': {'entry': 'loop', 'parameters': {}, 'nodes': nodes, 'outputs': outputs or {}}}}


class LoopTests(unittest.TestCase):
    def test_1800_rows_with_15_string_nodes_in_called_function(self):
        logs = []
        p = project({
            'loop': {'type': 'ForEachRow', 'inputs': {'dataset': {'ref': ['data', 'dataset']}}, 'next': {'body': 'call'}},
            'data': {'type': 'GetDataset', 'inputs': {'name': 'Data'}},
            'call': {'type': 'FunctionCall', 'function': 'Process', 'inputs': {'row': {'ref': ['loop', 'row']}}, 'next': {'then': 'print'}},
            'print': {'type': 'Print', 'inputs': {'value': {'ref': ['call', 'value']}}}},
            datasets={'Data': {'columns': ['id'], 'rows': [{'id': i} for i in range(1800)]}})
        nodes = {f's{i}': {'type': 'StringAppend', 'inputs': {
            'a': 'row' if i == 0 else {'ref': [f's{i-1}', 'result']}, 'b': 'x'}} for i in range(15)}
        nodes['return'] = {'type': 'FunctionReturn', 'inputs': {'value': {'ref': ['s14', 'result']}}}
        p['graphs']['Process'] = {'entry': 'return', 'parameters': {'row': 'dict'},
                                  'return_types': {'value': 'string'}, 'nodes': nodes}
        engine = Engine(p, discover(), log=logs.append)
        engine.run()
        self.assertEqual(logs, ['row' + 'x' * 15] * 1800)
        self.assertGreater(engine.steps, 27000)

    def test_default_boundary_and_custom_limit(self):
        for count, limit, fails in [(10000, None, False), (10001, None, True), (10001, 10001, False),
                                    (4, 3, True), (3, 3, False)]:
            with self.subTest(count=count, limit=limit):
                inputs = {'count': count}
                if limit is not None: inputs['max_iterations'] = limit
                engine = Engine(project({'loop': {'type': 'Repeat', 'inputs': inputs}}), discover())
                if fails:
                    with self.assertRaisesRegex(GraphError, 'Loop iteration limit reached'):engine.run()
                else:engine.run()

    def test_all_loop_limits_are_independent_of_body_and_nesting(self):
        for kind, inputs in [('ForLoop', {'start': 0, 'stop': 3}), ('Repeat', {'count': 3}),
                             ('ForEach', {'items': ['a', 'b', 'c']})]:
            with self.subTest(kind=kind):
                logs = []
                p = project({'loop': {'type': 'Repeat', 'inputs': {'count': 2, 'max_iterations': 2}, 'next': {'body': 'inner'}},
                    'inner': {'type': kind, 'inputs': inputs | {'max_iterations': 3}, 'next': {'body': 'print'}},
                    'print': {'type': 'Print', 'inputs': {'value': 'body'}, 'next': {'then': 'more'}},
                    'more': {'type': 'Print', 'inputs': {'value': 'more'}}})
                Engine(p, discover(), log=logs.append, max_steps=1).run()
                self.assertEqual(logs, ['body', 'more'] * 6)

    def test_dataset_limit_reports_loop_and_preserves_exact_body_count(self):
        logs = []
        p = project({'loop': {'type': 'ForEachRow', 'inputs': {'dataset': {'ref': ['data', 'dataset']}, 'max_iterations': 2},
                               'next': {'body': 'print'}},
                     'data': {'type': 'GetDataset', 'inputs': {'name': 'Data'}},
                     'print': {'type': 'Print', 'inputs': {'value': {'ref': ['loop', 'index']}}}},
                    datasets={'Data': {'columns': ['id'], 'rows': [{'id': i} for i in range(3)]}})
        with self.assertRaisesRegex(GraphError, r'Node loop .*iteration limit reached \(2\)'):
            Engine(p, discover(), log=logs.append).run()
        self.assertEqual(logs, ['0', '1'])

    def test_invalid_iteration_limits(self):
        for value in (0, -1, True, 2.5):
            with self.subTest(value=value), self.assertRaises(GraphError):
                Engine(project({'loop': {'type': 'Repeat', 'inputs': {'count': 0, 'max_iterations': value}}}), discover()).run()

    def test_polling_nodes_use_their_own_attempt_limits(self):
        p = project({'loop': {'type': 'WaitUntil', 'inputs': {
            'condition': False, 'interval_ms': 0, 'max_attempts': 10001}}},
            {'attempts': {'ref': ['loop', 'attempt']}})
        self.assertEqual(Engine(p, discover(), max_steps=1).run(), {'attempts': 10001})
        p = project({'loop': {'type': 'WaitUntilAB', 'inputs': {
            'a': False, 'b': False, 'interval_ms': 1, 'timeout_ms': 5000, 'max_attempts': 2}}})
        with self.assertRaisesRegex(GraphError, 'attempt limit reached'):
            Engine(p, discover()).run()

    def run_loop(self, kind, inputs):
        logs = []
        p = project({'loop': {'type': kind, 'inputs': inputs, 'next': {'body': 'print', 'completed': 'done'}},
                     'print': {'type': 'Print', 'inputs': {'value': {'ref': ['loop', 'index']}}},
                     'done': {'type': 'Print', 'inputs': {'value': 'done'}}})
        Engine(p, discover(), log=logs.append).run()
        return logs

    def test_range_repeat_and_empty(self):
        self.assertEqual(self.run_loop('ForLoop', {'start': 5, 'stop': -1, 'step': -2}), ['5', '3', '1', 'done'])
        self.assertEqual(self.run_loop('ForLoop', {'start': 0, 'stop': 0}), ['done'])
        self.assertEqual(self.run_loop('Repeat', {'count': 3}), ['0', '1', '2', 'done'])
        self.assertEqual(self.run_loop('Repeat', {'count': 0}), ['done'])
        for kind, inputs in [('ForLoop', {'step': 0}), ('Repeat', {'count': -1})]:
            with self.assertRaises(GraphError): self.run_loop(kind, inputs)

    def test_break_continue_and_nested_loop(self):
        for action, expected in [('Break', ['0', 'done']), ('Continue', ['0', '1', '2', 'done'])]:
            logs = []
            p = project({'loop': {'type': 'Repeat', 'inputs': {'count': 3}, 'next': {'body': 'print', 'completed': 'done'}},
                         'print': {'type': 'Print', 'inputs': {'value': {'ref': ['loop', 'index']}}, 'next': {'then': 'control'}},
                         'control': {'type': action, 'inputs': {}},
                         'done': {'type': 'Print', 'inputs': {'value': 'done'}}})
            Engine(p, discover(), log=logs.append).run()
            self.assertEqual(logs, expected)
        logs = []
        p = project({'loop': {'type': 'Repeat', 'inputs': {'count': 2}, 'next': {'body': 'inner'}},
                     'inner': {'type': 'Repeat', 'inputs': {'count': 10}, 'next': {'body': 'break', 'completed': 'print'}},
                     'break': {'type': 'Break', 'inputs': {}},
                     'print': {'type': 'Print', 'inputs': {'value': {'ref': ['loop', 'index']}}}})
        Engine(p, discover(), log=logs.append).run()
        self.assertEqual(logs, ['0', '1'])

    def test_control_outside_loop_and_empty_body_budget(self):
        for action in ('Break', 'Continue'):
            with self.assertRaisesRegex(GraphError, 'active loop'):
                Engine(project({'loop': {'type': action, 'inputs': {}}}), discover()).run()
        for kind, inputs in [('Repeat', {'count': 100}), ('WhileLoop', {'condition': True})]:
            with self.assertRaisesRegex(GraphError, 'iteration limit'):
                Engine(project({'loop': {'type': kind, 'inputs': inputs | {'max_iterations': 10}}}), discover()).run()

    def test_while_rechecks_and_limits(self):
        registry = discover()
        count = [0]
        def increment(c, n, i): count[0] += 1; return {}, 'then'
        registry['Increment'] = NodeType('Increment', {}, {}, ('then',), increment)
        registry['Condition'] = NodeType('Condition', {}, {'value': 'bool'}, (),
                                         lambda c, n, i: ({'value': count[0] < 3}, None), pure=True)
        p = project({'loop': {'type': 'WhileLoop', 'inputs': {'condition': {'ref': ['condition', 'value']}}, 'next': {'body': 'increment'}},
                     'condition': {'type': 'Condition', 'inputs': {}},
                     'increment': {'type': 'Increment', 'inputs': {}}}, {'count': {'ref': ['loop', 'count']}})
        self.assertEqual(Engine(p, registry).run(), {'count': 3})
        for inputs, expected in [({'condition': False}, 0), ({'condition': True, 'max_iterations': 2}, None)]:
            p = project({'loop': {'type': 'WhileLoop', 'inputs': inputs}}, {'count': {'ref': ['loop', 'count']}})
            if expected is None:
                with self.assertRaisesRegex(GraphError, 'iteration limit'): Engine(p, registry).run()
            else: self.assertEqual(Engine(p, registry).run(), {'count': expected})

    def test_cancellation(self):
        registry = discover()
        def cancel(c, n, i): c.engine.cancel.set(); return {}, 'then'
        registry['Cancel'] = NodeType('Cancel', {}, {}, ('then',), cancel)
        p = project({'loop': {'type': 'Repeat', 'inputs': {'count': 100}, 'next': {'body': 'cancel'}},
                     'cancel': {'type': 'Cancel', 'inputs': {}}})
        with self.assertRaisesRegex(GraphError, 'cancelled'): Engine(p, registry).run()

    def test_dataset_iterator_snapshot_and_identity(self):
        p = project({'loop': {'type': 'ForEachRow', 'inputs': {'dataset': {'ref': ['data', 'dataset']}}, 'next': {'body': 'append'}},
                     'data': {'type': 'GetDataset', 'inputs': {'name': 'Data'}},
                     'append': {'type': 'AppendRow', 'inputs': {'dataset': {'ref': ['data', 'dataset']}, 'row': {'ref': ['loop', 'row']}}}},
                    {'count': {'ref': ['loop', 'count']}}, {'Data': {'columns': ['x'], 'rows': [{'x': 1}, {'x': 2}]}})
        engine = Engine(p, discover())
        original = get_dataset(engine.project, 'Data')
        self.assertEqual(engine.run(), {'count': 2})
        self.assertIs(get_dataset(engine.project, 'Data'), original)
        self.assertEqual([r['x'] for r in original['rows']], [1, 2, 1, 2])
        self.assertEqual(len(p['datasets']['Data']['rows']), 2)

    def test_migrates_shared_getter(self):
        p = project({'loop': {'type': 'GetRows', 'inputs': {'dataset': 'Data'}},
                     'count': {'type': 'RowCount', 'inputs': {'dataset': 'Data'}}},
                    datasets={'Data': {'columns': ['x'], 'rows': []}})
        p['schema_revision'] = 2
        updated = upgrade_project(p)
        nodes = updated['graphs']['Main']['nodes']
        self.assertEqual(nodes['loop']['inputs']['dataset'], nodes['count']['inputs']['dataset'])
        self.assertEqual(len([n for n in nodes.values() if n['type'] == 'GetDataset']), 1)
        self.assertEqual(upgrade_project(updated), updated)
        self.assertEqual(p['graphs']['Main']['nodes']['loop']['inputs']['dataset'], 'Data')
