"""Núcleo procedural independente — Python 3.10+, somente biblioteca padrão.

Copie este arquivo e importe ``Procedural``. Um gerador é uma função Python
``(contexto, **parametros) -> qualquer objeto``; não existe formato de saída
obrigatório. O núcleo oferece aleatoriedade reproduzível, fluxos nomeados,
ruído, gramáticas, reescrita, restrições, pipelines e exportação.

Exemplo::

    engine = Procedural(seed=42)

    @engine.generator("personagem")
    def personagem(ctx, nivel=1):
        return {"classe": ctx.choose(["mago", "arqueiro"]),
                "vida": ctx.randint(10, 20) * nivel}

    print(engine.generate("personagem", nivel=3, key="protagonista"))

As chaves identificam resultados: repetir semente, parâmetros e chave reproduz
o resultado. Use chaves diferentes para instâncias diferentes. Dentro de um
gerador, ``ctx.random()`` avança seu próprio fluxo. Nenhum estado aleatório global
é usado. A API não exige renderizador, WebGL, Pillow ou o pacote MarkovJunior.

Execute ``python procedural.py --seed 42 --output resultado.json`` para a demo.
MIT License — Copyright (c) 2026 Markov-Procedural contributors.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

__version__ = "1.0.0"
__all__ = ["Procedural", "Context", "RandomStream", "Alternative", "RewriteRule",
           "Artifact", "ConstraintError", "GenerationLimitError", "demo"]


class ConstraintError(ValueError):
    """Nenhuma tentativa de geração satisfez todas as restrições."""


class GenerationLimitError(RuntimeError):
    """Uma gramática ou reescrita alcançou o limite explícito de trabalho."""


def _integer(value: int, name: str, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} deve ser um inteiro")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} deve ser >= {minimum}")
    return value


def _finite(value: float, name: str) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} deve ser finito")
    return value


def _encode(value: Any) -> bytes:
    """Endereços estáveis: JSON canônico, sem hash() dependente do processo."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _derive(parent: bytes, key: Any) -> bytes:
    encoded = _encode(key)
    return hashlib.sha256(parent + len(encoded).to_bytes(8, "big") + encoded).digest()


