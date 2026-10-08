"""Grounded naming game: agents communicate a meaning and get corrective feedback.

The environment supplies discrete meanings and evaluates receiver guesses.
No grammar rewriting cycles, invented outputs, or claim of AGI/ASI.
"""

from dataclasses import dataclass
import math
from procedural import Procedural


@dataclass
class Agent:
    id: int
    encoding: list[list[float]]
    decoding: list[list[float]]

    @classmethod
    def create(cls, id, meanings, symbols, ctx):
        return cls(
            id,
            [[0.1 + ctx.random() for _ in range(symbols)] for _ in range(meanings)],
            [[0.1 + ctx.random() for _ in range(meanings)] for _ in range(symbols)],
        )

    def speak(self, meaning, ctx, exploration=0):
        weights = self.encoding[meaning]
        if ctx.random() < exploration:
            return ctx.randint(0, len(weights) - 1)
        # Greedy with a deterministic tie-breaker; exploration is explicit.
        return max(range(len(weights)), key=lambda i: weights[i])

    def listen(self, symbol):
        weights = self.decoding[symbol]
        return max(range(len(weights)), key=lambda i: weights[i])

    def reinforce(self, meaning, symbol, rate):
        for i in range(len(self.encoding[meaning])):
            self.encoding[meaning][i] *= 1 - rate
        self.encoding[meaning][symbol] += rate
        for i in range(len(self.decoding[symbol])):
            self.decoding[symbol][i] *= 1 - rate
        self.decoding[symbol][meaning] += rate

    def to_dict(self):
        return {"id": self.id, "encoding": self.encoding, "decoding": self.decoding}


def evaluate(agents, edges, meanings, ctx, trials=1000):
    success = 0
    confusion = [[0 for _ in range(meanings)] for _ in range(meanings)]
    used = {}
    for _ in range(trials):
        a, b = ctx.choose(edges)
        if ctx.random() < 0.5:
            a, b = b, a
        meaning = ctx.randint(0, meanings - 1)
        symbol = agents[a].speak(meaning, ctx)
        guess = agents[b].listen(symbol)
        success += guess == meaning
        confusion[meaning][guess] += 1
        used[symbol] = used.get(symbol, 0) + 1
    entropy = -sum((count / trials) * math.log2(count / trials) for count in used.values())
    return {
        "accuracy": success / trials,
        "trials": trials,
        "confusion": confusion,
        "symbols_used": len(used),
        "symbol_entropy_bits": entropy,
    }


def language_game(
    seed=42,
    agents=12,
    meanings=6,
    symbols=12,
    rounds=10000,
    learning_rate=0.2,
    exploration=0.05,
    checkpoint=1000,
    evaluation_trials=1000,
):
    for name, value, minimum, maximum in [
        ("agents", agents, 2, 200),
        ("meanings", meanings, 2, 100),
        ("symbols", symbols, 2, 200),
        ("rounds", rounds, 0, 1_000_000),
        ("checkpoint", checkpoint, 1, 1_000_000),
        ("evaluation_trials", evaluation_trials, 1, 100000),
    ]:
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError(f"{name} must be in [{minimum}, {maximum}]")
    if not 0 < learning_rate <= 1 or not 0 <= exploration <= 1:
        raise ValueError("invalid learning/exploration rate")
    engine = Procedural(seed)
    ctx = engine.context.fork("language-game")
    graph = engine.generate(
        "graph",
        nodes=agents,
        edges=min(agents * 2, agents * (agents - 1) // 2),
        key="communication",
    )
    population = [Agent.create(i, meanings, symbols, ctx.fork(["agent", i])) for i in range(agents)]
    baseline = evaluate(
        population, graph["edges"], meanings, ctx.fork("evaluation"), evaluation_trials
    )
    history = [{"round": 0, **baseline}]
    for round in range(1, rounds + 1):
        a, b = ctx.choose(graph["edges"])
        if ctx.random() < 0.5:
            a, b = b, a
        meaning = ctx.randint(0, meanings - 1)
        symbol = population[a].speak(meaning, ctx, exploration)
        guess = population[b].listen(symbol)
        # Corrective feedback grounds the symbol in a known shared task.
        population[b].reinforce(meaning, symbol, learning_rate)
        if guess == meaning:
            population[a].reinforce(meaning, symbol, learning_rate)
        if round % checkpoint == 0 or round == rounds:
            history.append(
                {
                    "round": round,
                    **evaluate(
                        population,
                        graph["edges"],
                        meanings,
                        ctx.fork("evaluation"),
                        evaluation_trials,
                    ),
                }
            )
    return {
        "schema": "procedural.experiment.communication/1",
        "seed": seed,
        "configuration": {
            "agents": agents,
            "meanings": meanings,
            "symbols": symbols,
            "rounds": rounds,
            "learning_rate": learning_rate,
            "exploration": exploration,
            "evaluation_trials": evaluation_trials,
        },
        "graph": graph,
        "baseline": baseline,
        "history": history,
        "agents": [a.to_dict() for a in population],
        "interpretation": "Accuracy on a supplied naming task; no claim of general intelligence.",
    }
