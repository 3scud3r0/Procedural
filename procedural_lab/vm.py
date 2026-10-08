"""Bounded stack VM. Host access exists only through registered capabilities.

There is no Python eval/exec and arbitrary object attributes are inaccessible.
This is not a security boundary for hostile bytecode: use OS/process isolation.
"""

from dataclasses import dataclass, asdict
import copy
import math
import operator
import time
from procedural import Procedural
from .artifacts import ArtifactStore
from .geometry import Scene
from .errors import Diagnostic, Location


@dataclass(frozen=True)
class Limits:
    steps: int = 200000
    seconds: float = 5.0
    calls: int = 128
    items: int = 100000
    integer_bits: int = 4096
    objects: int = 10000
    artifact_bytes: int = 5_000_000
    stdout_bytes: int = 100000

    def __post_init__(self):
        for name, value in asdict(self).items():
            if name == "seconds":
                if not math.isfinite(value) or value <= 0:
                    raise ValueError("seconds must be positive and finite")
            elif type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")


@dataclass
class Module:
    name: str
    exports: dict

    def __repr__(self):
        return f"<module {self.name}>"


@dataclass
class UserFunction:
    definition: object
    globals: dict
    file: str

    def __repr__(self):
        return f"<function {self.definition.name}>"


@dataclass
class Capability:
    function: object

    def __repr__(self):
        return "<capability>"


