"""Screen nodes depend on a replaceable backend, independent of the graph UI."""
from autoflow.registry import NodeType
from autoflow.nodes.math_nodes import integer, point as checked_point


def threshold(inputs):
    value = integer(inputs["confidence"])
    if not 1 <= value <= 100:
        raise ValueError("Confidence must be an integer percentage from 1 to 100")
    return value / 100


def find(ctx, node_id, inputs):
    point = ctx.engine.screen.find(inputs["texture"], threshold(inputs))
    return {"found": point is not None, "point": {"x": point[0], "y": point[1]} if point is not None else None}, "found" if point is not None else "not_found"


def click(ctx, node_id, inputs):
    p = checked_point(inputs["point"])
    ctx.engine.log(ctx.engine.screen.click(p["x"], p["y"]))
    return {}, "then"


def find_text(ctx, node_id, inputs):
    location = ctx.engine.screen.find_text(inputs["text"], checked_point(inputs["start"]),
        checked_point(inputs["end"]), inputs["language"], ctx.engine.cancel, inputs["case_sensitive"])
    diagnostics = getattr(ctx.engine.screen, "last_ocr_diagnostics", None)
    if location is None and isinstance(diagnostics, dict):
        from json import dumps
        ctx.engine.log("OCR no exact match: " + dumps({"node": node_id, "requested": inputs["text"],
            "language": inputs["language"], "case_sensitive": inputs["case_sensitive"],
            **diagnostics}, ensure_ascii=False))
    return {"found": location is not None,
            "point": {"x": location[0], "y": location[1]} if location is not None else None}, "found" if location is not None else "not_found"


def is_on_screen(ctx, node_id, inputs):
    return {"found": ctx.engine.screen.find(inputs["texture"], threshold(inputs)) is not None}, None


def find_point(ctx, node_id, inputs):
    offset_x, offset_y = integer(inputs["offset_x"]), integer(inputs["offset_y"])
    location = ctx.engine.screen.find(inputs["texture"], threshold(inputs))
    return {"found": location is not None,
            "point": {"x": location[0] + offset_x, "y": location[1] + offset_y} if location is not None else None}, "found" if location is not None else "not_found"


def move(ctx, node_id, inputs):
    ctx.engine.screen.move(checked_point(inputs["point"]))
    return {}, "then"


def drag(ctx, node_id, inputs):
    ctx.engine.screen.drag(checked_point(inputs["start"]), checked_point(inputs["end"]), integer(inputs["duration_ms"]), ctx.engine.cancel)
    return {}, "then"


def press(ctx, node_id, inputs):
    ctx.engine.screen.key_press(inputs["keys"])
    return {}, "then"


def copy_text(ctx, node_id, inputs):
    return {"text": ctx.engine.screen.copy(ctx.engine.cancel)}, "then"


def paste_text(ctx, node_id, inputs):
    if type(inputs["use_clipboard"]) is not bool:
        raise ValueError("use_clipboard must be a boolean")
    ctx.engine.screen.paste(inputs["text"], inputs["use_clipboard"])
    return {}, "then"


NODES = [
    NodeType(name, {"texture": "string", "confidence": "integer"}, {"found": "bool", "point": "reference:Point?"},
             ("found", "not_found"), find, "Find a texture on the desktop. Point is its physical top-left position; confidence is 1-100 percent.",
             defaults={"texture": "", "confidence": 97}, category="Screen")
    for name in ("FindOnScreen", "IfOnScreen")
] + [NodeType("Click", {"point": "reference:Point"}, {}, ("then",), click, defaults={"point": {"x": 0, "y": 0}}, category="Screen"),
     NodeType("IsOnScreen", {"texture": "string", "confidence": "integer"}, {"found": "bool"}, (),
              is_on_screen, "Pure boolean: captures and checks the desktop each time its output is read.",
              defaults={"texture": "", "confidence": 97}, pure=True, category="Screen")]

NODES += [
    NodeType("FindTextOnScreen", {"text": "string", "start": "reference:Point", "end": "reference:Point", "language": "string", "case_sensitive": "bool"},
             {"found": "bool", "point": "reference:Point?"}, ("found", "not_found"), find_text,
             "Local OCR inside the rectangle between Start and End (physical screen pixels). Exact whole-line match; whitespace is normalized. Disable Case sensitive to ignore OCR capitalization errors. Returns the center of the first match, top to bottom. Language blank uses Windows settings (or enter de-DE).",
             defaults={"text": "", "start": {"x": 0, "y": 0}, "end": {"x": 500, "y": 500}, "language": "", "case_sensitive": True}, title="Find Text on Screen (OCR)", category="Screen"),
    NodeType("FindPointOnScreen", {"texture": "string", "confidence": "integer", "offset_x": "integer", "offset_y": "integer"},
             {"found": "bool", "point": "reference:Point?"}, ("found", "not_found"), find_point,
             "Find a texture and add its pixel offset. Click the enlarged texture to choose the offset.",
             defaults={"texture": "", "confidence": 97, "offset_x": 0, "offset_y": 0}, category="Screen"),
    NodeType("MouseMove", {"point": "reference:Point"}, {}, ("then",), move, defaults={"point": {"x": 0, "y": 0}}, title="Mouse Move", category="Input"),
    NodeType("Drag", {"start": "reference:Point", "end": "reference:Point", "duration_ms": "integer"}, {}, ("then",), drag,
             defaults={"start": {"x": 0, "y": 0}, "end": {"x": 100, "y": 100}, "duration_ms": 500}, category="Input"),
    NodeType("KeyPress", {"keys": "string"}, {}, ("then",), press, defaults={"keys": "enter"}, title="Key Press", category="Input"),
    NodeType("Copy", {}, {"text": "string"}, ("then",), copy_text, "Copy selected text using Ctrl+C and return clipboard text.", category="Input"),
    NodeType("Paste", {"text": "string", "use_clipboard": "bool"}, {}, ("then",), paste_text,
             "Paste using Ctrl+V. Disable Use clipboard to type Text directly without using the clipboard.", defaults={"text": "", "use_clipboard": True}, category="Input"),
]
