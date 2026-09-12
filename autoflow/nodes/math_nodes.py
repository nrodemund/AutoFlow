"""Integer arithmetic and explicit point construction/decomposition."""
import operator
from autoflow.registry import NodeType
from autoflow.datatypes import Point


def integer(value):
    if type(value) is not int:
        raise ValueError("Expected an integer")
    return value


def point(value):
    if not isinstance(value, dict) or set(value) != {"x", "y"}:
        raise ValueError("Expected a point {x, y}")
    return Point(integer(value["x"]), integer(value["y"]))


def quotient(a, b):
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return (abs(a) // abs(b)) * (-1 if (a < 0) != (b < 0) else 1)


def binary(operation):
    def execute(ctx, node_id, inputs):
        a, b = integer(inputs["a"]), integer(inputs["b"])
        return {"result": operation(a, b)}, None
    return execute


def add_point(ctx, node_id, inputs):
    a, b = point(inputs['a']), point(inputs['b'])
    return {'point': Point(a.x + b.x, a.y + b.y)}, None


def offset_point(ctx, node_id, inputs):
    origin = point(inputs['point'])
    return {'point': Point(origin.x + integer(inputs['x']), origin.y + integer(inputs['y']))}, None


NODES = [NodeType(name, {"a": "integer", "b": "integer"}, {"result": "integer"}, (), binary(op),
                  description, defaults={"a": 0, "b": 1}, pure=True, title=title, category="Math")
         for name, title, op, description in [
             ("SubtractInt", "Subtract (Int)", operator.sub, "A minus B."),
             ("MultiplyInt", "Multiply (Int)", operator.mul, "A times B."),
             ("DivideInt", "Divide (Int)", quotient, "Integer division, truncated toward zero. Zero divisor is an error."),
             ("ModuloInt", "Modulo (Int)", lambda a, b: a - quotient(a, b) * b, "Remainder with the sign of A."),
             ("MinInt", "Min (Int)", min, "Smaller integer."),
             ("MaxInt", "Max (Int)", max, "Larger integer."),
         ]] + [
    NodeType('AddPoint', {'a': 'reference:Point', 'b': 'reference:Point'}, {'point': 'reference:Point'}, (),
             add_point, 'Add two points component by component: (A.x + B.x, A.y + B.y).',
             defaults={'a': {'x': 0, 'y': 0}, 'b': {'x': 0, 'y': 0}},
             pure=True, title='Add Point', category='Point'),
    NodeType('OffsetPoint', {'point': 'reference:Point', 'x': 'integer', 'y': 'integer'}, {'point': 'reference:Point'}, (),
             offset_point, 'Add integer X and Y offsets to a point. Negative offsets are supported.',
             defaults={'point': {'x': 0, 'y': 0}, 'x': 0, 'y': 0},
             pure=True, title='Offset Point', category='Point'),
    NodeType("MakePoint", {"x": "integer", "y": "integer"}, {"point": "reference:Point"}, (),
             lambda c, n, i: ({"point": point(i)}, None), defaults={"x": 0, "y": 0},
             pure=True, title="Make Point", category="Point"),
    NodeType("BreakPoint", {"point": "reference:Point"}, {"x": "integer", "y": "integer"}, (),
             lambda c, n, i: (point(i["point"]), None), defaults={"point": {"x": 0, "y": 0}},
             pure=True, title="Break Point", category="Point"),
]
