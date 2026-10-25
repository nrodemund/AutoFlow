"""Discover node definitions from Python modules; no engine edits required."""
from dataclasses import dataclass, field
from importlib import import_module
from pkgutil import iter_modules
from typing import Callable


@dataclass(frozen=True)
class NodeType:
    name: str
    inputs: dict[str, str]
    outputs: dict[str, str]
    flows: tuple[str, ...]
    execute: Callable
    description: str = ""
    defaults: dict = field(default_factory=dict)
    pure: bool = False
    title: str = ""
    category: str = "Utilities"
    deferred_inputs: tuple[str, ...] = ()
    debug_preview: Callable | None = None
    debug_update: Callable | None = None


def discover(package_name="autoflow.nodes"):
    package = import_module(package_name)
    registry = {}
    for module in sorted(iter_modules(package.__path__), key=lambda m: m.name):
        for definition in getattr(import_module(f"{package_name}.{module.name}"), "NODES", []):
            if definition.name in registry:
                raise ValueError(f"Duplicate node type: {definition.name}")
            registry[definition.name] = definition
    return registry
