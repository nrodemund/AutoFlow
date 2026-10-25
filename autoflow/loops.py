"""Shared loop execution and nearest-loop break/continue control."""


class LoopSignal(Exception):
    def __init__(self, action): self.action = action


def iterate(ctx, node_id, values, completed, max_iterations=10000):
    if type(max_iterations) is not int or max_iterations < 1:
        raise ValueError('Max iterations must be a positive integer')
    upstream = dict(ctx.values)
    ctx.loop_depth += 1
    try:
        for iteration, outputs in enumerate(values, 1):
            ctx.check()
            if iteration > max_iterations:
                raise ValueError(f'Loop iteration limit reached ({max_iterations}); increase Max iterations on this loop')
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
