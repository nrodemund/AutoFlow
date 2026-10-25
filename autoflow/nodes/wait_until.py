"""Bounded polling with a re-evaluated boolean input and per-attempt execution."""
import math
import time
from autoflow.registry import NodeType


def wait_until(ctx, node_id, inputs):
    interval, attempts = inputs["interval_ms"], inputs["max_attempts"]
    if type(interval) is not int or interval < 0:
        raise ValueError("Loop interval must be a finite nonnegative number of milliseconds")
    if type(attempts) is not int or attempts < 1:
        raise ValueError("Max attempts must be a positive integer")
    upstream = dict(ctx.values)
    next_check = time.monotonic()
    for attempt in range(1, attempts + 1):
        if attempt > 1:
            ctx.engine.cancel.wait(max(0, next_check - time.monotonic()))
        ctx.check()
        next_check = time.monotonic() + interval / 1000
        # The loop body may produce the condition. Pure conditions are evaluated
        # only here, once per attempt, rather than eagerly before the loop.
        ctx.values = dict(upstream)
        ctx.values[node_id] = {"attempt": attempt, "matched": False}
        ctx.branch(node_id, "loop")
        matched = ctx.resolve(inputs["condition"])
        if type(matched) is not bool:
            raise ValueError("Condition must evaluate to a boolean")
        ctx.check()
        if matched:
            ctx.values = upstream
            return {"attempt": attempt, "matched": True}, "true"
    ctx.values = upstream
    return {"attempt": attempts, "matched": False}, "false"


NODES = [NodeType(
    "WaitUntil", {"condition": "bool", "interval_ms": "integer", "max_attempts": "integer"},
    {"attempt": "integer", "matched": "bool"}, ("true", "false", "loop"), wait_until,
    "Check immediately, then retry at the loop interval. Loop runs before each check; True succeeds, False means attempts exhausted.",
    defaults={"condition": False, "interval_ms": 500, "max_attempts": 5},
    title="Wait Until", category="Flow", deferred_inputs=("condition",))]
