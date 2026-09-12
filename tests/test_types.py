import unittest
from unittest.mock import patch
from autoflow.engine import Engine, GraphError
from autoflow.registry import discover
from autoflow.migrations import upgrade_project


def project(nodes, outputs=None):
    return {"version": 1, "schema_revision": 2, "main": "Main", "graphs": {"Main": {
        "entry": "start", "parameters": {}, "outputs": outputs or {},
        "nodes": {"start": {"type": "Start", "inputs": {}}} | nodes}}}


class TypesTests(unittest.TestCase):
    def test_point_add_and_offset_chain(self):
        from autoflow.datatypes import Point
        p = project({'add': {'type': 'AddPoint', 'inputs': {'a': {'x': -10, 'y': 20}, 'b': {'x': 3, 'y': -5}}},
                     'offset': {'type': 'OffsetPoint', 'inputs': {'point': {'ref': ['add', 'point']}, 'x': -2, 'y': 4}}},
                    {'sum': {'ref': ['add', 'point']}, 'offset': {'ref': ['offset', 'point']}})
        result = Engine(p, discover()).run()
        self.assertEqual(result, {'sum': Point(-7, 15), 'offset': Point(-9, 19)})
        self.assertIs(type(result['offset']), Point)
        self.assertEqual(p['graphs']['Main']['nodes']['add']['inputs']['a'], {'x': -10, 'y': 20})
        for invalid in (True, 1.5):
            p['graphs']['Main']['nodes']['offset']['inputs']['x'] = invalid
            with self.assertRaisesRegex(GraphError, 'integer'): Engine(p, discover()).run()

    def test_integer_math(self):
        for kind, expected in [("AddInt", -4), ("SubtractInt", -10), ("MultiplyInt", -21),
                               ("DivideInt", -2), ("ModuloInt", -1), ("MinInt", -7), ("MaxInt", 3)]:
            p = project({"op": {"type": kind, "inputs": {"a": -7, "b": 3}}}, {"result": {"ref": ["op", "result"]}})
            self.assertEqual(Engine(p, discover()).run(), {"result": expected})
        for kind in ("DivideInt", "ModuloInt"):
            p = project({"op": {"type": kind, "inputs": {"a": 10, "b": 0}}}, {"result": {"ref": ["op", "result"]}})
            with self.assertRaisesRegex(GraphError, "zero"):
                Engine(p, discover()).run()

    def test_make_break_point(self):
        p = project({"make": {"type": "MakePoint", "inputs": {"x": -20, "y": 51}},
                     "split": {"type": "BreakPoint", "inputs": {"point": {"ref": ["make", "point"]}}}},
                    {"x": {"ref": ["split", "x"]}, "y": {"ref": ["split", "y"]}})
        self.assertEqual(Engine(p, discover()).run(), {"x": -20, "y": 51})
        p["graphs"]["Main"]["nodes"]["make"]["inputs"]["x"] = 1.2
        with self.assertRaisesRegex(GraphError, "integer"):
            Engine(p, discover()).run()

    def test_no_number_pins_remain(self):
        for node in discover().values():
            self.assertNotIn("number", [value.rstrip("?") for value in (*node.inputs.values(), *node.outputs.values())])

    def test_legacy_migration_is_idempotent_and_does_not_edit_source(self):
        p = project({"find": {"type": "FindOnScreen", "inputs": {"texture": "a.png", "confidence": .7}},
                     "click": {"type": "Click", "inputs": {"x": {"ref": ["find", "x"]}, "y": {"ref": ["find", "y"]}}}},
                    {"x": {"ref": ["find", "x"]}})
        del p["schema_revision"]
        migrated = upgrade_project(p)
        nodes = migrated["graphs"]["Main"]["nodes"]
        self.assertEqual(nodes["find"]["inputs"]["confidence"], 70)
        self.assertIn("point", nodes["click"]["inputs"])
        self.assertTrue(any(n["type"] == "BreakPoint" for n in nodes.values()))
        self.assertEqual(upgrade_project(migrated), migrated)
        self.assertIn("x", p["graphs"]["Main"]["nodes"]["click"]["inputs"])
        Engine(migrated, discover())

    def test_ab_branches_and_priority(self):
        for a, b, expected in [(True, True, "A"), (False, True, "B"), (False, False, "Timeout")]:
            logs = []
            p = project({"start": {"type": "WaitUntilAB", "inputs": {"a": a, "b": b, "timeout_ms": 0},
                                   "next": {"a": "print_a", "b": "print_b", "timeout": "print_timeout"}},
                         **{"print_" + key: {"type": "Print", "inputs": {"value": value}} for key, value in [("a", "A"), ("b", "B"), ("timeout", "Timeout")]}})
            Engine(p, discover(), log=logs.append).run()
            self.assertEqual(logs, [expected])

    def test_ab_rechecks_and_cancels(self):
        p = project({"start": {"type": "WaitUntilAB", "inputs": {"a": False, "b": {"ref": ["visible", "found"]}}},
                     "visible": {"type": "IsOnScreen", "inputs": {"texture": "a.png"}}},
                    {"attempt": {"ref": ["start", "attempt"]}})
        class Screen:
            def __init__(self): self.calls = 0
            def find(self, *args):
                self.calls += 1
                return (1, 2) if self.calls == 3 else None
        engine = Engine(p, discover(), screen=Screen())
        with patch.object(engine.cancel, "wait", return_value=False):
            self.assertEqual(engine.run(), {"attempt": 3})
        engine = Engine(p, discover(), screen=Screen())
        with patch.object(engine.cancel, "wait", side_effect=lambda seconds: engine.cancel.set()):
            with self.assertRaisesRegex(GraphError, "cancelled"):
                engine.run()

    def test_ab_timeout_timing(self):
        p = project({"start": {"type": "WaitUntilAB", "inputs": {"a": False, "b": False, "timeout_ms": 1000, "interval_ms": 500}}},
                    {"elapsed": {"ref": ["start", "elapsed_ms"]}, "attempt": {"ref": ["start", "attempt"]}})
        engine = Engine(p, discover())
        now = [0.0]
        def wait(seconds): now[0] += seconds
        with patch("autoflow.nodes.wait_ab.time.monotonic", side_effect=lambda: now[0]), patch.object(engine.cancel, "wait", side_effect=wait):
            self.assertEqual(engine.run(), {"elapsed": 1000, "attempt": 3})
