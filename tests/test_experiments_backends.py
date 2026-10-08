import ctypes
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from procedural_lab.experiments import language_game, evolve_expression
from procedural_lab.experiments.communication import Agent, evaluate
from procedural_lab.backends import ArithmeticProgram, default_registry
from procedural import Procedural

ROOT = Path(__file__).resolve().parents[1]


class ExperimentsBackendTests(unittest.TestCase):
    def test_communication_is_reproducible_and_evaluation_does_not_train(self):
        options = dict(
            seed=42,
            agents=6,
            meanings=3,
            symbols=6,
            rounds=400,
            checkpoint=100,
            evaluation_trials=100,
        )
        a, b = language_game(**options), language_game(**options)
        self.assertEqual(a, b)
        self.assertTrue(all(0 <= point["accuracy"] <= 1 for point in a["history"]))
        ctx = Procedural(42).context
        agents = [Agent.create(i, 3, 6, ctx.fork(i)) for i in range(2)]
        before = json.dumps([x.to_dict() for x in agents])
        evaluate(agents, [[0, 1]], 3, ctx, trials=100)
        self.assertEqual(before, json.dumps([x.to_dict() for x in agents]))

    def test_communication_zero_rounds_is_a_true_baseline(self):
        result = language_game(rounds=0, evaluation_trials=50)
        self.assertEqual(len(result["history"]), 1)
        self.assertEqual(result["history"][0]["accuracy"], result["baseline"]["accuracy"])
        with self.assertRaises(ValueError):
            language_game(agents=1)

    def test_evolution_elitism_generalization_and_reproducibility(self):
        options = dict(seed=42, generations=20, population=24, max_depth=3)
        a, b = evolve_expression(**options), evolve_expression(**options)
        self.assertEqual(a, b)
        scores = [point["training_mae"] for point in a["history"]]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertFalse(
            set(x for x, y in a["training_cases"]) & set(x for x, y in a["heldout_cases"])
        )
        self.assertGreaterEqual(a["heldout_mae"], 0)

    def test_arithmetic_ir_python_export_matches_reference(self):
        program = ArithmeticProgram.from_dict(
            json.loads((ROOT / "examples/arithmetic.json").read_text())
        )
        exports = default_registry().export(program)
        self.assertEqual(len(exports), 9)
        namespace = {}
        exec(compile(exports["quadratic.py"], "generated.py", "exec"), namespace)
        for x in [-10, -1, 0, 1, 9, 123.5]:
            self.assertEqual(namespace["quadratic"](x), program.evaluate(x))

    def test_arithmetic_ir_rejects_injection_reserved_names_and_unknown_operations(self):
        for name in ["x); evil();", "while", "class", "select"]:
            with self.assertRaises(ValueError):
                ArithmeticProgram(name, {"op": "x"}).validate()
        with self.assertRaises(ValueError):
            ArithmeticProgram("valid", {"op": "host_exec"}).validate()
        with self.assertRaises(ValueError):
            ArithmeticProgram("valid", {"op": "constant", "value": float("nan")}).validate()
        with self.assertRaises(ValueError):
            default_registry().export(ArithmeticProgram("valid", {"op": "x"}), ["unknown"])

    @unittest.skipUnless(shutil.which("node"), "Node.js unavailable")
    def test_javascript_export_executes_and_matches_ir(self):
        program = ArithmeticProgram.from_dict(
            json.loads((ROOT / "examples/arithmetic.json").read_text())
        )
        source = default_registry().export(program, ["javascript"])["quadratic.mjs"]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "test.mjs"
            path.write_text(
                source + "\nconsole.log(JSON.stringify([-10,-1,0,1,9].map(quadratic)));"
            )
            values = json.loads(subprocess.check_output(["node", str(path)]))
        self.assertEqual(values, [program.evaluate(x) for x in [-10, -1, 0, 1, 9]])

    @unittest.skipUnless(shutil.which("cc") and shutil.which("c++"), "C/C++ compilers unavailable")
    def test_c_and_cpp_exports_compile_and_match_ir(self):
        program = ArithmeticProgram.from_dict(
            json.loads((ROOT / "examples/arithmetic.json").read_text())
        )
        exports = default_registry().export(program, ["c", "cpp"])
        with tempfile.TemporaryDirectory() as folder:
            for extension, compiler in [("c", "cc"), ("cpp", "c++")]:
                source = Path(folder) / f"quadratic.{extension}"
                library = Path(folder) / f"lib{extension}.so"
                source.write_text(exports[source.name])
                subprocess.run(
                    [compiler, "-shared", "-fPIC", str(source), "-o", str(library)],
                    check=True,
                    capture_output=True,
                )
                fn = ctypes.CDLL(str(library)).quadratic
                fn.argtypes = [ctypes.c_double]
                fn.restype = ctypes.c_double
                for x in [-10, -1, 0, 1, 9, 123.5]:
                    self.assertEqual(fn(x), program.evaluate(x))
