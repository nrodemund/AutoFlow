import argparse
from autoflow import datatypes as json
import sys
from pathlib import Path
from autoflow.engine import Engine, load_project
from autoflow.registry import discover


def main():
    parser = argparse.ArgumentParser(description="AutoFlow desktop automation and graph editor")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("nodes", help="List discoverable node definitions as JSON")
    editor = sub.add_parser("editor", help="Open the local visual graph editor")
    editor.add_argument("--port", type=int, default=8765)
    editor.add_argument("--no-browser", action="store_true")
    for command in ("run", "validate"):
        p = sub.add_parser(command)
        p.add_argument("project", type=Path)
        if command == "run":
            p.add_argument("--parameters", default="{}", help="Main graph parameters as JSON")
            p.add_argument("--max-steps", type=int, default=10000)
            p.add_argument("--simulate-screen", action="store_true", help="Disable real screen capture")
    args = parser.parse_args()
    try:
        if args.command == "editor":
            from autoflow.server import serve
            serve(args.port, not args.no_browser)
            return 0
        registry = discover()
        if args.command == "nodes":
            print(json.dumps([dict(name=n.name, inputs=n.inputs, outputs=n.outputs,
                                   flows=list(n.flows), defaults=n.defaults, description=n.description,
                                   pure=n.pure, title=n.title or n.name, category=n.category)
                              for n in registry.values()], indent=2))
            return 0
        from autoflow.screen import WindowsScreen
        base = args.project.resolve().parent
        screen = None if getattr(args, "simulate_screen", False) else WindowsScreen(base)
        engine = Engine(load_project(args.project), registry, base, screen=screen,
                        max_steps=getattr(args, "max_steps", 10000))
        if args.command == "validate":
            print("Graph structure is valid.")
        else:
            print("AutoFlow - " + ("desktop simulation" if args.simulate_screen else "live desktop automation"))
            print(json.dumps(engine.run(json.loads(args.parameters)), indent=2))
        return 0
    except KeyboardInterrupt:
        print("Stopped.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
