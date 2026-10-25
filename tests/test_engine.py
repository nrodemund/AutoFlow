import copy
import tempfile
import unittest
from pathlib import Path
from autoflow.engine import Engine, GraphError, load_project, save_project
from autoflow.registry import discover

ROOT = Path(__file__).resolve().parents[1]


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.project = load_project(ROOT / "examples/csv-flow.json")
        self.registry = discover()
        self.messages = []

    def engine(self, project=None, **kwargs):
        return Engine(project or self.project, self.registry, ROOT / "examples",
                      log=self.messages.append, **kwargs)

    def test_csv_iteration_and_function_scope(self):
        self.assertEqual(self.engine().run(), {"count": 2})
        self.assertIn("Ada", self.messages[0])
        self.assertIn("Grace", self.messages[1])
        self.assertEqual(self.messages[2], "All CSV rows processed.")

    def test_round_trip_preserves_editor_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "flow.json"
            save_project(self.project, path)
            self.assertEqual(load_project(path), self.project)

    def test_invalid_flow_and_reference_rejected(self):
        for change in ("flow", "reference"):
            project = copy.deepcopy(self.project)
            load = project["graphs"]["Main"]["nodes"]["load"]
            if change == "flow":
                load["next"] = {"wrong": "each"}
            else:
                load["inputs"]["path"] = {"ref": ["each", "wrong"]}
            with self.assertRaises(GraphError):
                self.engine(project)

    def test_unexecuted_data_fails_clearly(self):
        self.project["graphs"]["Main"]["entry"] = "each"
        with self.assertRaisesRegex(GraphError, "execute its producer first"):
            self.engine().run()

    def test_execution_budget_stops_cycle(self):
        graph = self.project["graphs"]["Main"]
        graph["entry"] = "done"
        graph["nodes"]["done"]["next"] = {"then": "done"}
        with self.assertRaisesRegex(GraphError, "flow cycle limit"):
            self.engine(max_steps=3).run()

    def test_recursive_function_limit(self):
        node = self.project["graphs"]["ProcessRow"]["nodes"]["print"]
        node.update(type="CallFunction", inputs={"graph": "ProcessRow", "arguments": {"row": {"param": "row"}}})
        with self.assertRaisesRegex(GraphError, "depth limit"):
            self.engine(max_depth=3).run()

    def test_cancel(self):
        engine = self.engine()
        engine.cancel.set()
        with self.assertRaisesRegex(GraphError, "cancelled"):
            engine.run()

    def test_empty_loop_completes(self):
        graph = self.project["graphs"]["Main"]
        graph["entry"] = "each"
        graph["nodes"]["each"]["inputs"]["items"] = []
        self.assertEqual(self.engine().run(), {"count": 0})
        self.assertEqual(self.messages, ["All CSV rows processed."])

    def test_function_requires_declared_parameters(self):
        self.project["graphs"]["Main"]["nodes"]["process"]["inputs"]["arguments"] = {}
        with self.assertRaisesRegex(GraphError, "expected parameters"):
            self.engine().run()

    def test_screen_found_branch_and_offset(self):
        class FakeScreen:
            def __init__(self):
                self.clicks = []
            def find(self, texture, confidence=.97):
                return (10, 20)
            def click(self, x, y):
                self.clicks.append((x, y))
                return "fake click"
        screen = FakeScreen()
        project = load_project(ROOT / "examples/screen-flow.json")
        self.engine(project, screen=screen).run()
        self.assertEqual(screen.clicks, [(60, 70)])
        self.assertEqual(self.messages[-1], "Confirmation found.")

    def test_screen_not_found_branch(self):
        self.engine(load_project(ROOT / "examples/screen-flow.json")).run()
        self.assertEqual(len(self.messages), 1)
        self.assertIn("not found", self.messages[0])


if __name__ == "__main__":
    unittest.main()
