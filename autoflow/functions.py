"""Function signatures determine the pins of parameter, call and return nodes."""
from autoflow.registry import NodeType


class ReturnSignal(Exception):
    def __init__(self, values): self.values = values


def definition(project, graph, node, registry):
    kind = node.get('type')
    if kind == 'FunctionParameter':
        name = node.get('parameter')
        if name not in graph.get('parameters', {}): raise ValueError(f'Unknown function parameter: {name}')
        return NodeType(kind, {}, {'value': graph['parameters'][name]}, (),
                        lambda c, n, i: ({'value': c.parameters[name]}, None), pure=True)
    if kind == 'FunctionCall':
        name = node.get('function')
        if name not in project['graphs']: raise ValueError(f'Unknown function: {name}')
        target = project['graphs'][name]
        outputs = target.get('return_types', {key: 'reference' for key in target.get('outputs', {})})
        return NodeType(kind, target.get('parameters', {}), outputs, ('then',),
                        lambda c, n, i: (c.engine.call(name, i, c.depth + 1), 'then'))
    if kind == 'FunctionReturn':
        def finish(c, n, i): raise ReturnSignal(i)
        return NodeType(kind, graph.get('return_types', {}), {}, (), finish)
    return registry.get(kind)
