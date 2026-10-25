"""Dependency-free loopback web editor and cancellable graph execution."""
import base64
import uuid
from copy import deepcopy
from autoflow import datasets, bundles
from autoflow import datatypes as json
import mimetypes
import math
import re
import socket
import threading
import time
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from autoflow.engine import Engine, load_project, save_project
from autoflow.registry import discover
from autoflow.migrations import upgrade_project
from autoflow.screen import WindowsScreen, clipboard_texture, store_texture
from autoflow.run_control import settings as run_settings

ROOT = Path(__file__).resolve().parents[1]
STATIC = Path(__file__).parent / "web"


class Editor:
    def __init__(self, root=ROOT, screen_factory=WindowsScreen):
        self.root = Path(root).resolve()
        self.projects = self.root / "projects"
        self.projects.mkdir(exist_ok=True)
        self.state = self.projects / ".editor-state.json"
        self.registry = discover()
        self.screen_factory = screen_factory
        self.lock = threading.RLock()
        self.events = deque(maxlen=2000)
        self.sequence = 0
        self.running = False
        self.engine = None
        self.results = {}
        self.run_state = "ready"
        self.active_settings = run_settings({})
        self.run_id = None

    def status(self):
        engine = self.engine
        manual = None
        debug = None
        debug_edits = []
        if engine:
            with engine.manual_lock:
                manual = dict(engine.manual_request) if engine.manual_request else None
            with engine.debug_lock:
                request = engine.debug_request
                debug = {k: v for k, v in request.items() if k not in ('continued', 'resume_at')} if request else None
                if debug is not None:
                    debug['resuming'] = request['continued']
                    debug['resume_in_ms'] = max(0, math.ceil((request['resume_at'] - time.monotonic()) * 1000)) if request['continued'] else 0
                debug_edits = deepcopy(engine.debug_edits)
        state = self.run_state
        if self.running and engine:
            state = ("stopping" if engine.cancel.is_set() else "debug" if debug else "manual" if manual else "paused" if engine.paused
                     else "pausing" if not engine.resumed.is_set() else "running")
        return dict(state=state, text=(engine.status_text or engine.current_node) if engine else "",
                    steps=engine.steps if engine else 0, settings=self.active_settings,
                    manual={k:v for k,v in manual.items() if k != "choice"} if manual else None, debug=debug,
                    debug_edits=debug_edits, run_id=self.run_id)

    def path(self, filename):
        if not isinstance(filename, str) or not re.fullmatch(r"[\w -][\w .-]{0,100}\.json", filename):
            raise ValueError("Use a simple .json filename (letters, numbers, spaces, hyphens).")
        return self.projects / filename

    def initial(self):
        warning = None
        if self.state.exists():
            try:
                filename = load_project(self.state)["last_saved"]
                project = load_project(self.path(filename))
                self.check_document(project)
                return {"project": project, "filename": filename}
            except (ValueError, OSError, KeyError, TypeError) as exc:
                warning = f"Could not reopen last saved file: {exc}"
        return {"project": load_project(self.root / "examples/add-print.json"),
                "filename": "addition.json", "warning": warning, "saved": False}

    def catalog(self):
        return [dict(name=n.name, title=n.title or n.name, category=n.category,
                     inputs=n.inputs, outputs=n.outputs, flows=list(n.flows), defaults=n.defaults,
                     pure=n.pure, description=n.description) for n in self.registry.values()]

    def save(self, filename, project):
        # Drafts may be incomplete; only runnable graphs require Engine validation.
        project = upgrade_project(project)
        self.check_document(project)
        with self.lock:
            save_project(project, self.path(filename))
            save_project({"last_saved": filename}, self.state)

    def check_document(self, project):
        if not isinstance(project, dict) or project.get("version") != 1:
            raise ValueError("Expected an AutoFlow version 1 project")
        datasets.validate_all(project.get("datasets", {}))
        run_settings(project)
        graphs = project.get("graphs")
        if not isinstance(graphs, dict) or project.get("main") not in graphs:
            raise ValueError("Project must contain a main graph")
        for graph in graphs.values():
            if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), dict):
                raise ValueError("Each graph must contain a nodes object")
            if not isinstance(graph.get("parameters", {}), dict) or not isinstance(graph.get("outputs", {}), dict):
                raise ValueError("Graph parameters and outputs must be objects")
            for node in graph["nodes"].values():
                if not isinstance(node, dict) or node.get("type") not in self.registry:
                    raise ValueError("Project contains an unknown node type")
                if not isinstance(node.get("inputs", {}), dict) or not isinstance(node.get("next", {}), dict):
                    raise ValueError("Node inputs and next must be objects")
                if type(node.get('debug', False)) is not bool:
                    raise ValueError('Node debug must be a boolean')
                position = node.get("position", [0, 0])
                if not isinstance(position, list) or len(position) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) for v in position):
                    raise ValueError("Node position must be [x, y]")

    def event(self, kind, message):
        with self.lock:
            self.sequence += 1
            self.events.append(dict(id=self.sequence, kind=kind, message=str(message),
                                    time=time.strftime("%H:%M:%S")))

    def run(self, project, parameters):
        with self.lock:
            if self.running:
                raise ValueError("A graph is already running")
            self.check_document(project)
            self.active_settings = run_settings(project)
            self.engine = Engine(project, self.registry, self.projects,
                                 screen=self.screen_factory(self.projects),
                                 log=lambda message: self.event("print", message))
            run_id = uuid.uuid4().hex
            self.run_id = run_id
            self.running = True
            self.run_state = "running"
            self.event("info", "Run started · live desktop automation")
            def work():
                try:
                    self.engine.current_node = "Starting…"
                    self.engine.wait(self.active_settings["start_delay"])
                    result = self.engine.run(parameters)
                    self.engine.checkpoint()
                    self.run_state = "completed"
                    self.event("success", "Run complete" + (f" · {json.dumps(result)}" if result else ""))
                except Exception as exc:
                    self.run_state = "stopped" if self.engine.cancel.is_set() else "error"
                    self.event("error", exc)
                finally:
                    with self.lock:
                        self.results[run_id] = deepcopy(self.engine.project.get("datasets", {}))
                        while len(self.results) > 10: del self.results[next(iter(self.results))]
                        self.running = False
            threading.Thread(target=work, daemon=True).start()
            return run_id


