"""Extensible numeric expression IR with nine source-code backends.

Exports only this arithmetic IR, never arbitrary Python/PCL. Numeric semantics
use float64; compare within tolerance, not bitwise across languages/platforms.
"""

from dataclasses import dataclass
import math
import re
import keyword

RESERVED = set(keyword.kwlist) | set(
    "main fn function select class type package local end double float int char void public private return static extern export const let var mut mod use struct enum impl trait match loop crate self super where go defer interface map chan range switch case default create replace returns language immutable strict".split()
)


@dataclass(frozen=True)
class ArithmeticProgram:
    name: str
    expression: dict

    def validate(self):
        if (
            not isinstance(self.name, str)
            or not re.fullmatch(r"[a-z][a-z0-9_]*", self.name)
            or self.name in RESERVED
        ):
            raise ValueError("name must be a nonreserved lowercase identifier")
        count = 0

        def visit(node, depth):
            nonlocal count
            count += 1
            if depth > 16 or count > 1000 or not isinstance(node, dict):
                raise ValueError("arithmetic IR complexity limit exceeded")
            op = node.get("op")
            if op == "x":
                return
            if op == "constant":
                value = node.get("value")
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    or abs(value) > 1e6
                ):
                    raise ValueError("constant must be a finite number within +/-1e6")
                return
            if op not in ("add", "sub", "mul"):
                raise ValueError("unsupported arithmetic operation")
            visit(node.get("left"), depth + 1)
            visit(node.get("right"), depth + 1)

        visit(self.expression, 0)
        return self

    def to_dict(self):
        return {
            "schema": "procedural.arithmetic/1",
            "name": self.name,
            "expression": self.expression,
        }

    @classmethod
    def from_dict(cls, value):
        if value.get("schema") != "procedural.arithmetic/1":
            raise ValueError("unsupported arithmetic IR schema")
        return cls(value["name"], value["expression"]).validate()

    def evaluate(self, x):
        self.validate()
        x = float(x)
        if not math.isfinite(x) or abs(x) > 1e6:
            raise ValueError("x must be finite and within +/-1e6")

        def visit(node):
            op = node["op"]
            if op == "x":
                return x
            if op == "constant":
                return float(node["value"])
            a, b = visit(node["left"]), visit(node["right"])
            value = {"add": lambda: a + b, "sub": lambda: a - b, "mul": lambda: a * b}[op]()
            if not math.isfinite(value):
                raise ValueError("arithmetic overflow")
            return value

        return visit(self.expression)


@dataclass(frozen=True)
class Backend:
    extension: str
    render: object


class BackendRegistry:
    def __init__(self):
        self.backends = {}

    def register(self, name, extension, render):
        if name in self.backends:
            raise ValueError(f"duplicate backend: {name}")
        if not re.fullmatch(r"\.[a-z]+", extension) or not callable(render):
            raise ValueError("invalid backend definition")
        self.backends[name] = Backend(extension, render)

    def export(self, program, targets=None):
        program.validate()
        targets = list(self.backends) if targets is None else list(targets)
        if len(set(targets)) != len(targets) or any(t not in self.backends for t in targets):
            raise ValueError("duplicate or unknown backend target")
        result = {}
        for target in targets:
            backend = self.backends[target]
            result[program.name + backend.extension] = backend.render(program)
        return result


def expression_source(node, constant=lambda value: repr(float(value))):
    if node["op"] == "x":
        return "x"
    if node["op"] == "constant":
        return constant(node["value"])
    operator = {"add": "+", "sub": "-", "mul": "*"}[node["op"]]
    return f"({expression_source(node['left'], constant)} {operator} {expression_source(node['right'], constant)})"


def default_registry():
    registry = BackendRegistry()

    def render_python(p):
        return f"def {p.name}(x: float) -> float:\n    return {expression_source(p.expression)}\n"

    def render_js(p):
        return f"export function {p.name}(x) {{\n  return {expression_source(p.expression)};\n}}\n"

    def render_ts(p):
        return f"export function {p.name}(x: number): number {{\n  return {expression_source(p.expression)};\n}}\n"

    def render_c(p):
        return f"double {p.name}(double x) {{\n  return {expression_source(p.expression)};\n}}\n"

    def render_cpp(p):
        return f'extern "C" double {p.name}(double x) {{\n  return {expression_source(p.expression)};\n}}\n'

    def render_rust(p):
        return f"pub fn {p.name}(x: f64) -> f64 {{\n    {expression_source(p.expression)}\n}}\n"

    def render_go(p):
        return f"package generated\n\nfunc {p.name.capitalize()}(x float64) float64 {{\n    return {expression_source(p.expression)}\n}}\n"

    def render_lua(p):
        return f"local function {p.name}(x)\n  return {expression_source(p.expression)}\nend\nreturn {p.name}\n"

    def render_sql(p):
        return f"-- PostgreSQL, arithmetic function with float64 semantics.\nCREATE OR REPLACE FUNCTION {p.name}(x double precision)\nRETURNS double precision LANGUAGE SQL IMMUTABLE STRICT\nAS $$ SELECT {expression_source(p.expression)}; $$;\n"

    for name, extension, render in [
        ("python", ".py", render_python),
        ("javascript", ".mjs", render_js),
        ("typescript", ".ts", render_ts),
        ("c", ".c", render_c),
        ("cpp", ".cpp", render_cpp),
        ("rust", ".rs", render_rust),
        ("go", ".go", render_go),
        ("lua", ".lua", render_lua),
        ("sql", ".sql", render_sql),
    ]:
        registry.register(name, extension, render)
    return registry
