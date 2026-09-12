"""Editor catalog entries; actual pins come from graph signatures."""
from autoflow.registry import NodeType

NODES = [NodeType(name, {}, {}, () if name != 'FunctionCall' else ('then',),
                  lambda c, n, i: ({}, None), pure=name == 'FunctionParameter',
                  title=title, category='Functions', description=description)
         for name, title, description in [
             ('FunctionParameter', 'Parameter', 'Created from the typed parameters in Function settings.'),
             ('FunctionCall', 'Call Function', 'Drag a function from the sidebar to call it with typed input and return pins.'),
             ('FunctionReturn', 'Return', 'Return named values and finish this function immediately.')]]
