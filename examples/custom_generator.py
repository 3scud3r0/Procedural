"""Ordinary Python has the full standalone API, without PCL syntax restrictions."""

from procedural import Procedural

engine = Procedural(seed=42)


@engine.generator("character")
def character(ctx, level=1):
    return {
        "class": ctx.choose(["mage", "ranger", "warrior"]),
        "health": ctx.randint(10, 20) * level,
        "skills": ctx.sample(["fire", "ice", "stealth", "healing", "craft"], 2),
    }


@engine.generator("party")
def party(ctx, count=4):
    return [ctx.generate("character", key=i, level=ctx.randint(1, 5)) for i in range(count)]


if __name__ == "__main__":
    print(engine.generate("party"))
