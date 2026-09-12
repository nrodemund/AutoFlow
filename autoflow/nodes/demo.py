"""Editor demonstration nodes; math nodes are evaluated from their data pins."""
from autoflow.registry import NodeType


def add_int(context, node_id, inputs):
    if any(type(inputs[key]) is not int for key in ("a", "b")):
        raise ValueError("Add (Int) accepts integers only")
    return {"result": inputs["a"] + inputs["b"]}, None


def print_value(context, node_id, inputs):
    context.engine.log(str(inputs["value"]))
    return {}, "then"


NODES = [
    NodeType("Start", {}, {}, ("then",), lambda c, n, i: ({}, "then"),
             title="Start", category="Flow"),
    NodeType("AddInt", {"a": "integer", "b": "integer"}, {"result": "integer"}, (),
             add_int, defaults={"a": 2, "b": 3}, pure=True, title="Add (Int)", category="Math"),
    NodeType("Print", {"value": "reference"}, {}, ("then",), print_value,
             defaults={"value": "Hello, AutoFlow!"}, title="Print", category="Console"),
]
