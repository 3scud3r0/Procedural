"""Execute exported code. Tool paths may be supplied by environment variables.

SQL validation evaluates its arithmetic expression in SQLite; it does NOT
validate PostgreSQL CREATE FUNCTION DDL. Missing tools are reported as skipped.
"""

import ctypes
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from procedural_lab.backends import ArithmeticProgram, default_registry, expression_source


def tool(name, variable):
    value = os.environ.get(variable) or shutil.which(name)
    if not value or not Path(value).exists():
        return None
    if name == "go":
        result = subprocess.run([value, "version"], capture_output=True, timeout=10)
        if result.returncode or not result.stdout.startswith(b"go version"):
            return None  # Some systems install the GNU Go board game as 'go'.
    return value


def command(args, cwd=None):
    return subprocess.check_output(args, cwd=cwd, stderr=subprocess.PIPE, timeout=60).decode()


def validate():
    program = ArithmeticProgram.from_dict(
        json.loads((ROOT / "examples/arithmetic.json").read_text())
    )
    samples = [-100.25, -10, -3, -1, 0, 0.25, 1, 3, 10, 100.25]
    expected = [program.evaluate(x) for x in samples]
    files = default_registry().export(program)
    records = []

    def record(target, values, method):
        if len(values) != len(expected) or any(
            not math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12) for a, b in zip(values, expected)
        ):
            raise ValueError(f"backend mismatch: {target}")
        records.append(
            {"target": target, "status": "passed", "samples": len(samples), "method": method}
        )

    def skip(target):
        records.append({"target": target, "status": "skipped", "reason": "toolchain unavailable"})

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for name, source in files.items():
            (root / name).write_text(source)
        ns = {}
        exec(compile(files["quadratic.py"], "quadratic.py", "exec"), ns)
        record("python", [ns["quadratic"](x) for x in samples], "CPython execution")
        node = tool("node", "PROCEDURAL_NODE")
        if node:
            (root / "test.mjs").write_text(
                'import {quadratic} from "./quadratic.mjs"; console.log(JSON.stringify('
                + json.dumps(samples)
                + ".map(quadratic)));"
            )
            record(
                "javascript",
                json.loads(command([node, str(root / "test.mjs")])),
                "Node.js ESM execution",
            )
        else:
            skip("javascript")
        tsc = tool("tsc", "PROCEDURAL_TSC")
        if tsc and node:
            command(
                [
                    tsc,
                    str(root / "quadratic.ts"),
                    "--outDir",
                    str(root / "ts"),
                    "--target",
                    "ES2020",
                    "--module",
                    "commonjs",
                ]
            )
            (root / "test.cjs").write_text(
                'const {quadratic}=require("./ts/quadratic.js"); console.log(JSON.stringify('
                + json.dumps(samples)
                + ".map(quadratic)));"
            )
            record(
                "typescript",
                json.loads(command([node, str(root / "test.cjs")])),
                "TypeScript compilation and Node.js execution",
            )
        else:
            skip("typescript")
        for target, extension, variable, compiler in [
            ("c", "c", "PROCEDURAL_CC", "cc"),
            ("cpp", "cpp", "PROCEDURAL_CXX", "c++"),
        ]:
            executable = tool(compiler, variable)
            if not executable:
                skip(target)
                continue
            library = root / f"{target}.so"
            command(
                [
                    executable,
                    "-shared",
                    "-fPIC",
                    str(root / f"quadratic.{extension}"),
                    "-o",
                    str(library),
                ]
            )
            fn = ctypes.CDLL(str(library)).quadratic
            fn.argtypes = [ctypes.c_double]
            fn.restype = ctypes.c_double
            record(
                target,
                [fn(x) for x in samples],
                "native shared library compilation and ctypes execution",
            )
        rust = tool("rustc", "PROCEDURAL_RUSTC")
        if rust:
            source = (
                files["quadratic.rs"]
                + "\nfn main() {\n"
                + "".join(f'println!("{{}}", quadratic({float(x)!r}));\n' for x in samples)
                + "}\n"
            )
            (root / "rust.rs").write_text(source)
            command([rust, str(root / "rust.rs"), "-o", str(root / "rust")])
            record(
                "rust",
                list(map(float, command([str(root / "rust")]).split())),
                "rustc compilation and native execution",
            )
        else:
            skip("rust")
        go = tool("go", "PROCEDURAL_GO")
        if go:
            (root / "generated").mkdir()
            (root / "generated" / "quadratic.go").write_text(files["quadratic.go"])
            (root / "go.mod").write_text("module check\n\ngo 1.18\n")
            main = (
                'package main\nimport("fmt"; "check/generated")\nfunc main(){\n'
                + "".join(f"fmt.Println(generated.Quadratic({float(x)!r}))\n" for x in samples)
                + "}\n"
            )
            (root / "main.go").write_text(main)
            record(
                "go",
                list(map(float, command([go, "run", "main.go"], root).split())),
                "Go compilation and execution",
            )
        else:
            skip("go")
        lua = tool("lua", "PROCEDURAL_LUA")
        if lua:
            main = 'local fn=dofile("quadratic.lua")\n' + "".join(
                f"print(fn({float(x)!r}))\n" for x in samples
            )
            (root / "test.lua").write_text(main)
            record(
                "lua",
                list(map(float, command([lua, "test.lua"], root).split())),
                "Lua interpreter execution",
            )
        else:
            skip("lua")
        connection = sqlite3.connect(":memory:")
        try:
            expression = expression_source(program.expression)
            values = [
                connection.execute(f"SELECT {expression} FROM (SELECT ? AS x)", (x,)).fetchone()[0]
                for x in samples
            ]
            record(
                "sql", values, "arithmetic SELECT in SQLite; PostgreSQL function DDL not validated"
            )
        finally:
            connection.close()
    return {
        "schema": "procedural.backend-validation/1",
        "program": program.to_dict(),
        "samples": samples,
        "comparison": {"relative_tolerance": 1e-12, "absolute_tolerance": 1e-12},
        "records": records,
    }


if __name__ == "__main__":
    result = validate()
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "benchmarks/backend_report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result["records"], indent=2))
