"""Poll two boolean conditions until A, B, or the time limit wins."""
import time
from autoflow.registry import NodeType
from autoflow.nodes.math_nodes import integer
from autoflow.engine import GraphError


def wait_ab(ctx, node_id, inputs):
    interval, timeout = integer(inputs["interval_ms"]), integer(inputs["timeout_ms"])
    if interval < 1 or timeout < 0:
        raise ValueError("Interval must be at least 1 ms; timeout must be nonnegative")
    start = time.monotonic()
    attempt = 0
    while True:
        ctx.check()
        ctx.engine.steps += 1
        if ctx.engine.steps > ctx.engine.max_steps:
            raise GraphError("Execution step limit reached")
        attempt += 1
        next_check = time.monotonic() + interval / 1000
        for name in ("a", "b"):
            result = ctx.resolve(inputs[name])
            if type(result) is not bool:
                raise ValueError(f"Condition {name.upper()} must evaluate to a boolean")
            ctx.check()
            if result:
                return {"attempt": attempt, "elapsed_ms": int((time.monotonic() - start) * 1000)}, name
        now = time.monotonic()
        if now - start >= timeout / 1000:
            return {"attempt": attempt, "elapsed_ms": int((now - start) * 1000)}, "timeout"
        ctx.engine.cancel.wait(max(0, min(next_check, start + timeout / 1000) - now))


NODES = [NodeType(
    "WaitUntilAB", {"a": "bool", "b": "bool", "interval_ms": "integer", "timeout_ms": "integer"},
    {"attempt": "integer", "elapsed_ms": "integer"}, ("a", "b", "timeout"), wait_ab,
    "Recheck A, then B, until one is true or time expires. A wins if both are true. First check is immediate.",
    defaults={"a": False, "b": False, "interval_ms": 500, "timeout_ms": 5000},
    title="Wait Until A/B", category="Flow", deferred_inputs=("a", "b"))]