class VirtualMachine:
    def __init__(self, seed=42, limits=None, modules=None, trace=False):
        self.seed = seed
        self.limits = limits or Limits()
        self.engine = Procedural(seed)
        self.ctx = self.engine.context
        self.scene = Scene(self.limits.objects)
        self.artifacts = ArtifactStore(max_bytes=self.limits.artifact_bytes)
        self.programs = modules or {}
        self.modules = {}
        self.loading = set()
        self.steps = 0
        self.frames = []
        self.stdout = []
        self.started = None
        self.trace = [] if trace else None
        self.current = Location()
        self.builtins = self._builtins()

    def cap(self, fn):
        return Capability(fn)

    def _builtins(self):
        math_api = {
            name: self.cap(getattr(math, name))
            for name in ["sin", "cos", "tan", "sqrt", "floor", "ceil", "log", "exp", "atan2"]
        }
        math_api.update(pi=math.pi, e=math.e)
        self.modules["math"] = Module("math", math_api)
        self.modules["procedural"] = Module(
            "procedural",
            {
                name: self.cap(fn)
                for name, fn in {
                    "generate": self.generate,
                    "noise": self.ctx.noise,
                    "fbm": self.ctx.fbm,
                    "grammar": self.ctx.grammar,
                }.items()
            },
        )
        functions = {
            "print": self.print,
            "emit": self.artifacts.emit,
            "range": self.range,
            "len": len,
            "abs": abs,
            "min": min,
            "max": max,
            "round": round,
            "int": int,
            "float": float,
            "str": str,
            "bool": bool,
            "sum": sum,
            "sorted": sorted,
            "list": list,
            "append": self.append,
            "random": self.ctx.random,
            "randint": self.ctx.randint,
            "uniform": self.ctx.uniform,
            "choose": self.ctx.choose,
            "noise": self.ctx.noise,
            "fbm": self.ctx.fbm,
            "grammar": self.ctx.grammar,
            "generate": self.generate,
            "box": self.scene.box,
            "sphere": self.scene.sphere,
            "line": self.scene.line,
        }
        return {name: self.cap(fn) for name, fn in functions.items()}

    def print(self, *values, sep=" ", end="\n"):
        value = sep.join(map(str, values)) + end
        if (
            len(value.encode()) + sum(len(s.encode()) for s in self.stdout)
            > self.limits.stdout_bytes
        ):
            raise ValueError("stdout limit exceeded")
        self.stdout.append(value)

    def append(self, values, value):
        if not isinstance(values, list):
            raise TypeError("append requires a list")
        if len(values) >= self.limits.items:
            raise ValueError("collection limit exceeded")
        self.check(value)
        values.append(value)
        try:
            self.check(values)
        except Exception:
            values.pop()
            raise

    def range(self, *args):
        value = range(*args)
        if len(value) > self.limits.items:
            raise ValueError("range limit exceeded")
        return value

    def generate(self, name, **parameters):
        if name == "terrain" and parameters.get("width", 32) * parameters.get("height", 32) > 10000:
            raise ValueError("VM terrain limit is 10000 cells")
        if name == "numbers" and parameters.get("count", 10) > self.limits.items:
            raise ValueError("VM numbers limit exceeded")
        if name == "graph" and parameters.get("nodes", 8) > 500:
            raise ValueError("VM graph limit is 500 nodes")
        return self.engine.generate(name, **parameters)

    def check(self, value, depth=0, seen=None):
        if isinstance(value, complex):
            raise ValueError("complex numbers are not supported")
        if depth > 64:
            raise ValueError("value nesting limit exceeded")
        if isinstance(value, int) and value.bit_length() > self.limits.integer_bits:
            raise ValueError("integer size limit exceeded")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("nonfinite number")
        if (
            isinstance(value, (str, bytes, list, tuple, dict, range))
            and len(value) > self.limits.items
        ):
            raise ValueError("value size limit exceeded")
        if isinstance(value, (list, tuple, dict)):
            seen = set() if seen is None else seen
            if id(value) in seen:
                raise ValueError("cyclic values are not supported")
            seen.add(id(value))
            try:
                values = value.values() if isinstance(value, dict) else value
                for item in values:
                    self.check(item, depth + 1, seen)
            finally:
                seen.remove(id(value))
        return value

    def tick(self, ins, file):
        self.current = Location(file, ins.line, ins.column)
        self.steps += 1
        if self.steps > self.limits.steps:
            raise Diagnostic("STEP_LIMIT", "instruction budget exceeded", self.current)
        if time.perf_counter() - self.started > self.limits.seconds:
            raise Diagnostic("TIME_LIMIT", "execution time exceeded", self.current)
        if self.trace is not None and len(self.trace) < 10000:
            self.trace.append(
                {
                    "step": self.steps,
                    "op": ins.op,
                    "file": file,
                    "line": ins.line,
                    "depth": len(self.frames),
                }
            )

    def execute(self, program):
        if self.started is not None:
            raise ValueError("VM instances execute one run; create a new VM for another run")
        program.validate()
        self.started = time.perf_counter()
        globals = self.namespace(program)
        try:
            self.frame(program.code, globals, globals, program.file, "<module>")
            return globals
        except Diagnostic:
            raise
        except Exception as error:
            raise Diagnostic(type(error).__name__, str(error), self.current, self.frames) from error

    def namespace(self, program):
        globals = dict(self.builtins)
        for name, definition in program.functions.items():
            globals[name] = UserFunction(definition, globals, program.file)
        return globals

    def import_module(self, name):
        if name in self.modules:
            return self.modules[name]
        if name in self.loading:
            raise ValueError(f"circular module import: {name}")
        if name not in self.programs:
            raise ImportError(f"capability or project module not found: {name}")
        program = self.programs[name]
        program.validate()
        self.loading.add(name)
        try:
            globals = self.namespace(program)
            self.frame(program.code, globals, globals, program.file, name)
            module = Module(
                name,
                {
                    k: v
                    for k, v in globals.items()
                    if k not in self.builtins and not k.startswith("_")
                },
            )
            self.modules[name] = module
            return module
        finally:
            self.loading.remove(name)

    def call(self, callee, args, kwargs):
        if isinstance(callee, Capability):
            return self.check(callee.function(*args, **kwargs))
        if not isinstance(callee, UserFunction):
            raise TypeError("only language functions and registered capabilities are callable")
        fn = callee.definition
        if len(args) > len(fn.parameters):
            raise TypeError(f"{fn.name}: too many arguments")
        locals = dict(zip(fn.parameters, args))
        for name, value in kwargs.items():
            if name not in fn.parameters or name in locals:
                raise TypeError(f"{fn.name}: unknown or duplicate argument {name}")
            locals[name] = value
        defaults = dict(zip(fn.parameters[len(fn.parameters) - len(fn.defaults) :], fn.defaults))
        for name in fn.parameters:
            if name not in locals:
                if name not in defaults:
                    raise TypeError(f"{fn.name}: missing argument {name}")
                locals[name] = self.check(copy.deepcopy(defaults[name]))
        return self.frame(fn.code, locals, callee.globals, callee.file, fn.name)

    def binary(self, op, left, right):
        if (
            op == "pow"
            and isinstance(right, (int, float))
            and abs(right) > self.limits.integer_bits
        ):
            raise ValueError("exponent limit exceeded")
        if op == "mul" and (
            (isinstance(left, (str, list, tuple)) and isinstance(right, int))
            or (isinstance(right, (str, list, tuple)) and isinstance(left, int))
        ):
            seq, count = (left, right) if isinstance(right, int) else (right, left)
            if len(seq) * max(0, count) > self.limits.items:
                raise ValueError("repetition size limit exceeded")
        operation = {
            "add": operator.add,
            "sub": operator.sub,
            "mul": operator.mul,
            "div": operator.truediv,
            "floordiv": operator.floordiv,
            "mod": operator.mod,
            "pow": operator.pow,
        }[op]
        return self.check(operation(left, right))

    def frame(self, code, locals, globals, file, name):
        if len(self.frames) >= self.limits.calls:
            raise Diagnostic("CALL_LIMIT", "call depth exceeded", self.current, self.frames)
        frame = {"function": name, "file": file, "line": 1}
        self.frames.append(frame)
        stack = []
        pc = 0

        def take(count):
            if count > len(stack):
                raise Diagnostic("BYTECODE", "stack underflow", self.current)
            if count == 0:
                return []
            values = stack[-count:]
            del stack[-count:]
            return values

        try:
            while pc < len(code):
                ins = code[pc]
                self.tick(ins, file)
                frame["line"] = ins.line
                pc += 1
                op, arg = ins.op, ins.arg
                if op == "CONST":
                    stack.append(self.check(copy.deepcopy(arg)))
                elif op == "LOAD":
                    if arg in locals:
                        stack.append(locals[arg])
                    elif arg in globals:
                        stack.append(globals[arg])
                    else:
                        raise NameError(f"name not defined: {arg}")
                elif op == "STORE":
                    locals[arg] = take(1)[0]
                elif op == "POP":
                    take(1)
                elif op == "DUP":
                    stack.extend(take(1) * 2)
                elif op == "BINARY":
                    a, b = take(2)
                    stack.append(self.binary(arg, a, b))
                elif op == "UNARY":
                    a = take(1)[0]
                    stack.append(
                        self.check(
                            {"neg": operator.neg, "pos": operator.pos, "not": operator.not_}[arg](a)
                        )
                    )
                elif op == "COMPARE":
                    a, b = take(2)
                    fn = {
                        "eq": operator.eq,
                        "ne": operator.ne,
                        "lt": operator.lt,
                        "le": operator.le,
                        "gt": operator.gt,
                        "ge": operator.ge,
                        "in": lambda a, b: a in b,
                        "notin": lambda a, b: a not in b,
                    }[arg]
                    stack.append(fn(a, b))
                elif op in {"LIST", "TUPLE", "DICT"}:
                    values = take(arg * 2 if op == "DICT" else arg)
                    value = (
                        dict(zip(values[::2], values[1::2]))
                        if op == "DICT"
                        else tuple(values)
                        if op == "TUPLE"
                        else values
                    )
                    stack.append(self.check(value))
                elif op == "GET_ITEM":
                    a, b = take(2)
                    if not isinstance(a, (list, tuple, dict, str, range)):
                        raise TypeError("indexing requires a collection")
                    stack.append(a[b])
                elif op == "SET_ITEM":
                    a, b, c = take(3)
                    if not isinstance(a, (list, dict)):
                        raise TypeError("item assignment requires list or dict")
                    old = copy.deepcopy(a)
                    a[b] = c
                    try:
                        self.check(a)
                    except Exception:
                        if isinstance(a, list):
                            a[:] = old
                        else:
                            a.clear()
                            a.update(old)
                        raise
                elif op == "ATTR":
                    a = take(1)[0]
                    if not isinstance(a, Module):
                        raise TypeError("attribute access only permitted on modules")
                    if arg not in a.exports:
                        raise AttributeError(f"{a.name} has no export {arg}")
                    stack.append(a.exports[arg])
                elif op == "CALL":
                    count, names = arg
                    values = take(count + len(names))
                    callee = take(1)[0]
                    stack.append(
                        self.call(callee, values[:count], dict(zip(names, values[count:])))
                    )
                elif op == "JUMP":
                    pc = arg
                elif op in {"JUMP_FALSE", "JUMP_TRUE"}:
                    value = bool(take(1)[0])
                    if value == (op == "JUMP_TRUE"):
                        pc = arg
                elif op == "ITER":
                    value = take(1)[0]
                    if not isinstance(value, (list, tuple, str, dict, range)):
                        raise TypeError("for requires a collection")
                    stack.append(iter(value))
                elif op == "NEXT":
                    if not stack:
                        raise ValueError("missing iterator")
                    try:
                        stack.append(next(stack[-1]))
                    except StopIteration:
                        take(1)
                        pc = arg
                elif op == "RETURN":
                    return take(1)[0]
                elif op == "IMPORT":
                    stack.append(self.import_module(arg))
            return None
        except Diagnostic as error:
            if not error.frames:
                error.frames = list(copy.deepcopy(self.frames))
            raise
        except Exception as error:
            raise Diagnostic(
                type(error).__name__, str(error), self.current, copy.deepcopy(self.frames)
            ) from error
        finally:
            self.frames.pop()

    def report(self):
        return {
            "seed": self.seed,
            "rng": "procedural.sha256/1",
            "steps": self.steps,
            "stdout": "".join(self.stdout),
            "limits": asdict(self.limits),
            "artifacts": self.artifacts.manifest(),
            "objects": len(self.scene.objects),
            "elapsed_seconds": time.perf_counter() - self.started if self.started else 0,
        }
