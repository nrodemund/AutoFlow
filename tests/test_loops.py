import unittest
from autoflow.engine import Engine, GraphError
from autoflow.registry import discover, NodeType
from autoflow.migrations import upgrade_project
from autoflow.datasets import get_dataset


def project(nodes, outputs=None, datasets=None):
    return {'version': 1, 'schema_revision': 3, 'main': 'Main', 'datasets': datasets or {},
            'graphs': {'Main': {'entry': 'loop', 'parameters': {}, 'nodes': nodes, 'outputs': outputs or {}}}}


class LoopTests(unittest.TestCase):
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
            with self.assertRaisesRegex(GraphError, 'step limit'):
                Engine(project({'loop': {'type': kind, 'inputs': inputs}}), discover(), max_steps=10).run()

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
