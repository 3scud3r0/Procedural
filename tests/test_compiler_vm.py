import copy
import json
import unittest
from procedural import RandomStream
from procedural_lab import compile_source, Program, VirtualMachine, Limits
from procedural_lab.errors import Diagnostic
from procedural_lab.project import Project
from procedural_lab.runner import execute_project


class CompilerVMTests(unittest.TestCase):
    def test_defaults_roundtrip_preserves_data_and_rejects_non_json_literals(self):
        source = 'def f(data={"items": [1, 2]}):\n    return data\nprint(f())'
        program = compile_source(source)
        vm = VirtualMachine()
        vm.execute(Program.from_dict(json.loads(program.to_json())))
        self.assertEqual("".join(vm.stdout), "{'items': [1, 2]}\n")
        for source in ["def f(xs=(1,2)):\n    return xs", "def f(xs={1:2}):\n    return xs"]:
            with self.assertRaises(Diagnostic):
                compile_source(source)

    def test_language_function_and_module_representations_are_reproducible(self):
        source = "import math\ndef f():\n    pass\nprint(math, f, print)"
        first = "".join(self.run_source(source).stdout)
        second = "".join(self.run_source(source).stdout)
        self.assertEqual(first, second)
        self.assertEqual(first, "<module math> <function f> <capability>\n")
        with self.assertRaises(Diagnostic):
            self.run_source("x=(-1)**0.5")

    def run_source(self, source, **options):
        vm = VirtualMachine(**options)
        vm.execute(compile_source(source))
        return vm

    def test_general_functions_recursion_default_arguments_keywords(self):
        source = """def factorial(n):
    if n <= 1:
        return 1
    return n * factorial(n-1)
def scale(x, factor=3):
    return x * factor
print(factorial(20), scale(7), scale(factor=5,x=4))
"""
        vm = self.run_source(source)
        self.assertEqual("".join(vm.stdout), "2432902008176640000 21 20\n")

    def test_loops_break_continue_nested_iteration_and_while(self):
        source = """values=[]
for i in range(5):
    if i == 1:
        continue
    for j in range(4):
        if j == 2:
            break
        append(values,i*10+j)
x=0
while x < 5:
    x += 1
    if x == 3:
        break
print(values,x)
"""
        vm = self.run_source(source)
        self.assertEqual("".join(vm.stdout), "[0, 1, 20, 21, 30, 31, 40, 41] 3\n")

    def test_expression_semantics_match_python_for_seeded_inputs(self):
        rng = RandomStream(42)
        for _ in range(80):
            a, b, c = rng.randint(-20, 20), rng.randint(1, 20), rng.randint(-10, 10)
            source = f"print(({a}*{b}+{c}) // {b}, ({a}+{c}) % {b}, {a} < {c})"
            actual = "".join(self.run_source(source).stdout)
            expected = f"{(a * b + c) // b} {(a + c) % b} {a < c}\n"
            self.assertEqual(actual, expected)

    def test_short_circuit_and_conditional_expression(self):
        vm = self.run_source('print(False and 1/0, True or 1/0, 7 if 3 < 4 else 1/0, "a" in "cat")')
        self.assertEqual("".join(vm.stdout), "False True 7 True\n")

    def test_mutable_default_values_are_isolated_per_call(self):
        vm = self.run_source("def f(xs=[]):\n    append(xs, 1)\n    return xs\nprint(f(),f())")
        self.assertEqual("".join(vm.stdout), "[1] [1]\n")

    def test_collections_and_item_assignment(self):
        vm = self.run_source(
            'xs=[1,2,3]\nxs[1]=9\nd={"x":xs}\nd["y"]=7\nprint(d["x"][1],d["y"],(1,2)[0])'
        )
        self.assertEqual("".join(vm.stdout), "9 7 1\n")

    def test_module_imports_source_locations_and_own_globals(self):
        project = Project(
            {
                "main.proc": "from helper import f\nprint(f(7))",
                "helper.proc": "factor=3\ndef f(x):\n    return factor*x",
            }
        )
        result = execute_project(project, preview=False)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["report"]["stdout"], "21\n")
        project.files["helper.proc"] = "def f(x):\n    return x / 0"
        result = execute_project(project, preview=False)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["location"]["file"], "helper.proc")
        self.assertEqual(result["error"]["location"]["line"], 2)

    def test_module_import_cycles_fail_explicitly(self):
        result = execute_project(
            Project({"main.proc": "import a", "a.proc": "import b", "b.proc": "import a"}),
            preview=False,
        )
        self.assertFalse(result["ok"])
        self.assertIn("circular", result["error"]["message"])

    def test_only_registered_modules_and_attributes_are_accessible(self):
        for source in [
            "import os",
            "print((1).__class__)",
            'print("abc".upper())',
            'open("x","w")',
            'eval("1")',
        ]:
            with self.assertRaises(Diagnostic):
                self.run_source(source)
        vm = self.run_source("from math import sqrt, pi\nprint(sqrt(9),pi > 3)")
        self.assertEqual("".join(vm.stdout), "3.0 True\n")

    def test_unsupported_syntax_is_rejected_instead_of_silently_changed(self):
        sources = [
            "class X:\n    pass",
            "xs=[x for x in range(3)]",
            "def f(*xs):\n    pass",
            "if True:\n    def f():\n        return 1",
            "print(1 < 2 < 3)",
            "x=[1,2][0:1]",
            "try:\n    pass\nexcept:\n    pass",
        ]
        for source in sources:
            with self.subTest(source=source), self.assertRaises(Diagnostic):
                compile_source(source)

    def test_syntax_and_runtime_diagnostics_include_partial_stdout(self):
        with self.assertRaises(Diagnostic) as caught:
            compile_source("def broken(:\n    pass", "invalid.proc")
        self.assertEqual(caught.exception.location.file, "invalid.proc")
        self.assertEqual(caught.exception.location.line, 1)
        vm = VirtualMachine()
        with self.assertRaises(Diagnostic) as caught:
            vm.execute(compile_source('print("before")\nx=1/0', "error.proc"))
        self.assertEqual(caught.exception.location.line, 2)
        self.assertEqual("".join(vm.stdout), "before\n")

    def test_instruction_and_call_limits_stop_nontermination(self):
        with self.assertRaises(Diagnostic) as caught:
            self.run_source("while True:\n    pass", limits=Limits(steps=50))
        self.assertEqual(caught.exception.code, "STEP_LIMIT")
        with self.assertRaises(Diagnostic) as caught:
            self.run_source("def f():\n    return f()\nf()", limits=Limits(calls=8))
        self.assertEqual(caught.exception.code, "CALL_LIMIT")

    def test_value_limits_and_cycles_are_rejected(self):
        for source in ['x="a"*1000', "x=2**1000", "xs=[]\nappend(xs,xs)", "xs=[]\nappend(xs,[xs])"]:
            with self.assertRaises(Diagnostic):
                self.run_source(source, limits=Limits(items=100, integer_bits=100))

    def test_bytecode_roundtrip_digest_and_disassembly(self):
        p = compile_source("def f(x):\n    return x*x\nprint(f(7))")
        restored = Program.from_dict(json.loads(p.to_json()))
        self.assertEqual(p.digest, restored.digest)
        self.assertIn("CALL", restored.disassemble())
        vm = VirtualMachine()
        vm.execute(restored)
        self.assertEqual("".join(vm.stdout), "49\n")

    def test_malformed_bytecode_is_rejected_or_reports_underflow(self):
        p = compile_source("print(1)").to_dict()
        for change in [
            {"op": "HOST_EXEC"},
            {"op": "JUMP", "arg": -1},
            {"op": "CALL", "arg": [1, ["a", "a"]]},
            {"op": "ATTR", "arg": "__class__"},
        ]:
            bad = copy.deepcopy(p)
            bad["code"][0].update(change)
            with self.assertRaises(Diagnostic):
                Program.from_dict(bad)
        bad = copy.deepcopy(p)
        bad["code"] = [{"op": "POP", "arg": None, "line": 1, "column": 1}]
        with self.assertRaises(Diagnostic) as caught:
            VirtualMachine().execute(Program.from_dict(bad))
        self.assertEqual(caught.exception.code, "BYTECODE")

    def test_seeded_artifacts_and_geometry_are_reproducible(self):
        source = 'for i in range(8):\n    sphere(radius=uniform(.1,.4), position=[i,randint(1,3),0])\nemit("data.json",generate("numbers",count=10))'
        project = Project({"main.proc": source}, seed=42)
        first = execute_project(project)
        second = execute_project(project)
        self.assertTrue(first["ok"], first)
        self.assertEqual(first["files"], second["files"])
        self.assertEqual(first["report"]["objects"], 8)
        self.assertIn("scene.png", first["files"])
        project.seed = 43
        self.assertNotEqual(first["files"], execute_project(project)["files"])

    def test_trace_does_not_change_output_and_records_calls(self):
        project = Project({"main.proc": "def f(x):\n    return x+1\nprint(f(2))"})
        a = execute_project(project, preview=False)
        b = execute_project(project, trace=True, preview=False)
        self.assertEqual(a["files"]["scene.json"], b["files"]["scene.json"])
        records = json.loads(b["files"]["trace.json"])
        self.assertTrue(any(row["depth"] == 2 for row in records))

    def test_failure_returns_no_publishable_partial_artifacts(self):
        result = execute_project(Project({"main.proc": 'emit("first.txt","partial")\n1/0'}))
        self.assertFalse(result["ok"])
        self.assertEqual(result["files"], {})
