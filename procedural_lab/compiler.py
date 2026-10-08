"""Python-syntax procedural language compiled without eval/exec.

This is a documented subset of Python, not CPython compatibility. Unsupported
syntax is rejected at compilation with a source location.
"""

import ast
import hashlib
from .bytecode import Program, Function, Instruction
from .errors import Diagnostic, Location

BIN = {
    ast.Add: "add",
    ast.Sub: "sub",
    ast.Mult: "mul",
    ast.Div: "div",
    ast.FloorDiv: "floordiv",
    ast.Mod: "mod",
    ast.Pow: "pow",
}
CMP = {
    ast.Eq: "eq",
    ast.NotEq: "ne",
    ast.Lt: "lt",
    ast.LtE: "le",
    ast.Gt: "gt",
    ast.GtE: "ge",
    ast.In: "in",
    ast.NotIn: "notin",
}


class Compiler:
    def __init__(self, file):
        self.file = file
        self.code = []
        self.functions = {}
        self.loops = []
        self.in_function = False

    def fail(self, node, message):
        raise Diagnostic(
            "COMPILE",
            message,
            Location(self.file, getattr(node, "lineno", 1), getattr(node, "col_offset", 0) + 1),
        )

    def name(self, node, name):
        if name.startswith("__"):
            self.fail(node, "names beginning with '__' are reserved")
        return name

    def emit(self, node, op, arg=None):
        self.code.append(
            Instruction(op, arg, getattr(node, "lineno", 1), getattr(node, "col_offset", 0) + 1)
        )
        return len(self.code) - 1

    def patch(self, position, target=None):
        self.code[position].arg = len(self.code) if target is None else target

    def statements(self, nodes):
        for node in nodes:
            self.statement(node)

    def statement(self, node):
        if isinstance(node, ast.Expr):
            self.expression(node.value)
            self.emit(node, "POP")
        elif isinstance(node, ast.Assign):
            if len(node.targets) != 1:
                self.fail(node, "chained assignment is not supported")
            self.assign(node.targets[0], node.value)
        elif isinstance(node, ast.AugAssign):
            if not isinstance(node.target, ast.Name) or type(node.op) not in BIN:
                self.fail(node, "augmented assignment requires a name and supported operator")
            self.emit(node, "LOAD", self.name(node, node.target.id))
            self.expression(node.value)
            self.emit(node, "BINARY", BIN[type(node.op)])
            self.emit(node, "STORE", node.target.id)
        elif isinstance(node, ast.If):
            self.expression(node.test)
            branch = self.emit(node, "JUMP_FALSE", 0)
            self.statements(node.body)
            end = self.emit(node, "JUMP", 0)
            self.patch(branch)
            self.statements(node.orelse)
            self.patch(end)
        elif isinstance(node, ast.While):
            if node.orelse:
                self.fail(node, "loop else is not supported")
            start = len(self.code)
            self.expression(node.test)
            end = self.emit(node, "JUMP_FALSE", 0)
            loop = {"breaks": [], "continue": start, "iterator": False}
            self.loops.append(loop)
            self.statements(node.body)
            self.emit(node, "JUMP", start)
            self.patch(end)
            for pos in loop["breaks"]:
                self.patch(pos)
            self.loops.pop()
        elif isinstance(node, ast.For):
            if node.orelse or not isinstance(node.target, ast.Name):
                self.fail(node, "for requires a single target name and no else")
            self.expression(node.iter)
            self.emit(node, "ITER")
            start = len(self.code)
            end = self.emit(node, "NEXT", 0)
            self.emit(node, "STORE", self.name(node, node.target.id))
            loop = {"breaks": [], "continue": start, "iterator": True}
            self.loops.append(loop)
            self.statements(node.body)
            self.emit(node, "JUMP", start)
            self.patch(end)
            for pos in loop["breaks"]:
                self.patch(pos)
            self.loops.pop()
        elif isinstance(node, (ast.Break, ast.Continue)):
            if not self.loops:
                self.fail(node, "break/continue outside loop")
            loop = self.loops[-1]
            if isinstance(node, ast.Break):
                if loop["iterator"]:
                    self.emit(node, "POP")
                loop["breaks"].append(self.emit(node, "JUMP", 0))
            else:
                self.emit(node, "JUMP", loop["continue"])
        elif isinstance(node, ast.Return):
            if not self.in_function:
                self.fail(node, "return outside function")
            self.expression(node.value) if node.value else self.emit(node, "CONST", None)
            self.emit(node, "RETURN")
        elif isinstance(node, ast.FunctionDef):
            self.function(node)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                self.emit(node, "IMPORT", self.name(node, alias.name))
                self.emit(node, "STORE", self.name(node, alias.asname or alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.level or node.module is None:
                self.fail(node, "relative imports are not supported")
            for alias in node.names:
                if alias.name == "*":
                    self.fail(node, "wildcard imports are not supported")
                self.emit(node, "IMPORT", self.name(node, node.module))
                self.emit(node, "ATTR", self.name(node, alias.name))
                self.emit(node, "STORE", self.name(node, alias.asname or alias.name))
        elif isinstance(node, ast.Pass):
            pass
        else:
            self.fail(node, f"unsupported statement: {type(node).__name__}")

    def assign(self, target, value):
        if isinstance(target, ast.Name):
            self.expression(value)
            self.emit(target, "STORE", self.name(target, target.id))
        elif isinstance(target, ast.Subscript) and not isinstance(target.slice, ast.Slice):
            self.expression(target.value)
            self.expression(target.slice)
            self.expression(value)
            self.emit(target, "SET_ITEM")
        else:
            self.fail(target, "assignment target must be a name or item")

    def function(self, node):
        if (
            self.in_function
            or self.loops
            or node.decorator_list
            or node.args.vararg
            or node.args.kwarg
            or node.args.kwonlyargs
            or node.args.posonlyargs
        ):
            self.fail(
                node, "functions must be top-level with positional parameters and literal defaults"
            )
        name = self.name(node, node.name)
        if name in self.functions:
            self.fail(node, "duplicate function definition")
        parameters = [self.name(arg, arg.arg) for arg in node.args.args]
        defaults = []
        for value in node.args.defaults:
            try:
                defaults.append(ast.literal_eval(value))
            except (ValueError, TypeError):
                self.fail(value, "default parameters must be literals")
        saved_code, saved_loops = self.code, self.loops
        self.code, self.loops, self.in_function = [], [], True
        self.statements(node.body)
        self.emit(node, "CONST", None)
        self.emit(node, "RETURN")
        self.functions[name] = Function(name, parameters, defaults, self.code)
        self.code, self.loops, self.in_function = saved_code, saved_loops, False

    def expression(self, node):
        if isinstance(node, ast.Constant):
            if not isinstance(node.value, (str, int, float, bool, type(None))):
                self.fail(node, "unsupported literal")
            self.emit(node, "CONST", node.value)
        elif isinstance(node, ast.Name):
            self.emit(node, "LOAD", self.name(node, node.id))
        elif isinstance(node, ast.BinOp) and type(node.op) in BIN:
            self.expression(node.left)
            self.expression(node.right)
            self.emit(node, "BINARY", BIN[type(node.op)])
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd, ast.Not)):
            self.expression(node.operand)
            self.emit(
                node, "UNARY", {ast.USub: "neg", ast.UAdd: "pos", ast.Not: "not"}[type(node.op)]
            )
        elif isinstance(node, ast.BoolOp):
            jumps = []
            for value in node.values[:-1]:
                self.expression(value)
                self.emit(node, "DUP")
                jumps.append(
                    self.emit(
                        node, "JUMP_FALSE" if isinstance(node.op, ast.And) else "JUMP_TRUE", 0
                    )
                )
                self.emit(node, "POP")
            self.expression(node.values[-1])
            for jump in jumps:
                self.patch(jump)
        elif isinstance(node, ast.Compare):
            if len(node.ops) != 1 or type(node.ops[0]) not in CMP:
                self.fail(node, "use explicit 'and' instead of chained comparisons")
            self.expression(node.left)
            self.expression(node.comparators[0])
            self.emit(node, "COMPARE", CMP[type(node.ops[0])])
        elif isinstance(node, (ast.List, ast.Tuple)):
            for value in node.elts:
                self.expression(value)
            self.emit(node, "LIST" if isinstance(node, ast.List) else "TUPLE", len(node.elts))
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if key is None:
                    self.fail(node, "dictionary expansion is not supported")
                self.expression(key)
                self.expression(value)
            self.emit(node, "DICT", len(node.keys))
        elif isinstance(node, ast.Subscript) and not isinstance(node.slice, ast.Slice):
            self.expression(node.value)
            self.expression(node.slice)
            self.emit(node, "GET_ITEM")
        elif isinstance(node, ast.Attribute):
            self.expression(node.value)
            self.emit(node, "ATTR", self.name(node, node.attr))
        elif isinstance(node, ast.Call):
            if any(isinstance(arg, ast.Starred) for arg in node.args) or any(
                k.arg is None for k in node.keywords
            ):
                self.fail(node, "argument expansion is not supported")
            self.expression(node.func)
            for arg in node.args:
                self.expression(arg)
            for keyword in node.keywords:
                self.expression(keyword.value)
            self.emit(node, "CALL", [len(node.args), [self.name(k, k.arg) for k in node.keywords]])
        elif isinstance(node, ast.IfExp):
            self.expression(node.test)
            otherwise = self.emit(node, "JUMP_FALSE", 0)
            self.expression(node.body)
            end = self.emit(node, "JUMP", 0)
            self.patch(otherwise)
            self.expression(node.orelse)
            self.patch(end)
        else:
            self.fail(node, f"unsupported expression: {type(node).__name__}")


def compile_source(source, file="main.proc"):
    if not isinstance(source, str) or len(source.encode()) > 1_000_000:
        raise Diagnostic("SOURCE", "source must be text of at most 1 MB", Location(file))
    try:
        tree = ast.parse(source, filename=file)
    except SyntaxError as error:
        raise Diagnostic(
            "SYNTAX", error.msg, Location(file, error.lineno or 1, error.offset or 1)
        ) from error
    compiler = Compiler(file)
    top_functions = {id(node) for node in tree.body if isinstance(node, ast.FunctionDef)}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and id(node) not in top_functions:
            compiler.fail(node, "function definitions must be directly at module level")
    compiler.statements(tree.body)
    program = Program(
        file, hashlib.sha256(source.encode()).hexdigest(), compiler.code, compiler.functions
    )
    try:
        return program.validate()
    except (ValueError, TypeError) as error:
        raise Diagnostic("COMPILE", str(error), Location(file)) from error
