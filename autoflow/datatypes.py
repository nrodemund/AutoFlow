"""Shared Python value types and safe JSON representations for non-JSON values."""
import base64
import json
import math

SCALARS = ('bool', 'integer', 'float', 'string', 'bytes')
ALIASES = {'boolean': 'bool', 'int': 'integer', 'str': 'string', 'text': 'string',
           'number': 'float', 'object': 'dict', 'array': 'reference:list',
           'point': 'reference:Point', 'any': 'reference'}


class Point(dict):
    """A custom point object retaining mapping access for desktop backends."""
    def __init__(self, x=0, y=0):
        if type(x) is not int or type(y) is not int: raise ValueError('Point coordinates must be integer')
        super().__init__(x=x, y=y)

    x = property(lambda self: self['x'])
    y = property(lambda self: self['y'])


def checked(value, kind):
    kind = canonical(kind)
    if kind.endswith('?') and value is None: return None
    kind = kind.rstrip('?')
    if kind == 'reference': return value
    if kind == 'reference:Point':
        if isinstance(value, Point): return value
        if isinstance(value, dict) and set(value) == {'x', 'y'}: return Point(**value)
    expected = {'bool': bool, 'integer': int, 'float': float, 'string': str, 'bytes': bytes,
                'set': set, 'dict': dict, 'reference:list': list, 'reference:tuple': tuple}.get(kind)
    if kind == 'float' and type(value) is int: return float(value)
    if expected and type(value) is expected:
        if kind == 'float' and not math.isfinite(value): raise ValueError('Expected finite float')
        return value
    if kind.startswith('reference:') and kind[10:] in (type(value).__name__, type(value).__module__ + '.' + type(value).__qualname__): return value
    raise ValueError(f'Expected {kind}, got {type(value).__name__}')


def canonical(name):
    if not isinstance(name, str): raise ValueError('Type names must be strings')
    optional = name.endswith('?')
    base = name.rstrip('?')
    return ALIASES.get(base, base) + ('?' if optional else '')


def convert(value, kind):
    kind = canonical(kind)
    if kind == 'string': return '' if value is None else str(value)
    if kind == 'bytes':
        if isinstance(value, bytes): return value
        if isinstance(value, str): return value.encode('utf-8')
        raise ValueError('Expected bytes or a UTF-8 string')
    if kind == 'bool':
        if type(value) is bool: return value
        if isinstance(value, str) and value.lower() in ('true', 'false'): return value.lower() == 'true'
        raise ValueError('Expected true or false')
    if kind in ('integer', 'float'):
        if isinstance(value, bool) or value is None: raise ValueError(f'Expected {kind}')
        if kind == 'integer':
            if isinstance(value, float) and not value.is_integer(): raise ValueError('Expected integer')
            return int(value)
        result = float(value)
        if not math.isfinite(result): raise ValueError('Expected finite float')
        return result
    raise ValueError(f'Unsupported scalar type: {kind}')


def encode(value):
    if isinstance(value, Point): return {'$type': 'Point', 'value': dict(value)}
    if isinstance(value, bytes): return {'$type': 'bytes', 'value': base64.b64encode(value).decode('ascii')}
    if isinstance(value, (set, tuple)):
        return {'$type': 'set' if isinstance(value, set) else 'tuple', 'value': [encode(v) for v in value]}
    if isinstance(value, list): return [encode(v) for v in value]
    if isinstance(value, dict):
        if not all(isinstance(k, str) for k in value) or set(value) == {'$type', 'value'}:
            return {'$type': 'dict', 'value': [[encode(k), encode(v)] for k, v in value.items()]}
        return {k: encode(v) for k, v in value.items()}
    return value


def decode(value):
    if isinstance(value, list): return [decode(v) for v in value]
    if isinstance(value, dict):
        if set(value) == {'$type', 'value'}:
            kind, raw = value['$type'], value['value']
            if kind == 'Point': return Point(**raw)
            if kind == 'bytes': return base64.b64decode(raw, validate=True)
            if kind == 'set': return set(decode(v) for v in raw)
            if kind == 'tuple': return tuple(decode(v) for v in raw)
            if kind == 'dict': return {decode(k): decode(v) for k, v in raw}
        return {k: decode(v) for k, v in value.items()}
    return value


def dumps(value, **kwargs): return json.dumps(encode(value), **kwargs)
def loads(value, **kwargs): return decode(json.loads(value, **kwargs))
def dump(value, handle, **kwargs): handle.write(dumps(value, **kwargs))
def load(handle, **kwargs): return loads(handle.read(), **kwargs)
