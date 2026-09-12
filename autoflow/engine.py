"""Synchronous execution with separate execution pins and data references."""
from autoflow import datatypes as json
import threading
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

    def find_text(self, text, start, end, language="", cancel=None):
        return None

    def click(self, x, y):
        return f"SIMULATED click at ({x}, {y})"

    def move(self, point): pass
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
        self.validate()

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
        return self.call(self.project["main"], parameters or {}, 0)

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
        if self.engine.cancel.is_set():
            raise GraphError("Execution cancelled")

    def walk(self, node_id):
        while node_id:
            node = self.graph["nodes"][node_id]
            flow = self.execute(node_id)
            node_id = node.get("next", {}).get(flow)

    def tick(self):
        self.check()
        self.engine.steps += 1
        if self.engine.steps > self.engine.max_steps:
            raise GraphError("Execution step limit reached")

    def execute(self, node_id):
        self.tick()
        node = self.graph["nodes"][node_id]
        kind = definition(self.engine.project, self.graph, node, self.engine.registry)
        try:
            inputs = {key: value if key in kind.deferred_inputs else self.resolve(value)
                      for key, value in (kind.defaults | node.get("inputs", {})).items()}
            inputs = {key: value if key in kind.deferred_inputs else checked(value, kind.inputs[key]) for key, value in inputs.items()}
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
