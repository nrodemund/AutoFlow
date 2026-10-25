"""Select a value using a boolean condition."""
from autoflow.registry import NodeType


def select(ctx, node_id, inputs):
    pin = 'when_true' if inputs['condition'] else 'when_false'
    return {'result': ctx.resolve(inputs[pin])}, None


NODES = [NodeType(
    'Select', {'condition': 'bool', 'when_true': 'reference', 'when_false': 'reference'},
    {'result': 'reference'}, (), select,
    'Return When true if Condition is true, otherwise When false. Only the selected input is evaluated. Accepts any value type.',
    defaults={'condition': False, 'when_true': '', 'when_false': ''},
    pure=True, title='Select', category='Data', deferred_inputs=('when_true', 'when_false'))]