def make_server(editor, port=8765):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, status, content, mime="application/json"):
            if mime == "application/json":
                content = json.dumps(content).encode()
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(content)

        def allowed(self):
            host = f"127.0.0.1:{self.server.server_port}"
            if self.headers.get("Host") != host:
                self.send(403, {"error": "Use the editor's 127.0.0.1 URL"})
                return False
            origin = self.headers.get("Origin")
            if origin and origin != f"http://{host}":
                self.send(403, {"error": "Cross-origin access is disabled"})
                return False
            return True

        def do_GET(self):
            if not self.allowed():
                return
            path = urlparse(self.path).path
            try:
                if path == "/api/bootstrap":
                    with editor.lock:
                        return self.send(200, editor.initial() | {"nodes": editor.catalog()})
                if path == "/api/files":
                    return self.send(200, {"files": sorted(p.name for p in editor.projects.glob("*.json") if not p.name.startswith(".")),
                                           "examples": sorted(p.name for p in (editor.root / "examples").glob("*.json"))})
                if path == "/api/texture-preview":
                    import io
                    from urllib.parse import parse_qs
                    from PIL import Image, ImageOps
                    query = parse_qs(urlparse(self.path).query)
                    texture = query.get("path", [""])[0]
                    if not texture:
                        raise ValueError("No texture selected")
                    with Image.open((editor.projects / texture).resolve()) as source:
                        preview = ImageOps.exif_transpose(source).convert("RGBA")
                        if query.get("thumbnail") == ["1"]:
                            preview.thumbnail((48, 48))
                        output = io.BytesIO()
                        preview.save(output, format="PNG")
                    return self.send(200, output.getvalue(), "image/png")
                if path == "/api/events":
                    from urllib.parse import parse_qs
                    cursor = int(parse_qs(urlparse(self.path).query).get("after", [0])[0])
                    with editor.lock:
                        # An open editor can retain its previous cursor when the
                        # Python server is restarted; resume without a page reload.
                        if cursor > editor.sequence:
                            cursor = 0
                        return self.send(200, {"events": [e for e in editor.events if e["id"] > cursor], "running": editor.running, "status": editor.status()})
                files = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css", "/editor-features.js": "editor-features.js"}
                if path in files:
                    file = STATIC / files[path]
                    return self.send(200, file.read_bytes(), mimetypes.guess_type(file)[0] or "text/plain")
                self.send(404, {"error": "Not found"})
            except Exception as exc:
                self.send(400, {"error": str(exc)})

        def do_POST(self):
            if not self.allowed():
                return
            try:
                if self.headers.get("Content-Type") != "application/json":
                    raise ValueError("Expected application/json")
                size = int(self.headers.get("Content-Length", 0))
                if not 0 < size <= 64_000_000:
                    raise ValueError("Request must be between 1 byte and 64 MB")
                data = json.loads(self.rfile.read(size))
                if "project" in data:
                    data["project"] = upgrade_project(data["project"])
                path = urlparse(self.path).path
                if path == "/api/save":
                    editor.save(data["filename"], data["project"])
                    result = {"filename": data["filename"]}
                elif path == "/api/load":
                    source = editor.path(data["filename"])
                    if data.get("example"):
                        source = editor.root / "examples" / source.name
                    project = load_project(source)
                    editor.check_document(project)
                    if data.get("example"):
                        for graph in project["graphs"].values():
                            for node in graph["nodes"].values():
                                path = node.get("inputs", {}).get("path")
                                if node["type"] == "LoadCSVFromFile" and isinstance(path, str) and not Path(path).is_absolute():
                                    node["inputs"]["path"] = "../examples/" + path
                    result = {"project": project, "filename": data["filename"], "saved": not data.get("example", False)}
                elif path == "/api/import":
                    editor.check_document(data["project"])
                    result = {"project": data["project"]}
                elif path == "/api/run":
                    result = {"run_id": editor.run(data["project"], data.get("parameters", {}))}
                elif path == "/api/run-result":
                    with editor.lock:
                        result = {"datasets": editor.results.get(data["run_id"])}
                elif path == "/api/dataset-import":
                    table, sheets = datasets.read(base64.b64decode(data["content"], validate=True), Path(data["name"]).suffix, data.get("sheet"))
                    result = {"dataset": table, "sheets": sheets}
                elif path == "/api/dataset-export":
                    result = {"content": base64.b64encode(datasets.write(data["dataset"], data["extension"])).decode()}
                elif path == "/api/dataset-sort":
                    table = datasets.validate(data["dataset"])
                    datasets.sort(table, data["column"], data.get("descending", False))
                    result = {"dataset": table}
                elif path == "/api/export":
                    editor.check_document(data["project"])
                    result = {"content": base64.b64encode(bundles.export(data["project"], editor.projects)).decode()}
                elif path == "/api/bundle-import":
                    result = {"project": bundles.unpack(base64.b64decode(data["content"], validate=True), editor.projects, editor.check_document)}
                elif path == "/api/manual-response":
                    with editor.lock:
                        if not editor.running or not editor.engine:
                            raise ValueError("No graph is running")
                        editor.engine.answer_manual(data["id"], data["choice"])
                    result = {"ok": True}
                elif path == '/api/debug-continue':
                    with editor.lock:
                        if not editor.running or not editor.engine:
                            raise ValueError('No graph is running')
                        editor.engine.continue_debug(data['id'], data.get('delay', 0))
                    result = {'ok': True}
                elif path == '/api/debug-capture':
                    with editor.lock:
                        if not editor.running or not editor.engine:
                            raise ValueError('No graph is running')
                        result = {'edit': editor.engine.capture_debug_offset(data['id'])}
                elif path == "/api/pause":
                    with editor.lock:
                        if editor.running and editor.engine:
                            editor.engine.toggle_pause()
                    result = {"ok": True}
                elif path == "/api/stop":
                    with editor.lock:
                        if editor.engine:
                            editor.engine.cancel.set()
                    result = {"ok": True}
                elif path == "/api/texture":
                    extension = Path(data["name"]).suffix.lower()
                    if extension not in (".png", ".jpg", ".jpeg", ".bmp", ".webp"):
                        raise ValueError("Choose a PNG, JPEG, BMP or WebP image")
                    raw = base64.b64decode(data["content"], validate=True)
                    result = {"path": store_texture(raw, editor.projects / "assets")}
                elif path == "/api/clipboard":
                    result = {"path": clipboard_texture(editor.projects / "assets")}
                else:
                    return self.send(404, {"error": "Not found"})
                self.send(200, result)
            except Exception as exc:
                self.send(400, {"error": str(exc)})

    class LocalServer(ThreadingHTTPServer):
        # Windows SO_REUSEADDR otherwise allows two editor instances to bind the
        # same port, unpredictably serving a stale node registry after updates.
        allow_reuse_address = False

        def server_bind(self):
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            super().server_bind()

    return LocalServer(("127.0.0.1", port), Handler)


def serve(port=8765, open_browser=True):
    server = make_server(Editor(), port)
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"AutoFlow editor: {url}\nKeep this window open. Ctrl+C stops the server.", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    finally:
        server.server_close()
