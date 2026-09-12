"""Python value constructors and explicit conversions."""
import operator
from autoflow.datatypes import convert
from autoflow.registry import NodeType


NODES = [NodeType(name, {'value': kind}, {'value': kind}, (),
                  lambda c, n, i: ({'value': i['value']}, None),
                  defaults={'value': default}, pure=True, category='Values')
         for name, kind, default in [
             ('Bool', 'bool', False), ('Integer', 'integer', 0), ('Float', 'float', 0.0),
             ('String', 'string', ''), ('Bytes', 'bytes', b''), ('Set', 'set', set()),
             ('Dict', 'dict', {}), ('Tuple', 'reference:tuple', ())]]


def conversion(kind):
    def execute(context, node_id, inputs):
        value = inputs['value']
        result = set(value) if kind == 'set' else dict(value) if kind == 'dict' else convert(value, kind)
        return {'value': result}, None
    return execute


NODES += [NodeType('To' + kind.title(), {'value': 'reference'}, {'value': kind}, (), conversion(kind),
                   pure=True, category='Conversions', defaults={'value': default})
          for kind, default in [('bool', False), ('integer', 0), ('float', 0.0), ('string', ''),
                                ('bytes', ''), ('set', []), ('dict', {})]]


def arithmetic(operation):
    return lambda c, n, i: ({'result': operation(i['a'], i['b'])}, None)


NODES += [NodeType(name + 'Float', {'a': 'float', 'b': 'float'}, {'result': 'float'}, (),
                   arithmetic(operation), defaults={'a': 0.0, 'b': 1.0}, pure=True, category='Math')
          for name, operation in [('Add', operator.add), ('Subtract', operator.sub),
                                  ('Multiply', operator.mul), ('Divide', operator.truediv)]]
