import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from autoflow import datatypes as dt, datasets as ds
from autoflow.engine import Engine, load_project, save_project
from autoflow.migrations import upgrade_project
from autoflow.registry import discover


class PythonDatatypeTests(unittest.TestCase):
    def test_storage_roundtrip(self):
        value = {'bytes': b'\x00\xff', 'set': {1, 2}, 'tuple': (1, 'a'),
                 'dict': {1: {'x': 2}}, 'point': dt.Point(3, 4),
                 'escaped': {'$type': 'bytes', 'value': 'plain dictionary'}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'values.json'
            save_project(value, path)
            result = load_project(path)
        self.assertEqual(result, value)
        self.assertIs(type(result['point']), dt.Point)
        self.assertIs(type(result['tuple']), tuple)
        self.assertIs(type(result['set']), set)
        self.assertIs(type(result['bytes']), bytes)

    def test_registry_uses_python_types(self):
        for node in discover().values():
            for kind in (*node.inputs.values(), *node.outputs.values()):
                base = kind.rstrip('?')
                self.assertTrue(base in (*dt.SCALARS, 'set', 'dict', 'reference') or base.startswith('reference:'), kind)

    def test_strict_types_and_custom_reference_identity(self):
        for value in (True, 1.5, '1'):
            with self.assertRaises(ValueError): dt.checked(value, 'integer')
        class Custom: pass
        value = Custom()
        self.assertIs(dt.checked(value, 'reference:Custom'), value)
        self.assertIs(dt.checked(value, 'reference'), value)
        self.assertIs(type(dt.checked(1, 'float')), float)

    def test_column_inference_and_restrictions(self):
        for values, expected in [([], 'string'), ([None], 'string'), (['001', '002'], 'string'),
                                  (['1', '2'], 'integer'), (['1', '2.5'], 'float'),
                                  (['true', 'false'], 'bool'), ([1, 'maybe'], 'string'),
                                  ([b'\xff'], 'bytes'), (['1e999'], 'string')]:
            table = ds.validate({'columns': ['x'], 'rows': [{'x': v} for v in values]})
            self.assertEqual(table['types']['x'], expected)
            for row in table['rows']: dt.checked(row['x'], expected)
        for value in ({}, set(), (), dt.Point()):
            with self.assertRaises(ValueError): ds.validate({'columns': ['x'], 'rows': [{'x': value}]})
        for kind in ('dict', 'set', 'reference:Point'):
            with self.assertRaises(ValueError): ds.validate({'columns': ['x'], 'rows': [], 'types': {'x': kind}})

    def test_bytes_interchange(self):
        for extension in ('.csv', '.xlsx'):
            table = ds.validate({'columns': ['x'], 'rows': [{'x': b'\x00\xff'}]})
            self.assertEqual(ds.read(ds.write(table, extension), extension)[0], table)

    def test_dataset_conversions(self):
        registry = discover()
        context = SimpleNamespace(engine=SimpleNamespace(project={'datasets': {'Data':
            {'columns': ['x', 'y'], 'rows': [{'x': 1, 'y': 'a'}, {'x': 1, 'y': 'a'}]}}}))
        self.assertEqual(registry['DatasetToSet'].execute(context, '', {'dataset': ds.get_dataset(context.engine.project, 'Data')})[0]['result'], {(1, 'a')})
        self.assertEqual(registry['DatasetToDict'].execute(context, '', {'dataset': ds.get_dataset(context.engine.project, 'Data')})[0]['result'][0], {'x': 1, 'y': 'a'})

    def test_runtime_values(self):
        values = [('Bool', True), ('Integer', 7), ('Float', 1.5), ('String', 'hello'),
                  ('Bytes', b'\xff'), ('Set', {1, 2}), ('Dict', {'a': 1}), ('Tuple', (1, 2))]
        nodes = {'start': {'type': 'Start', 'inputs': {}}}
        nodes.update({name: {'type': name, 'inputs': {'value': value}} for name, value in values})
        project = {'version': 1, 'schema_revision': 2, 'main': 'Main', 'graphs': {'Main': {
            'entry': 'start', 'nodes': nodes, 'parameters': {},
            'outputs': {name: {'ref': [name, 'value']} for name, _ in values}}}}
        result = Engine(project, discover()).run()
        for name, value in values:
            self.assertEqual(result[name], value)
            self.assertIs(type(result[name]), type(value))

    def test_migrate_existing_type_names(self):
        project = {'version': 1, 'schema_revision': 2, 'graphs': {'Main': {'parameters': {
            'a': 'boolean', 'b': 'object', 'c': 'array', 'd': 'point?', 'e': 'number'}}}}
        updated = upgrade_project(project)
        self.assertEqual(updated['graphs']['Main']['parameters'], {
            'a': 'bool', 'b': 'dict', 'c': 'reference:list', 'd': 'reference:Point?', 'e': 'float'})
        self.assertEqual(upgrade_project(updated), updated)
