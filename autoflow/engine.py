"""Synchronous execution with separate execution pins and data references."""
from autoflow import datatypes as json
import threading
import time
from pathlib import Path
from autoflow.migrations import upgrade_project
from autoflow.datatypes import checked, Point
from autoflow.datasets import Dataset
from autoflow.loops import LoopSignal
from autoflow.functions import definition, ReturnSignal


class GraphError(ValueError):
    pass


class SimulationScreen:
    """Deterministic demo backend. Never reads or changes the desktop."""
    def find(self, texture, confidence=.97):
        return None

    def find_text(self, text, start, end, language="", cancel=None, case_sensitive=True):
        return None

    def click(self, x, y):
        return f"SIMULATED click at ({x}, {y})"

    def move(self, point): self._cursor = dict(point)
    def cursor_position(self): return dict(getattr(self, '_cursor', {'x': 0, 'y': 0}))
    def drag(self, start, end, duration, cancel): pass
    def key_press(self, keys): pass
    def copy(self, cancel): return ""
    def paste(self, text, use_clipboard): pass


def load_project(path):
    with Path(path).open(encoding="utf-8") as handle:
        return upgrade_project(json.load(handle))


def save_project(project, path):
    """Atomic save; editor node positions and extra metadata are preserved."""
    import os
    import tempfile
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                         delete=False, suffix=".tmp") as handle:
            name = handle.name
            json.dump(project, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(name, target)
    finally:
        if name and Path(name).exists():
            Path(name).unlink()


class Engine:
    def __init__(self, project, registry, base_dir=".", screen=None, log=print,
                 max_steps=10000, max_depth=32):
        self.project, self.registry = upgrade_project(project), registry
        self.base_dir = Path(base_dir).resolve()
        self.screen = screen or SimulationScreen()
        self.log = log
        self.max_steps, self.max_depth = max_steps, max_depth
        self.steps = 0
        self.cancel = threading.Event()
        self.resumed = threading.Event()
        self.resumed.set()
        self.paused = False
        self.current_node = ""
        self.manual_request = None
        self.manual_lock = threading.Lock()
        self.debug_request = None
        self.debug_lock = threading.Lock()
        self.debug_edits = []
        self._debug_runtime = None
        self.status_text = ""
        self.validate()

    def manual_interaction(self, prompt):
        import uuid
        request = {"id": uuid.uuid4().hex, "prompt": prompt, "choice": None}
        with self.manual_lock:
            self.manual_request = request
        try:
            while True:
                if self.cancel.wait(.05):
                    raise GraphError("Execution cancelled")
                with self.manual_lock:
                    if request["choice"] is not None:
                        return request["choice"]
        finally:
            with self.manual_lock:
                self.manual_request = None

    def answer_manual(self, request_id, choice):
        if choice not in ("success", "failed"):
            raise ValueError("Choose Continue or Ignore")
        with self.manual_lock:
            request = self.manual_request
            if not request or request["id"] != request_id or request["choice"] is not None:
                raise ValueError("This manual interaction is no longer waiting")
            request["choice"] = choice

    def debug_node(self, context, node_id, kind, inputs):
        import uuid
        from autoflow.debugging import describe_inputs
        self.checkpoint()
        preview = ''
        update = kind.debug_update
        if kind.debug_preview:
            try:
                preview = kind.debug_preview(context, node_id, inputs) or ''
            except Exception as error:
                preview = f'Preview failed: {error}'
                update = None
        request = dict(id=uuid.uuid4().hex, node=node_id,
                       graph=next(name for name, graph in self.project['graphs'].items() if graph is context.graph),
                       title=context.graph['nodes'][node_id].get('title') or kind.title or kind.name,
                       inputs=describe_inputs(inputs, kind.deferred_inputs), preview=preview, continued=False,
                       can_capture=kind.name == 'OffsetPoint', resume_at=0)
        with self.debug_lock:
            self.debug_request = request
            self._debug_runtime = (context, kind, inputs)
        try:
            while True:
                if self.cancel.wait(.05):
                    raise GraphError('Execution cancelled')
                with self.debug_lock:
                    if request['continued'] and time.monotonic() >= request['resume_at']:
                        return
                if update:
                    try:
                        preview = update(context, node_id, inputs)
                    except Exception as error:
                        preview = f'Live preview unavailable: {error}'
                        update = None
                    with self.debug_lock:
                        request['preview'] = preview
        finally:
            with self.debug_lock:
                self.debug_request = None
                self._debug_runtime = None

    def continue_debug(self, request_id, delay=0):
        if type(delay) not in (int, float) or delay not in (0, 2):
            raise ValueError('Debug resume delay must be 0 or 2 seconds')
        with self.debug_lock:
            request = self.debug_request
            if not request or request['id'] != request_id or request['continued']:
                raise ValueError('This debug breakpoint is no longer waiting')
            request['continued'] = True
            request['resume_at'] = time.monotonic() + delay

    def capture_debug_offset(self, request_id):
        from copy import deepcopy
        from autoflow.debugging import describe_inputs
        with self.debug_lock:
            request = self.debug_request
            if not request or request['id'] != request_id or request['continued'] or self.cancel.is_set():
                raise ValueError('This debug breakpoint is no longer waiting')
            if not request['can_capture']:
                raise ValueError('Capture offset is only available for Offset Point')
            context, kind, inputs = self._debug_runtime
            cursor = checked(self.screen.cursor_position(), 'reference:Point')
            origin = inputs['point']
            changes = {'x': cursor.x - origin['x'], 'y': cursor.y - origin['y']}
            node = context.graph['nodes'][request['node']]
            previous = {key: deepcopy(node.get('inputs', {}).get(key, 0)) for key in changes}
            node.setdefault('inputs', {}).update(changes)
            inputs.update(changes)
            request['inputs'] = describe_inputs(inputs, kind.deferred_inputs)
            request['captured'] = changes
            edit = dict(id=len(self.debug_edits) + 1, graph=request['graph'], node=request['node'],
                        previous=previous, changes=changes)
            self.debug_edits.append(edit)
            return deepcopy(edit)

    def toggle_pause(self):
        if self.manual_request is not None or self.debug_request is not None:
            return  # Pause shortcut must never acknowledge a manual decision.
        if self.resumed.is_set():
            self.resumed.clear()
        else:
            self.resumed.set()

    def checkpoint(self):
        try:
            while not self.resumed.is_set():
                self.paused = True
                if self.cancel.wait(.05):
                    raise GraphError("Execution cancelled")
            if self.cancel.is_set():
                raise GraphError("Execution cancelled")
        finally:
            self.paused = False

    def wait(self, seconds):
        remaining = seconds
        while remaining > 0:
            self.checkpoint()
            began = time.monotonic()
            self.cancel.wait(min(.05, remaining))
            remaining -= time.monotonic() - began
        self.checkpoint()

    def validate(self):
        from autoflow.datasets import validate_all
        validate_all(self.project.get("datasets", {}))
        if self.project.get("version") != 1:
            raise GraphError("Expected project version 1")
        graphs = self.project.get("graphs", {})
        if self.project.get("main") not in graphs:
            raise GraphError("Main graph does not exist")
        for name, graph in graphs.items():
            nodes = graph.get("nodes", {})
            if graph.get("entry") not in nodes:
                raise GraphError(f"{name}: entry does not exist")
            for node_id, node in nodes.items():
                if type(node.get('debug', False)) is not bool:
                    raise GraphError(f'{name}/{node_id}: debug must be a boolean')
                kind = definition(self.project, graph, node, self.registry)
                if kind is None:
                    raise GraphError(f"{name}/{node_id}: unknown node type")
                inputs = node.get("inputs", {})
                missing = set(kind.inputs) - set(inputs) - set(kind.defaults)
                extra = set(inputs) - set(kind.inputs)
                if missing or extra:
                    raise GraphError(f"{name}/{node_id}: missing inputs {missing}, unknown inputs {extra}")
                for pin, target in node.get("next", {}).items():
                    if pin not in kind.flows or target not in nodes:
                        raise GraphError(f"{name}/{node_id}: invalid flow {pin} -> {target}")
                self._validate_values(inputs, graph, name)
            self._validate_values(graph.get("outputs", {}), graph, name)

    def _validate_values(self, value, graph, name):
        if isinstance(value, dict):
            if set(value) == {"ref"}:
                ref = value["ref"]
                if not isinstance(ref, list) or len(ref) != 2:
                    raise GraphError(f"{name}: reference must be [node, output]")
                node_id, pin = ref
                node = graph["nodes"].get(node_id)
                kind = definition(self.project, graph, node, self.registry) if node else None
                if not kind or pin not in kind.outputs:
                    raise GraphError(f"{name}: invalid data reference {ref}")
            elif set(value) == {"param"}:
                if value["param"] not in graph.get("parameters", {}):
                    raise GraphError(f"{name}: unknown parameter {value['param']}")
            else:
                for child in value.values():
                    self._validate_values(child, graph, name)
        elif isinstance(value, list):
            for child in value:
                self._validate_values(child, graph, name)

    def run(self, parameters=None):
        self.steps = 0
        main = self.project['graphs'][self.project['main']]
        arguments = main.get('parameter_defaults', {}) | (parameters or {})
        return self.call(self.project["main"], arguments, 0)

    def call(self, name, parameters, depth):
        if depth >= self.max_depth:
            raise GraphError("Function depth limit reached")
        if name not in self.project["graphs"]:
            raise GraphError(f"Unknown function graph: {name}")
        graph = self.project["graphs"][name]
        expected = set(graph.get("parameters", {}))
        if set(parameters) != expected:
            raise GraphError(f"{name}: expected parameters {sorted(expected)}")
        parameters = {key: checked(value, graph['parameters'][key]) for key, value in parameters.items()}
        context = Context(self, graph, parameters, depth)
        try:
            context.walk(graph["entry"])
            result = context.resolve(graph.get("outputs", {}))
        except ReturnSignal as returned:
            result = returned.values
        types = graph.get('return_types')
        if types is not None:
            if set(result) != set(types): raise GraphError(f'{name}: connect and execute a Return node for {sorted(types)}')
            result = {key: checked(value, types[key]) for key, value in result.items()}
        return result


class Context:
    def __init__(self, engine, graph, parameters, depth):
        self.engine, self.graph, self.parameters, self.depth = engine, graph, parameters, depth
        self.values = {}
        self.evaluating = set()
        self.loop_depth = 0

    def resolve(self, value):
        if isinstance(value, (Point, Dataset)): return value
        if isinstance(value, dict):
            if set(value) == {"ref"}:
                node, pin = value["ref"]
                producer = definition(self.engine.project, self.graph, self.graph["nodes"][node], self.engine.registry)
                if producer.pure:
                    if node in self.evaluating:
                        raise GraphError("Circular pure-node data connection")
                    self.evaluating.add(node)
                    try:
                        self.execute(node)
                    finally:
                        self.evaluating.remove(node)
                try:
                    return self.values[node][pin]
                except KeyError as exc:
                    raise GraphError(f"Output {node}.{pin} is unavailable; execute its producer first") from exc
            if set(value) == {"param"}:
                return self.parameters[value["param"]]
            return {key: self.resolve(child) for key, child in value.items()}
        if isinstance(value, list):
            return [self.resolve(child) for child in value]
        return value

    def check(self):
        self.engine.checkpoint()

    def walk(self, node_id):
        visits = {}
        while node_id:
            self.check()
            visits[node_id] = visits.get(node_id, 0) + 1
            if visits[node_id] > self.engine.max_steps:
                raise GraphError(f'Execution flow cycle limit reached at {node_id} ({self.engine.max_steps} visits)')
            node = self.graph["nodes"][node_id]
            flow = self.execute(node_id)
            node_id = node.get("next", {}).get(flow)

    def tick(self):
        self.check()
        self.engine.steps += 1

    def execute(self, node_id):
        self.tick()
        node = self.graph["nodes"][node_id]
        kind = definition(self.engine.project, self.graph, node, self.engine.registry)
        try:
            inputs = {key: value if key in kind.deferred_inputs else self.resolve(value)
                      for key, value in (kind.defaults | node.get("inputs", {})).items()}
            inputs = {key: value if key in kind.deferred_inputs else checked(value, kind.inputs[key]) for key, value in inputs.items()}
            self.check()
            if not kind.pure:
                self.engine.current_node = f"{node_id} · {kind.title or kind.name}"
            if node.get('debug', False):
                self.engine.current_node = f"{node_id} · {kind.title or kind.name}"
                self.engine.debug_node(self, node_id, kind, inputs)
                self.check()
            outputs, flow = kind.execute(self, node_id, inputs)
            if set(outputs) != set(kind.outputs) or (flow is not None and flow not in kind.flows):
                raise GraphError(f"Invalid result from node type {kind.name}")
            self.values[node_id] = {key: checked(value, kind.outputs[key]) for key, value in outputs.items()}
            return flow
        except (LoopSignal, ReturnSignal):
            raise
        except Exception as exc:
            raise GraphError(f"Node {node_id} ({kind.name}): {exc}") from exc

    def branch(self, node_id, flow):
        self.walk(self.graph["nodes"][node_id].get("next", {}).get(flow))
