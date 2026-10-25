import csv
import math
from autoflow.registry import NodeType
from autoflow.nodes.math_nodes import integer, point


def load_csv(ctx, node_id, inputs):
    path = ctx.engine.base_dir / inputs["path"]
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return {"rows": rows}, "then"


def for_each(ctx, node_id, inputs):
    items = inputs["items"]
    if not isinstance(items, (list, tuple, set, dict)):
        raise ValueError("items must be a list, tuple, set or dict")
    from autoflow.loops import iterate
    items = list(items)
    count = len(items)
    return iterate(ctx, node_id, ({"item": item, "index": index, "count": count}
                                  for index, item in enumerate(items)),
                   lambda: {"item": None, "index": None, "count": count}, inputs['max_iterations'])


def call_function(ctx, node_id, inputs):
    return {"result": ctx.engine.call(inputs["graph"], inputs["arguments"], ctx.depth + 1)}, "then"


def log(ctx, node_id, inputs):
    ctx.engine.log(str(inputs["message"]))
    return {}, "then"


def wait(ctx, node_id, inputs):
    milliseconds = integer(inputs["milliseconds"])
    if milliseconds < 0:
        raise ValueError("milliseconds must be nonnegative")
    ctx.engine.wait(milliseconds / 1000)
    ctx.check()
    return {}, "then"


def offset(ctx, node_id, inputs):
    p, delta = point(inputs["point"]), point(inputs["offset"])
    return {"point": {"x": p["x"] + delta["x"], "y": p["y"] + delta["y"]}}, "then"


NODES = [
    NodeType("LoadCSVFromFile", {"path": "string"}, {"rows": "reference:list"}, ("then",), load_csv),
    NodeType("ForEach", {"items": "reference", "max_iterations": "integer"}, {"item": "reference", "index": "integer?", "count": "integer"},
             ("body", "completed"), for_each, defaults={'max_iterations': 10000}, category="Loops"),
    NodeType("CallFunction", {"graph": "string", "arguments": "dict"}, {"result": "dict"}, ("then",), call_function),
    NodeType("Log", {"message": "reference"}, {}, ("then",), log),
    NodeType("Wait", {"milliseconds": "integer"}, {}, ("then",), wait, defaults={"milliseconds": 500}),
    NodeType("Offset", {"point": "reference:Point", "offset": "reference:Point"}, {"point": "reference:Point"}, ("then",), offset,
             defaults={"point": {"x": 0, "y": 0}, "offset": {"x": 50, "y": 50}}),
]
