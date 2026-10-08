"""Behavioral contract of the standalone, renderer-independent procedural core."""

import itertools
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from dataclasses import dataclass

from procedural import (
    Procedural,
    RandomStream,
    Alternative,
    RewriteRule,
    Artifact,
    ConstraintError,
    GenerationLimitError,
    demo,
)


class ProceduralCoreTests(unittest.TestCase):
    def test_standalone_file_runs_without_repository_or_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "procedural.py"
            script.write_bytes((Path(__file__).parents[1] / "procedural.py").read_bytes())
            output = Path(directory) / "result.json"
            subprocess.run(
                [sys.executable, "-I", str(script), "--seed", "42", "--output", str(output)],
                check=True,
                capture_output=True,
                cwd=directory,
            )
            result = json.loads(output.read_text())
            self.assertEqual(result, demo(42))
            namespace = {}
            exec(compile(result["code"], "generated.py", "exec"), namespace)
            function = next(value for value in namespace.values() if callable(value))
            self.assertIn(function(7), [14, 21, 35])

    def test_seed_and_address_are_reproducible_across_processes(self):
        rng = RandomStream(42)
        self.assertEqual(
            [rng.random() for _ in range(5)],
            [
                0.43872669737159675,
                0.3093158000435591,
                0.3139729335121564,
                0.7645437402739114,
                0.08962787426810814,
            ],
        )
        code = (
            "from procedural import demo; import json; print(json.dumps(demo(42),sort_keys=True))"
        )
        outputs = [
            subprocess.check_output(
                [sys.executable, "-c", code], env={**os.environ, "PYTHONHASHSEED": str(seed)}
            )
            for seed in (1, 777)
        ]
        self.assertEqual(*outputs)
        self.assertNotEqual(demo(42), demo(43))

    def test_named_generators_are_isolated_from_draws_and_registration_order(self):
        first, second = Procedural(42), Procedural(42)
        expected = first.generate("numbers", count=20, key="stable")
        for _ in range(100):
            second.context.random()
        second.generate("terrain", width=2, height=2)
        second.register("new", lambda ctx: ctx.random())
        self.assertEqual(expected, second.generate("numbers", count=20, key="stable"))
        self.assertNotEqual(expected, second.generate("numbers", count=20, key="other"))

    def test_unrestricted_python_outputs_and_nested_composition(self):
        @dataclass
        class Entity:
            value: int

        engine = Procedural("custom", builtins=False)

        @engine.generator("entity")
        def entity(ctx, maximum=100):
            return Entity(ctx.randint(0, maximum))

        @engine.generator("world")
        def world(ctx):
            return [ctx.generate("entity", key=i) for i in range(8)]

        result = engine.generate("world")
        self.assertTrue(all(isinstance(item, Entity) for item in result))
        self.assertEqual(result, engine.generate("world"))
        self.assertEqual(engine.generators, ("entity", "world"))
        with self.assertRaises(ValueError):
            engine.register("entity", entity)

    def test_weighted_selection_zero_weights_and_large_weights(self):
        rng = RandomStream(123)
        for _ in range(50):
            self.assertEqual(rng.choose(["forbidden", "allowed"], [0, 1e308]), "allowed")
            self.assertIn(rng.choose([1, 2], [1e308, 1e308]), [1, 2])
        for weights in ([0, 0], [-1, 2], [float("inf"), 1], [1]):
            with self.assertRaises(ValueError):
                rng.choose([1, 2], weights)

    def test_random_bounds_large_integers_sampling_and_no_global_rng_mutation(self):
        import random

        before = random.getstate()
        rng = RandomStream(b"bytes")
        for _ in range(100):
            self.assertTrue(0 <= rng.random() < 1)
            self.assertTrue(-2 <= rng.uniform(-2, 3) <= 3)
            self.assertTrue(2**300 <= rng.randint(2**300, 2**301) <= 2**301)
        self.assertEqual(random.getstate(), before)
        self.assertEqual(len(set(rng.sample(list(range(100)), 20))), 20)
        self.assertEqual(sorted(rng.shuffle(range(10))), list(range(10)))
        with self.assertRaises(ValueError):
            rng.randbelow(0)

    def test_noise_is_spatially_continuous_and_independent_of_draws(self):
        ctx = Procedural(42).context
        for coordinate in (-1.0, 0.0, 4.5):
            a = ctx.noise(coordinate, 3.1)
            b = ctx.noise(coordinate + 0.00001, 3.1)
            self.assertLess(abs(a - b), 0.0001)
            self.assertTrue(-1 <= ctx.fbm(coordinate, 3.1) <= 1)
        expected = ctx.noise(-3.2, 4.1, 5.6, 9.0)
        ctx.random()
        self.assertEqual(expected, ctx.noise(-3.2, 4.1, 5.6, 9.0))
        with self.assertRaises(ValueError):
            ctx.noise(float("nan"))

    def test_terrain_tiles_agree_at_shared_coordinates(self):
        engine = Procedural(42)
        a = engine.generate("terrain", width=3, height=4, origin=(0, 0))
        b = engine.generate("terrain", width=3, height=4, origin=(2, 0))
        self.assertEqual([row[2] for row in a["values"]], [row[0] for row in b["values"]])

    def test_grammar_supports_weights_literal_braces_and_recursive_termination(self):
        ctx = Procedural(42).context
        rules = {"start": ["{start}x", "end"], "literal": "{{not_a_rule}}"}
        text = ctx.grammar(rules, "{start}|{literal}", max_depth=3)
        self.assertTrue(text.startswith("end"))
        self.assertTrue(text.endswith("|{not_a_rule}"))
        self.assertEqual(
            ctx.grammar({"start": [Alternative("no", 0), Alternative("yes", 1)]}), "yes"
        )

    def test_grammar_rejects_undefined_rules_and_expansion_bombs(self):
        ctx = Procedural(42).context
        with self.assertRaises(ValueError):
            ctx.grammar({"start": "{missing}"})
        for options in ({"max_depth": 3}, {"max_expansions": 4}, {"max_chars": 2}):
            with self.assertRaises(GenerationLimitError):
                ctx.grammar({"start": "{start}{start}"}, **options)
        self.assertEqual(ctx.grammar({"start": "ok"}, max_chars=2), "ok")

    def test_rewrite_generic_symbols_callbacks_and_explicit_limits(self):
        ctx = Procedural(42).context
        rule = RewriteRule((0,), lambda context, match: [context.randint(1, 9)])
        result = ctx.rewrite([0, 0, {"custom": "object"}], [rule])
        self.assertTrue(all(1 <= value <= 9 for value in result[:2]))
        self.assertEqual(result[-1], {"custom": "object"})
        self.assertEqual(
            ctx.rewrite("aa", [RewriteRule(("a", "a"), ("b",))], strategy="first"), ["b"]
        )
        with self.assertRaises(GenerationLimitError):
            ctx.rewrite(["a"], [RewriteRule(("a",), ("a",))], max_steps=3)
        with self.assertRaises(GenerationLimitError):
            ctx.rewrite(itertools.repeat("a"), [], max_symbols=3)
        with self.assertRaises(GenerationLimitError):
            ctx.rewrite(
                ["a"], [RewriteRule(("a",), lambda c, m: itertools.repeat("b"))], max_symbols=3
            )

    def test_constraint_search_reproducibility_and_failure(self):
        engine = Procedural(42, builtins=False)
        engine.register("candidate", lambda ctx: ctx.randint(0, 100))
        args = dict(constraints=[lambda n: n % 7 == 0], attempts=100)
        value = engine.generate("candidate", **args)
        self.assertEqual(value % 7, 0)
        self.assertEqual(value, engine.generate("candidate", **args))
        with self.assertRaises(ConstraintError):
            engine.generate("candidate", constraints=[lambda n: False], attempts=4)

        def broken(ctx):
            raise RuntimeError("generator bug")

        engine.register("broken", broken)
        with self.assertRaisesRegex(RuntimeError, "generator bug"):
            engine.generate("broken", attempts=100)

    def test_pipeline_changes_output_types_without_touching_input(self):
        ctx = Procedural(42).context
        original = {"number": 7}
        result = ctx.pipeline(
            original,
            [
                lambda ctx, data: list(range(data["number"])),
                lambda ctx, data: {"values": ctx.shuffle(data)},
                lambda ctx, data: json.dumps(data),
            ],
        )
        self.assertEqual(sorted(json.loads(result)["values"]), list(range(7)))
        self.assertEqual(original, {"number": 7})

    def test_graph_edge_count_connectivity_and_no_self_edges(self):
        graph = Procedural(42).generate("graph", nodes=30, edges=50)
        self.assertEqual(len(graph["edges"]), 50)
        self.assertEqual(len({tuple(edge) for edge in graph["edges"]}), 50)
        visited = {0}
        for _ in graph["nodes"]:
            for a, b in graph["edges"]:
                self.assertNotEqual(a, b)
                if a in visited or b in visited:
                    visited.update((a, b))
        self.assertEqual(visited, set(graph["nodes"]))
        self.assertEqual(Procedural(42).generate("graph", nodes=0), {"nodes": [], "edges": []})
        with self.assertRaises(ValueError):
            Procedural(42).generate("graph", nodes=5, edges=3)

    def test_artifact_encodings_and_directory_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(
                json.loads(Artifact("nested/data.json", {"ação": 1}).save(directory).read_text()),
                {"ação": 1},
            )
            self.assertEqual(
                Artifact("source.cpp", "int main() { return 0; }", "text")
                .save(directory)
                .read_text(),
                "int main() { return 0; }",
            )
            self.assertEqual(
                Artifact("data.bin", b"\x00\xff", "bytes").save(directory).read_bytes(), b"\x00\xff"
            )
            for name in ("../escape", "/tmp/escape", "."):
                with self.assertRaises(ValueError):
                    Artifact(name, {}).save(directory)


if __name__ == "__main__":
    unittest.main()
