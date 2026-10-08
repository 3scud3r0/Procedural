"""Portable, versioned bytecode. JSON loading validates operands and jumps."""

from dataclasses import dataclass, field, asdict
import hashlib
import json
from .errors import Diagnostic

SCHEMA = "procedural.bytecode/1"
OPS = frozenset(
    {
        "CONST",
        "LOAD",
        "STORE",
        "POP",
        "DUP",
        "BINARY",
        "UNARY",
        "COMPARE",
        "LIST",
        "TUPLE",
        "DICT",
        "GET_ITEM",
        "SET_ITEM",
        "ATTR",
        "CALL",
        "JUMP",
        "JUMP_FALSE",
        "JUMP_TRUE",
        "ITER",
        "NEXT",
        "RETURN",
        "IMPORT",
    }
)
BINARY = frozenset({"add", "sub", "mul", "div", "floordiv", "mod", "pow"})
COMPARE = frozenset({"eq", "ne", "lt", "le", "gt", "ge", "in", "notin"})


def json_literal(value):
    if isinstance(value, (str, int, float, bool, type(None))):
        json.dumps(value, allow_nan=False)
        return
    if isinstance(value, list):
        for item in value:
            json_literal(item)
        return
    if isinstance(value, dict) and all(isinstance(k, str) for k in value):
        for item in value.values():
            json_literal(item)
        return
    raise ValueError("defaults require JSON literals with string dictionary keys")


@dataclass
class Instruction:
    op: str
    arg: object = None
    line: int = 1
    column: int = 1


@dataclass
class Function:
    name: str
    parameters: list[str]
    defaults: list[object]
    code: list[Instruction]


@dataclass
class Program:
    file: str
    source_hash: str
    code: list[Instruction]
    functions: dict[str, Function] = field(default_factory=dict)

    def to_dict(self):
        return {"schema": SCHEMA, **asdict(self)}

    def to_json(self):
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, allow_nan=False)

    @property
    def digest(self):
        return hashlib.sha256(self.to_json().encode()).hexdigest()

    @classmethod
    def from_dict(cls, value):
        try:
            if value.get("schema") != SCHEMA:
                raise ValueError("unsupported bytecode schema")
            functions = {
                name: Function(
                    fn["name"],
                    fn["parameters"],
                    fn["defaults"],
                    [Instruction(**ins) for ins in fn["code"]],
                )
                for name, fn in value["functions"].items()
            }
            program = cls(
                value["file"],
                value["source_hash"],
                [Instruction(**ins) for ins in value["code"]],
                functions,
            )
            program.validate()
            return program
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise Diagnostic("BYTECODE", str(error)) from error

    def validate(self):
        if not isinstance(self.file, str) or not isinstance(self.source_hash, str):
            raise ValueError("invalid program metadata")
        if len(self.functions) > 1000:
            raise ValueError("too many functions")
        for name, fn in self.functions.items():
            if name != fn.name or not isinstance(name, str) or name.startswith("__"):
                raise ValueError("invalid function name")
            if not isinstance(fn.parameters, list) or any(
                not isinstance(p, str) or p.startswith("__") for p in fn.parameters
            ):
                raise ValueError("invalid parameters")
            if len(set(fn.parameters)) != len(fn.parameters) or len(fn.defaults) > len(
                fn.parameters
            ):
                raise ValueError("invalid function signature")
            for value in fn.defaults:
                json_literal(value)
        for code in [self.code] + [f.code for f in self.functions.values()]:
            if not isinstance(code, list) or len(code) > 100000:
                raise ValueError("invalid instruction count")
            for ins in code:
                if (
                    ins.op not in OPS
                    or type(ins.line) is not int
                    or ins.line < 1
                    or type(ins.column) is not int
                    or ins.column < 1
                ):
                    raise ValueError("invalid instruction")
                if ins.op in {"JUMP", "JUMP_TRUE", "JUMP_FALSE", "NEXT"}:
                    if type(ins.arg) is not int or not 0 <= ins.arg <= len(code):
                        raise ValueError("invalid jump target")
                if ins.op in {"LOAD", "STORE", "ATTR", "IMPORT"}:
                    if not isinstance(ins.arg, str) or ins.arg.startswith("__"):
                        raise ValueError("invalid name operand")
                if ins.op in {"LIST", "TUPLE", "DICT"} and (
                    type(ins.arg) is not int or not 0 <= ins.arg <= 100000
                ):
                    raise ValueError("invalid collection operand")
                if ins.op == "BINARY" and ins.arg not in BINARY:
                    raise ValueError("invalid binary operator")
                if ins.op == "COMPARE" and ins.arg not in COMPARE:
                    raise ValueError("invalid comparison operator")
                if ins.op == "UNARY" and ins.arg not in {"neg", "pos", "not"}:
                    raise ValueError("invalid unary operator")
                if ins.op == "CALL":
                    if not isinstance(ins.arg, (tuple, list)) or len(ins.arg) != 2:
                        raise ValueError("invalid call operand")
                    count, names = ins.arg
                    if (
                        type(count) is not int
                        or count < 0
                        or not isinstance(names, list)
                        or any(not isinstance(n, str) for n in names)
                    ):
                        raise ValueError("invalid call signature")
                    if count + len(names) > 1000 or len(set(names)) != len(names):
                        raise ValueError("invalid call argument count")
        # Ensure constants/defaults are finite JSON rather than executable objects.
        json.dumps(self.to_dict(), allow_nan=False)
        return self

    def disassemble(self):
        sections = [("<module>", self.code)] + [
            (name, fn.code) for name, fn in self.functions.items()
        ]
        lines = []
        for name, code in sections:
            lines.append(f"\n{name}:")
            for index, ins in enumerate(code):
                lines.append(
                    f"{index:04d}  {ins.op:12s} {ins.arg!r:30s}  {self.file}:{ins.line}:{ins.column}"
                )
        return "\n".join(lines)
