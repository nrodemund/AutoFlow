"""Shared loop execution and nearest-loop break/continue control."""


class LoopSignal(Exception):
    def __init__(self, action): self.action = action


def iterate(ctx, node_id, values, completed):
    upstream = dict(ctx.values)
    ctx.loop_depth += 1
    try:
        for outputs in values:
            ctx.tick()
            ctx.values = dict(upstream)
            ctx.values[node_id] = outputs
            try:
                ctx.branch(node_id, 'body')
            except LoopSignal as signal:
                if signal.action == 'break': break
    finally:
        ctx.loop_depth -= 1
        ctx.values = upstream
    return completed(), 'completed'
