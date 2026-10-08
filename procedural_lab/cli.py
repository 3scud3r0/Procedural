"""CLI: execute, compile, inspect, verify, export, benchmark and experiment."""

import argparse
import json
from pathlib import Path
import sys
from . import __version__
from .project import Project
from .runner import run_isolated
from .vm import Limits
from .artifacts import ArtifactStore, verify_run
from .bytecode import Program
from .backends import ArithmeticProgram, default_registry
from .errors import Diagnostic


def parser():
    root = argparse.ArgumentParser(
        prog="procedural",
        description="Procedural Lab — reproducible generation and executable languages",
    )
    root.add_argument("--version", action="version", version=__version__)
    commands = root.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="execute PCL in a killable worker process")
    run.add_argument("source", type=Path)
    run.add_argument("--seed", type=int)
    run.add_argument("--output", type=Path, default=Path("output"))
    run.add_argument("--steps", type=int, default=200000)
    run.add_argument("--seconds", type=float, default=5)
    run.add_argument("--trace", action="store_true")
    run.add_argument("--no-preview", action="store_true")
    compile = commands.add_parser("compile", help="compile to versioned bytecode JSON")
    compile.add_argument("source", type=Path)
    compile.add_argument("--output", type=Path, required=True)
    inspect = commands.add_parser("inspect", help="disassemble source or bytecode")
    inspect.add_argument("source", type=Path)
    verify = commands.add_parser("verify", help="verify a run manifest and hashes")
    verify.add_argument("directory", type=Path)
    export = commands.add_parser("export", help="export arithmetic IR to supported languages")
    export.add_argument("source", type=Path)
    export.add_argument("--targets", nargs="+")
    export.add_argument("--output", type=Path, required=True)
    bench = commands.add_parser("benchmark", help="measure time, memory and checksums")
    bench.add_argument("--repeats", type=int, default=5)
    bench.add_argument("--output", type=Path, required=True)
    experiment = commands.add_parser(
        "experiment", help="run measured communication or program evolution"
    )
    experiment.add_argument("kind", choices=["communication", "evolution"])
    experiment.add_argument("--seed", type=int, default=42)
    experiment.add_argument("--rounds", type=int, default=10000)
    experiment.add_argument("--generations", type=int, default=100)
    experiment.add_argument("--output", type=Path, required=True)
    return root


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "run":
            project = Project.load(args.source, args.seed)
            result = run_isolated(
                project,
                Limits(steps=args.steps, seconds=args.seconds),
                args.trace,
                not args.no_preview,
            )
            sys.stdout.write(result["report"].get("stdout", ""))
            if not result["ok"]:
                print(json.dumps(result["error"], ensure_ascii=False), file=sys.stderr)
                return 1
            store = ArtifactStore()
            for name, data in result["files"].items():
                store.emit(name, data)
            metadata = {
                "version": __version__,
                "seed": project.seed,
                "program_hash": result["program_hash"],
                "module_hashes": result["module_hashes"],
                "rng": "procedural.sha256/1",
                "report": result["report"],
            }
            print(store.publish(args.output, metadata))
        elif args.command == "compile":
            program, modules = Project.load(args.source).compile()
            write_json(
                args.output,
                {
                    "schema": "procedural.compilation/1",
                    "entry": program.to_dict(),
                    "modules": {name: p.to_dict() for name, p in modules.items()},
                },
            )
            print(args.output)
        elif args.command == "inspect":
            if args.source.suffix == ".json":
                value = json.loads(args.source.read_text())
                if value.get("schema") == "procedural.compilation/1":
                    value = value["entry"]
                program = Program.from_dict(value)
            else:
                program, _ = Project.load(args.source).compile()
            print(program.disassemble())
        elif args.command == "verify":
            manifest = verify_run(args.directory)
            print(f"verified {len(manifest['artifacts'])} artifacts")
        elif args.command == "export":
            program = ArithmeticProgram.from_dict(json.loads(args.source.read_text()))
            store = ArtifactStore()
            for name, source in default_registry().export(program, args.targets).items():
                store.emit(name, source)
            print(
                store.publish(
                    args.output, {"arithmetic_ir": program.to_dict(), "version": __version__}
                )
            )
        elif args.command == "benchmark":
            from .benchmarks import suite

            write_json(args.output, suite(args.repeats))
            print(args.output)
        elif args.command == "experiment":
            from .experiments import language_game, evolve_expression

            result = (
                language_game(args.seed, rounds=args.rounds)
                if args.kind == "communication"
                else evolve_expression(args.seed, generations=args.generations)
            )
            write_json(args.output, result)
            print(args.output)
        return 0
    except (Diagnostic, ValueError, OSError, KeyError, TypeError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
