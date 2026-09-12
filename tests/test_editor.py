import copy
import json
import tempfile
import threading
import time
import unittest
from http.client import HTTPConnection
from pathlib import Path

from autoflow.engine import Engine, GraphError, load_project, save_project
from autoflow.registry import discover
from autoflow.server import Editor, make_server

ROOT = Path(__file__).resolve().parents[1]


class PureNodeTests(unittest.TestCase):
    def setUp(self):
        self.project = load_project(ROOT / "examples/add-print.json")
        self.registry = discover()
        self.messages = []

    def run_graph(self):
        return Engine(self.project, self.registry, log=self.messages.append).run()

    def test_add_is_pure_and_prints_sum(self):
        self.run_graph()
        self.assertEqual(self.messages, ["5"])

    def test_inline_values_change_output(self):
        self.project["graphs"]["Main"]["nodes"]["add"]["inputs"] = {"a": -10, "b": 17}
        self.run_graph()
        self.assertEqual(self.messages, ["7"])

    def test_add_rejects_float_and_boolean(self):
        for value in (2.5, True, "2"):
            self.project["graphs"]["Main"]["nodes"]["add"]["inputs"]["a"] = value
            with self.assertRaisesRegex(GraphError, "integer"):
                self.run_graph()

    def test_pure_data_cycle_is_reported(self):
        nodes = self.project["graphs"]["Main"]["nodes"]
        nodes["other"] = copy.deepcopy(nodes["add"])
        nodes["add"]["inputs"]["a"] = {"ref": ["other", "result"]}
        nodes["other"]["inputs"]["a"] = {"ref": ["add", "result"]}
        with self.assertRaisesRegex(GraphError, "Circular pure-node"):
            self.run_graph()

    def test_function_parameters_and_pure_return(self):
        self.project["graphs"]["Sum"] = {
            "entry": "start", "parameters": {"a": "integer", "b": "integer"},
            "nodes": {"start": {"type": "Start", "inputs": {}},
                      "add": {"type": "AddInt", "inputs": {"a": {"param": "a"}, "b": {"param": "b"}}}},
            "outputs": {"sum": {"ref": ["add", "result"]}}}
        engine = Engine(self.project, self.registry)
        self.assertEqual(engine.call("Sum", {"a": 4, "b": 8}, 0), {"sum": 12})


class EditorAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "examples").mkdir()
        self.project = load_project(ROOT / "examples/add-print.json")
        save_project(self.project, self.root / "examples/add-print.json")
        self.editor = Editor(self.root)
        self.server = make_server(self.editor, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        if self.editor.engine:
            self.editor.engine.cancel.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, path, data=None, headers=None):
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        request_headers = {"Content-Type": "application/json"} | (headers or {})
        connection.request("POST" if data is not None else "GET", path,
                           json.dumps(data) if data is not None else None, request_headers)
        response = connection.getresponse()
        status, body, mime = response.status, response.read(), response.getheader("Content-Type")
        connection.close()
        return status, json.loads(body) if mime == "application/json" else body

    def test_static_ui_and_node_catalog(self):
        for path in ("/", "/app.js", "/editor-features.js", "/style.css"):
            status, body = self.request(path)
            self.assertEqual(status, 200)
            self.assertTrue(body)
        status, body = self.request("/api/bootstrap")
        self.assertEqual(status, 200)
        self.assertTrue(next(n for n in body["nodes"] if n["name"] == "AddInt")["pure"])
        for node in body["nodes"]:
            self.assertIsInstance(node["flows"], list)
        self.assertEqual(next(n for n in body["nodes"] if n["name"] == "GetDataset")["outputs"], {"dataset": "reference:Dataset"})

    def test_save_load_and_new_server_reopen_last_save(self):
        self.project["graphs"]["Main"]["nodes"]["add"]["position"] = [410, 270]
        self.project["graphs"]["Main"]["nodes"]["add"]["inputs"]["a"] = 40
        status, _ = self.request("/api/save", {"filename": "first.json", "project": self.project})
        self.assertEqual(status, 200)
        status, body = self.request("/api/load", {"filename": "first.json"})
        self.assertEqual(body["project"], self.project)
        self.assertEqual(Editor(self.root).initial()["project"], self.project)
        self.request("/api/save", {"filename": "last.json", "project": self.project})
        self.request("/api/load", {"filename": "first.json"})
        self.assertEqual(Editor(self.root).initial()["filename"], "last.json")
        self.assertEqual(self.request("/api/files")[1]["files"], ["first.json", "last.json"])

    def test_can_save_incomplete_draft_but_run_reports_error(self):
        self.project["graphs"]["Main"]["nodes"] = {}
        self.assertEqual(self.request("/api/save", {"filename": "draft.json", "project": self.project})[0], 200)
        status, body = self.request("/api/run", {"project": self.project})
        self.assertEqual(status, 400)
        self.assertIn("entry", body["error"])

    def test_malformed_document_is_rejected(self):
        self.assertEqual(self.request("/api/import", {"project": {"version": 1}})[0], 400)

    def test_file_paths_and_cross_origin_are_rejected(self):
        self.assertEqual(self.request("/api/save", {"filename": "../escape.json", "project": self.project})[0], 400)
        self.assertEqual(self.request("/api/run", {"project": self.project}, {"Origin": "https://example.com"})[0], 403)
        self.assertEqual(self.request("/api/bootstrap", headers={"Host": "evil.test"})[0], 403)

    def test_run_streams_print_to_console_events(self):
        self.assertEqual(self.request("/api/run", {"project": self.project})[0], 200)
        deadline = time.monotonic() + 2
        while self.editor.running and time.monotonic() < deadline:
            time.sleep(.01)
        status, body = self.request("/api/events?after=0")
        self.assertEqual(status, 200)
        self.assertFalse(body["running"])
        self.assertIn("5", [e["message"] for e in body["events"] if e["kind"] == "print"])
        cursor = body["events"][-1]["id"]
        self.assertEqual(self.request(f"/api/events?after={cursor}")[1]["events"], [])
        self.assertEqual(self.request("/api/events?after=999999")[1]["events"], body["events"])

    def test_stop_interrupts_wait_and_blocks_concurrent_run(self):
        nodes = self.project["graphs"]["Main"]["nodes"]
        nodes["start"] = {"type": "Wait", "inputs": {"milliseconds": 30000}}
        self.request("/api/run", {"project": self.project})
        self.assertEqual(self.request("/api/run", {"project": self.project})[0], 400)
        self.assertEqual(self.request("/api/stop", {})[0], 200)
        deadline = time.monotonic() + 2
        while self.editor.running and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertFalse(self.editor.running)
        self.assertTrue(any("cancelled" in e["message"] for e in self.editor.events))

    def test_texture_is_stored_as_relative_reference(self):
        import base64
        import io
        from PIL import Image
        image = io.BytesIO()
        Image.new("RGB", (3, 3), "red").save(image, format="PNG")
        content = base64.b64encode(image.getvalue()).decode()
        status, body = self.request("/api/texture", {"name": "test.png", "content": content})
        self.assertEqual(status, 200)
        with Image.open(self.editor.projects / body["path"]) as saved:
            self.assertEqual(saved.size, (3, 3))
            self.assertEqual(saved.getpixel((0, 0)), (255, 0, 0, 255))
        for suffix in ("", "&thumbnail=1"):
            status, preview = self.request("/api/texture-preview?path=" + body["path"] + suffix)
            self.assertEqual(status, 200)
            with Image.open(io.BytesIO(preview)) as image:
                self.assertEqual(image.getpixel((0, 0)), (255, 0, 0, 255))
        self.assertEqual(self.request("/api/texture-preview?path=missing.png")[0], 400)

    def test_corrupt_last_save_falls_back_with_warning(self):
        save_project({"last_saved": "missing.json"}, self.editor.state)
        result = self.editor.initial()
        self.assertEqual(result["project"], self.project)
        self.assertIn("Could not reopen", result["warning"])


if __name__ == "__main__":
    unittest.main()