class RandomStream:
    """PRNG baseado em SHA-256, com algoritmo explícito e fluxos derivados.

    Não substitui a sequência DotNetRandom dos modelos originais MarkovJunior.
    A mesma semente/chave produz a mesma sequência em Python e Pyodide.
    """

    def __init__(self, seed: int | str | bytes = 0, *, _digest: bytes | None = None):
        if _digest is not None:
            self._digest = _digest
        elif isinstance(seed, bytes):
            self._digest = hashlib.sha256(b"procedural/1:bytes:" + seed).digest()
        elif isinstance(seed, (int, str)) and not isinstance(seed, bool):
            self._digest = hashlib.sha256(b"procedural/1:json:" + _encode(seed)).digest()
        else:
            raise TypeError("seed deve ser int, str ou bytes")
        self._counter = 0

    def fork(self, key: Any) -> RandomStream:
        """Cria um fluxo sem consumir nem depender do estado do fluxo pai."""
        return RandomStream(_digest=_derive(self._digest, key))

    def _block(self) -> bytes:
        block = hashlib.sha256(self._digest + self._counter.to_bytes(16, "big")).digest()
        self._counter += 1
        return block

    def random(self) -> float:
        return (int.from_bytes(self._block()[:8], "big") >> 11) / (1 << 53)

    def randbelow(self, stop: int) -> int:
        _integer(stop, "stop", 1)
        bits = (stop - 1).bit_length()
        if bits == 0:
            return 0
        size = (bits + 7) // 8
        while True:
            raw = b"".join(self._block() for _ in range((size + 31) // 32))
            value = int.from_bytes(raw[:size], "big") & ((1 << bits) - 1)
            if value < stop:
                return value

    def randint(self, minimum: int, maximum: int) -> int:
        _integer(minimum, "minimum")
        _integer(maximum, "maximum")
        if minimum > maximum:
            raise ValueError("minimum deve ser <= maximum")
        return minimum + self.randbelow(maximum - minimum + 1)

    def uniform(self, minimum: float = 0, maximum: float = 1) -> float:
        minimum, maximum = _finite(minimum, "minimum"), _finite(maximum, "maximum")
        if minimum > maximum:
            raise ValueError("minimum deve ser <= maximum")
        t = self.random()
        return minimum * (1 - t) + maximum * t

    def normal(self, mean: float = 0, deviation: float = 1) -> float:
        mean, deviation = _finite(mean, "mean"), _finite(deviation, "deviation")
        if deviation < 0:
            raise ValueError("deviation deve ser >= 0")
        return mean + deviation * math.sqrt(-2 * math.log(1 - self.random())) * math.cos(2 * math.pi * self.random())

    def choose(self, values: Sequence[Any], weights: Sequence[float] | None = None) -> Any:
        if not values:
            raise ValueError("values não pode ser vazio")
        if weights is None:
            return values[self.randbelow(len(values))]
        if len(values) != len(weights):
            raise ValueError("values e weights devem ter o mesmo tamanho")
        weights = [_finite(w, "weight") for w in weights]
        if any(w < 0 for w in weights) or max(weights) == 0:
            raise ValueError("pesos devem ser não negativos, com pelo menos um positivo")
        largest = max(weights)
        normalized = [w / largest for w in weights]
        target = self.random() * math.fsum(normalized)
        total = 0.0
        for value, weight in zip(values, normalized):
            total += weight
            if target < total:
                return value
        return values[max(i for i, w in enumerate(weights) if w > 0)]

    def shuffle(self, values: Iterable[Any]) -> list[Any]:
        result = list(values)
        for i in range(len(result) - 1, 0, -1):
            j = self.randbelow(i + 1)
            result[i], result[j] = result[j], result[i]
        return result

    def sample(self, values: Sequence[Any], count: int) -> list[Any]:
        _integer(count, "count", 0)
        if count > len(values):
            raise ValueError("count não pode superar o tamanho de values")
        return self.shuffle(values)[:count]


@dataclass(frozen=True)
class Alternative:
    text: str
    weight: float = 1.0

    def __post_init__(self):
        if not isinstance(self.text, str):
            raise TypeError("text deve ser str")
        weight = _finite(self.weight, "weight")
        if weight < 0:
            raise ValueError("weight deve ser não negativo")
        object.__setattr__(self, "weight", weight)


@dataclass(frozen=True)
class RewriteRule:
    """Padrão contíguo de símbolos; substituição fixa ou função (ctx, match)."""

    pattern: tuple[Any, ...]
    replacement: Sequence[Any] | Callable[[Context, tuple[Any, ...]], Iterable[Any]]
    weight: float = 1.0

    def __post_init__(self):
        if not self.pattern:
            raise ValueError("pattern não pode ser vazio")
        weight = _finite(self.weight, "weight")
        if weight <= 0:
            raise ValueError("weight deve ser positivo")
        object.__setattr__(self, "pattern", tuple(self.pattern))
        object.__setattr__(self, "weight", weight)


@dataclass(frozen=True)
class Artifact:
    """Saída opcional; geradores também podem retornar objetos sem exportá-los."""

    name: str
    content: Any
    format: str = "json"

    def to_bytes(self) -> bytes:
        if self.format == "json":
            return (json.dumps(self.content, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
        if self.format == "text":
            if not isinstance(self.content, str):
                raise TypeError("artefato text exige str")
            return self.content.encode("utf-8")
        if self.format == "bytes":
            if not isinstance(self.content, bytes):
                raise TypeError("artefato bytes exige bytes")
            return self.content
        raise ValueError("format deve ser json, text ou bytes")

    def save(self, directory: str | Path) -> Path:
        root = Path(directory).resolve()
        name = Path(self.name)
        if not self.name or name.is_absolute() or ".." in name.parts:
            raise ValueError("name deve ser um caminho relativo sem '..'")
        target = (root / name).resolve()
        if not target.is_relative_to(root) or target == root:
            raise ValueError("artefato deve ficar dentro do diretório de saída")
        content = self.to_bytes()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return target


_GRAMMAR_TOKEN = re.compile(r"\{\{|\}\}|\{([A-Za-z_]\w*)\}")


@dataclass
class Context:
    """Contexto passado aos geradores. ``data`` é local a cada geração/fluxo."""

    rng: RandomStream
    engine: Procedural
    data: dict[str, Any] = field(default_factory=dict)
    _noise_streams: dict[bytes, RandomStream] = field(default_factory=dict, repr=False)
    _noise_values: dict[tuple[bytes, tuple[int, ...]], float] = field(default_factory=dict, repr=False)

    def fork(self, key: Any) -> Context:
        return Context(self.rng.fork(key), self.engine)

    def random(self) -> float:
        return self.rng.random()

    def randint(self, minimum: int, maximum: int) -> int:
        return self.rng.randint(minimum, maximum)

    def uniform(self, minimum: float = 0, maximum: float = 1) -> float:
        return self.rng.uniform(minimum, maximum)

    def normal(self, mean: float = 0, deviation: float = 1) -> float:
        return self.rng.normal(mean, deviation)

    def choose(self, values: Sequence[Any], weights: Sequence[float] | None = None) -> Any:
        return self.rng.choose(values, weights)

    def shuffle(self, values: Iterable[Any]) -> list[Any]:
        return self.rng.shuffle(values)

    def sample(self, values: Sequence[Any], count: int) -> list[Any]:
        return self.rng.sample(values, count)

    def generate(self, name: str, *, key: Any = None, constraints: Iterable[Callable[[Any], bool]] = (),
                 attempts: int = 1, **parameters: Any) -> Any:
        """Componha geradores preservando o endereço aleatório deste contexto."""
        return self.engine._generate(self, name, key, constraints, attempts, parameters)

    def noise(self, *coordinates: float, key: Any = "noise") -> float:
        """Value noise suave de 1 a 4 dimensões, no intervalo [-1, 1]."""
        if not 1 <= len(coordinates) <= 4:
            raise ValueError("noise aceita de 1 a 4 coordenadas")
        coords = [_finite(c, "coordinate") for c in coordinates]
        cells = [math.floor(c) for c in coords]
        fractions = [c - i for c, i in zip(coords, cells)]
        smooth = [t * t * t * (t * (t * 6 - 15) + 10) for t in fractions]
        address = _encode(key)
        stream = self._noise_streams.get(address)
        if stream is None:
            stream = self.rng.fork(["noise", key])
            if len(self._noise_streams) >= 128:
                self._noise_streams.pop(next(iter(self._noise_streams)))
            self._noise_streams[address] = stream
        value = 0.0
        for corner in itertools.product((0, 1), repeat=len(coords)):
            lattice = tuple(i + bit for i, bit in zip(cells, corner))
            weight = math.prod(t if bit else 1 - t for t, bit in zip(smooth, corner))
            cache_key = (stream._digest, lattice)
            sample = self._noise_values.get(cache_key)
            if sample is None:
                sample = stream.fork(lattice).random() * 2 - 1
                if len(self._noise_values) >= 8192:
                    self._noise_values.pop(next(iter(self._noise_values)))
                self._noise_values[cache_key] = sample
            value += sample * weight
        return max(-1.0, min(1.0, value))

    def fbm(self, *coordinates: float, octaves: int = 4, frequency: float = 1,
            lacunarity: float = 2, persistence: float = 0.5, key: Any = "fbm") -> float:
        """Soma normalizada de oitavas de noise, mantendo o intervalo [-1, 1]."""
        _integer(octaves, "octaves", 1)
        if octaves > 32:
            raise ValueError("octaves deve ser <= 32")
        frequency, lacunarity = _finite(frequency, "frequency"), _finite(lacunarity, "lacunarity")
        persistence = _finite(persistence, "persistence")
        if frequency <= 0 or lacunarity <= 0 or not 0 < persistence <= 1:
            raise ValueError("frequency/lacunarity devem ser positivos; persistence deve estar em (0, 1]")
        amplitude, total, norm = 1.0, 0.0, 0.0
        for octave in range(octaves):
            total += amplitude * self.noise(*(c * frequency for c in coordinates), key=[key, octave])
            norm += amplitude
            frequency *= lacunarity
            amplitude *= persistence
        return total / norm

    def grammar(self, rules: Mapping[str, str | Sequence[str | Alternative]], start: str = "{start}", *,
                max_depth: int = 32, max_expansions: int = 10000, max_chars: int = 100000) -> str:
        """Expande {regras}; {{ e }} produzem chaves literais, sem eval/exec.

        No limite de profundidade, escolhe alternativas terminais. Recursões
        sem alternativa terminal falham com GenerationLimitError.
        """
        _integer(max_depth, "max_depth", 0)
        _integer(max_expansions, "max_expansions", 1)
        _integer(max_chars, "max_chars", 0)
        if max_depth > 200:
            raise ValueError("max_depth deve ser <= 200")
        normalized = {}
        for name, options in rules.items():
            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_]\w*", name):
                raise ValueError(f"nome de regra inválido: {name!r}")
            if isinstance(options, str):
                options = [options]
            choices = [item if isinstance(item, Alternative) else Alternative(item) for item in options]
            if not choices or any(not isinstance(item.text, str) for item in choices):
                raise ValueError(f"regra {name!r} exige alternativas de texto")
            weights = [_finite(item.weight, "weight") for item in choices]
            if any(w < 0 for w in weights) or not any(w > 0 for w in weights):
                raise ValueError(f"pesos inválidos na regra {name!r}")
            normalized[name] = choices
        for text in [start] + [a.text for choices in normalized.values() for a in choices]:
            for match in _GRAMMAR_TOKEN.finditer(text):
                if match.group(1) and match.group(1) not in normalized:
                    raise ValueError(f"regra não definida: {match.group(1)}")
        expansions = 0

        def expand(text: str, depth: int) -> str:
            nonlocal expansions
            parts, length, offset = [], 0, 0

            def append(part: str):
                nonlocal length
                length += len(part)
                if length > max_chars:
                    raise GenerationLimitError("gramática excedeu max_chars")
                parts.append(part)

            for match in _GRAMMAR_TOKEN.finditer(text):
                append(text[offset:match.start()])
                name = match.group(1)
                if name is None:
                    append("{" if match.group() == "{{" else "}")
                else:
                    expansions += 1
                    if expansions > max_expansions:
                        raise GenerationLimitError("gramática excedeu max_expansions")
                    choices = normalized[name]
                    if depth >= max_depth:
                        choices = [a for a in choices if a.weight > 0 and not any(m.group(1) for m in _GRAMMAR_TOKEN.finditer(a.text))]
                    if not choices:
                        raise GenerationLimitError(f"regra {name!r} não termina em max_depth")
                    selected = self.choose(choices, [a.weight for a in choices])
                    append(expand(selected.text, depth + 1))
                offset = match.end()
            append(text[offset:])
            return "".join(parts)

        return expand(start, 0)

    def rewrite(self, symbols: Iterable[Any], rules: Sequence[RewriteRule], *,
                max_steps: int = 10000, max_symbols: int = 100000, strategy: str = "random") -> list[Any]:
        """Reescrita de sequências genéricas: um match por passo.

        random sorteia entre todos os matches usando pesos das regras; first
        usa ordem de regra e posição. Retorna ao não haver matches; alcançar um
        limite com trabalho restante produz erro, nunca sucesso incompleto.
        """
        _integer(max_steps, "max_steps", 0)
        _integer(max_symbols, "max_symbols", 0)
        if strategy not in ("first", "random"):
            raise ValueError("strategy deve ser first ou random")
        result = list(itertools.islice(iter(symbols), max_symbols + 1))
        for step in range(max_steps + 1):
            if len(result) > max_symbols:
                raise GenerationLimitError("reescrita excedeu max_symbols")
            matches = []
            for rule in rules:
                size = len(rule.pattern)
                for offset in range(len(result) - size + 1):
                    if tuple(result[offset:offset + size]) == tuple(rule.pattern):
                        matches.append((rule, offset))
                        if strategy == "first":
                            break
                if matches and strategy == "first":
                    break
            if not matches:
                return result
            if step == max_steps:
                raise GenerationLimitError("reescrita excedeu max_steps")
            rule, offset = matches[0] if strategy == "first" else self.choose(matches, [r.weight for r, _ in matches])
            matched = tuple(result[offset:offset + len(rule.pattern)])
            replacement = rule.replacement(self, matched) if callable(rule.replacement) else rule.replacement
            replacement = list(itertools.islice(iter(replacement), max_symbols + 1))
            if len(result) - len(rule.pattern) + len(replacement) > max_symbols:
                raise GenerationLimitError("reescrita excedeu max_symbols")
            result[offset:offset + len(rule.pattern)] = replacement
        raise AssertionError("estado de reescrita inválido")

    def pipeline(self, value: Any, stages: Iterable[Callable[[Context, Any], Any]]) -> Any:
        """Cada estágio (contexto, valor) transforma qualquer tipo de objeto."""
        for index, stage in enumerate(stages):
            value = stage(self.fork(["stage", index]), value)
        return value


class Procedural:
    """Registro extensível e ponto de entrada. Instâncias isolam seus geradores."""

    def __init__(self, seed: int | str | bytes = 0, *, builtins: bool = True):
        self.seed = seed
        self.context = Context(RandomStream(seed), self)
        self._generators: dict[str, Callable[..., Any]] = {}
        if builtins:
            for name, generator in _BUILTINS.items():
                self.register(name, generator)

    @property
    def generators(self) -> tuple[str, ...]:
        return tuple(sorted(self._generators))

    def register(self, name: str, function: Callable[..., Any], *, replace: bool = False) -> Callable[..., Any]:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("name deve ser texto não vazio")
        if not callable(function):
            raise TypeError("function deve ser chamável")
        if name in self._generators and not replace:
            raise ValueError(f"gerador já registrado: {name}")
        self._generators[name] = function
        return function

    def generator(self, name: str, *, replace: bool = False):
        def decorator(function):
            return self.register(name, function, replace=replace)
        return decorator

    def generate(self, name: str, *, key: Any = None, constraints: Iterable[Callable[[Any], bool]] = (),
                 attempts: int = 1, **parameters: Any) -> Any:
        return self._generate(self.context, name, key, constraints, attempts, parameters)

    def _generate(self, parent: Context, name: str, key: Any, constraints: Iterable[Callable[[Any], bool]],
                  attempts: int, parameters: dict[str, Any]) -> Any:
        if name not in self._generators:
            raise KeyError(f"gerador não registrado: {name}; disponíveis: {self.generators}")
        _integer(attempts, "attempts", 1)
        constraints = tuple(constraints)
        if any(not callable(predicate) for predicate in constraints):
            raise TypeError("constraints deve conter funções (resultado) -> bool")
        stream = parent.fork(["generate", name, key])
        for attempt in range(attempts):
            value = self._generators[name](stream.fork(["attempt", attempt]), **parameters)
            if all(predicate(value) for predicate in constraints):
                return value
        raise ConstraintError(f"gerador {name!r} falhou nas restrições após {attempts} tentativa(s)")


def _numbers(ctx: Context, count: int = 10, minimum: float = 0, maximum: float = 1,
             integers: bool = False) -> list[float | int]:
    _integer(count, "count", 0)
    draw = ctx.randint if integers else ctx.uniform
    return [draw(minimum, maximum) for _ in range(count)]


def _grammar(ctx: Context, rules: Mapping[str, Any], start: str = "{start}", **limits: Any) -> str:
    return ctx.grammar(rules, start, **limits)


def _terrain(ctx: Context, width: int = 32, height: int = 32, scale: float = 0.08,
             octaves: int = 4, amplitude: float = 10, origin: Sequence[float] = (0, 0)) -> dict[str, Any]:
    _integer(width, "width", 1)
    _integer(height, "height", 1)
    if width * height > 1_000_000:
        raise ValueError("terrain deve ter no máximo 1.000.000 células")
    scale, amplitude = _finite(scale, "scale"), _finite(amplitude, "amplitude")
    if scale <= 0 or amplitude < 0 or len(origin) != 2:
        raise ValueError("scale deve ser positivo, amplitude não negativa e origin deve ter duas coordenadas")
    ox, oy = (_finite(c, "origin") for c in origin)
    values = [[ctx.fbm((x + ox) * scale, (y + oy) * scale, octaves=octaves) * amplitude
               for x in range(width)] for y in range(height)]
    return {"width": width, "height": height, "values": values}


def _graph(ctx: Context, nodes: int = 8, edges: int | None = None, connected: bool = True) -> dict[str, Any]:
    _integer(nodes, "nodes", 0)
    if nodes > 2000:
        raise ValueError("graph deve ter no máximo 2000 nós")
    maximum = nodes * (nodes - 1) // 2
    minimum = max(0, nodes - 1) if connected else 0
    edges = minimum if edges is None else _integer(edges, "edges", 0)
    if not minimum <= edges <= maximum:
        raise ValueError(f"edges deve estar entre {minimum} e {maximum}")
    chosen = set()
    if connected:
        order = ctx.shuffle(range(nodes))
        for i in range(1, nodes):
            chosen.add(tuple(sorted((order[i], order[ctx.rng.randbelow(i)]))))
    if len(chosen) < edges:
        candidates = [(a, b) for a in range(nodes) for b in range(a + 1, nodes) if (a, b) not in chosen]
        chosen.update(ctx.sample(candidates, edges - len(chosen)))
    return {"nodes": list(range(nodes)), "edges": [list(edge) for edge in sorted(chosen)]}


_BUILTINS = {"numbers": _numbers, "grammar": _grammar, "terrain": _terrain, "graph": _graph}


def demo(seed: int | str | bytes = 42) -> dict[str, Any]:
    """Demonstra composição: dados, texto/código, terreno e estrutura de conexões."""
    engine = Procedural(seed)

    @engine.generator("character")
    def character(ctx, level=1):
        return {"class": ctx.choose(["mage", "ranger", "warrior"]), "health": ctx.randint(10, 20) * level}

    return {
        "character": engine.generate("character", level=3, key="hero"),
        "numbers": engine.generate("numbers", count=6, minimum=0, maximum=100, integers=True),
        "sentence": engine.generate("grammar", rules={"start": "The {place} contains {thing}.",
            "place": ["forest", "city", "cave"], "thing": ["a garden", "a machine", "a portal"]}),
        "code": engine.generate("grammar", key="code", rules={"start": "def {name}(x):\n    return x * {factor}\n",
            "name": ["transform", "scale"], "factor": ["2", "3", "5"]}),
        "terrain": engine.generate("terrain", width=8, height=8),
        "graph": engine.generate("graph", nodes=8, edges=10),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, help="salvar demonstração em JSON")
    args = parser.parse_args()
    result = demo(args.seed)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(Artifact(args.output.name, result).to_bytes())
        print(args.output)
    else:
        print(Artifact("demo.json", result).to_bytes().decode("utf-8"), end="")


if __name__ == "__main__":
    main()
