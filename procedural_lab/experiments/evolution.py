"""Genetic programming of bounded arithmetic ASTs with held-out evaluation."""

from dataclasses import dataclass
from procedural import Procedural


@dataclass(frozen=True)
class Expression:
    op: str
    value: int = 0
    left: object = None
    right: object = None

    def evaluate(self, x):
        if self.op == "x":
            return x
        if self.op == "constant":
            return self.value
        a, b = self.left.evaluate(x), self.right.evaluate(x)
        result = {"add": lambda: a + b, "sub": lambda: a - b, "mul": lambda: a * b}[self.op]()
        return max(-1_000_000, min(1_000_000, result))

    @property
    def size(self):
        return 1 if self.op in ("x", "constant") else 1 + self.left.size + self.right.size

    def source(self):
        if self.op == "x":
            return "x"
        if self.op == "constant":
            return str(self.value)
        return f"({self.left.source()} {dict(add='+', sub='-', mul='*')[self.op]} {self.right.source()})"

    def to_dict(self):
        if self.op in ("x", "constant"):
            return {"op": self.op, "value": self.value}
        return {"op": self.op, "left": self.left.to_dict(), "right": self.right.to_dict()}


def random_expression(ctx, depth):
    if depth == 0 or ctx.random() < 0.3:
        return Expression("x") if ctx.random() < 0.5 else Expression("constant", ctx.randint(-3, 5))
    return Expression(
        ctx.choose(["add", "sub", "mul"]),
        left=random_expression(ctx, depth - 1),
        right=random_expression(ctx, depth - 1),
    )


def mutate(expression, ctx, depth):
    if depth == 0 or ctx.random() < 0.25 or expression.op in ("x", "constant"):
        return random_expression(ctx, depth)
    if ctx.random() < 0.5:
        return Expression(
            expression.op, left=mutate(expression.left, ctx, depth - 1), right=expression.right
        )
    return Expression(
        expression.op, left=expression.left, right=mutate(expression.right, ctx, depth - 1)
    )


def score(expression, cases):
    return sum(abs(expression.evaluate(x) - y) for x, y in cases) / len(cases)


def evolve_expression(seed=42, generations=100, population=64, max_depth=4, task="quadratic"):
    if task not in ("quadratic", "linear", "square"):
        raise ValueError("task must be quadratic, linear or square")
    for name, value, minimum, maximum in [
        ("generations", generations, 0, 10000),
        ("population", population, 4, 1000),
        ("max_depth", max_depth, 1, 8),
    ]:
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError(f"{name} must be in [{minimum}, {maximum}]")
    target = {
        "quadratic": lambda x: x * x + 3 * x + 2,
        "linear": lambda x: 2 * x + 1,
        "square": lambda x: x * x,
    }[task]
    training = [(x, target(x)) for x in range(-3, 4)]
    heldout = [(x, target(x)) for x in list(range(-10, -3)) + list(range(4, 11))]
    ctx = Procedural(seed).context.fork("evolution")
    candidates = [random_expression(ctx.fork(["initial", i]), max_depth) for i in range(population)]
    history = []
    for generation in range(generations + 1):
        # Held-out cases never influence ranking, selection or early stopping.
        ranked = sorted(
            candidates, key=lambda expr: (score(expr, training), expr.size, expr.source())
        )
        best = ranked[0]
        history.append(
            {
                "generation": generation,
                "training_mae": score(best, training),
                "nodes": best.size,
                "expression": best.source(),
            }
        )
        if generation == generations or score(best, training) == 0:
            break
        next_population = [best]  # Elitism: best training error cannot regress.
        for i in range(1, population):
            stream = ctx.fork(["generation", generation, "child", i])
            tournament = stream.sample(ranked, min(4, len(ranked)))
            parent = min(tournament, key=lambda expr: (score(expr, training), expr.size))
            next_population.append(mutate(parent, stream, max_depth))
        candidates = next_population
    return {
        "schema": "procedural.experiment.evolution/1",
        "seed": seed,
        "task": task,
        "configuration": {
            "generations": generations,
            "population": population,
            "max_depth": max_depth,
        },
        "history": history,
        "best": best.to_dict(),
        "source": f"def generated(x):\n    return {best.source()}\n",
        "training_mae": score(best, training),
        "heldout_mae": score(best, heldout),
        "training_cases": training,
        "heldout_cases": heldout,
        "interpretation": "Search over a fixed arithmetic grammar; no claim of AGI or recursive intelligence.",
    }
