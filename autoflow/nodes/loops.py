"""Range, counted, conditional and dataset row iteration."""
from copy import deepcopy
from autoflow.registry import NodeType
from autoflow.loops import iterate, LoopSignal
from autoflow.datatypes import checked


def for_loop(ctx, node_id, inputs):
    if inputs['step'] == 0: raise ValueError('Step must not be zero')
    values = range(inputs['start'], inputs['stop'], inputs['step'])
    count = len(values)
    return iterate(ctx, node_id, ({'index': i, 'count': count} for i in values),
                   lambda: {'index': None, 'count': count}, inputs['max_iterations'])


def repeat(ctx, node_id, inputs):
    if inputs['count'] < 0: raise ValueError('Count must not be negative')
    return for_loop(ctx, node_id, {'start': 0, 'stop': inputs['count'], 'step': 1,
                                  'max_iterations': inputs['max_iterations']})


def while_loop(ctx, node_id, inputs):
    if inputs['max_iterations'] < 1: raise ValueError('Max iterations must be positive')
    count = 0
    def values():
        nonlocal count
        while True:
            ctx.check()
            if not checked(ctx.resolve(inputs['condition']), 'bool'): return
            index = count
            count += 1
            yield {'index': index, 'count': count}
    return iterate(ctx, node_id, values(), lambda: {'index': None, 'count': count}, inputs['max_iterations'])


def for_each_row(ctx, node_id, inputs):
    # Snapshot guarantees a finite, stable traversal when the body edits the table.
    rows = deepcopy(inputs['dataset']['rows'])
    count = len(rows)
    return iterate(ctx, node_id, ({'row': row, 'index': index, 'count': count}
                                  for index, row in enumerate(rows)),
                   lambda: {'row': None, 'index': None, 'count': count}, inputs['max_iterations'])


def control(action):
    def run(ctx, node_id, inputs):
        if not ctx.loop_depth: raise ValueError(f'{action.title()} requires an active loop')
        raise LoopSignal(action)
    return run


NODES = [
    NodeType('ForLoop', {'start': 'integer', 'stop': 'integer', 'step': 'integer', 'max_iterations': 'integer'},
             {'index': 'integer?', 'count': 'integer'}, ('body', 'completed'), for_loop,
             'Python range: start inclusive, stop exclusive. Step can be negative.',
             defaults={'start': 0, 'stop': 10, 'step': 1, 'max_iterations': 10000}, title='For Loop', category='Loops'),
    NodeType('Repeat', {'count': 'integer', 'max_iterations': 'integer'}, {'index': 'integer?', 'count': 'integer'},
             ('body', 'completed'), repeat, 'Repeat Count times, with a zero-based index.',
             defaults={'count': 5, 'max_iterations': 10000}, category='Loops'),
    NodeType('WhileLoop', {'condition': 'bool', 'max_iterations': 'integer'},
             {'index': 'integer?', 'count': 'integer'}, ('body', 'completed'), while_loop,
             'Reevaluate Condition before each iteration. The limit raises an error if still true.',
             defaults={'condition': False, 'max_iterations': 10000}, deferred_inputs=('condition',),
             title='While Loop', category='Loops'),
    NodeType('ForEachRow', {'dataset': 'reference:Dataset', 'max_iterations': 'integer'},
             {'row': 'dict?', 'index': 'integer?', 'count': 'integer'}, ('body', 'completed'), for_each_row,
             'Iterate a snapshot of dataset rows. Index refers to the original row order; avoid sorting/deleting while editing by index.',
             defaults={'max_iterations': 10000}, title='For Each Row', category='Datasets'),
    NodeType('Break', {}, {}, (), control('break'), 'Exit the nearest loop and follow its Completed flow.', category='Loops'),
    NodeType('Continue', {}, {}, (), control('continue'), 'Skip the rest of the nearest loop body.', category='Loops'),
    NodeType('If', {'condition': 'bool'}, {}, ('true', 'false'),
             lambda c, n, i: ({}, 'true' if i['condition'] else 'false'),
             defaults={'condition': False}, category='Flow'),
]
