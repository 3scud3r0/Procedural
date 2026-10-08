"""Measured timings and memory, with environment metadata and stable checksums."""

import hashlib
import json
import platform
import statistics
import time
import tracemalloc
from procedural import Procedural, RandomStream, RewriteRule
from .compiler import compile_source
from .vm import VirtualMachine


def measure(name, function, repeats=5):
    samples = []
    hashes = []
    peaks = []
    function()  # Warmup is explicitly excluded from samples.
    for _ in range(repeats):
        tracemalloc.start()
        started = time.perf_counter()
        result = function()
        elapsed = time.perf_counter() - started
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        samples.append(elapsed)
        peaks.append(peak)
        hashes.append(
            hashlib.sha256(json.dumps(result, sort_keys=True, allow_nan=False).encode()).hexdigest()
        )
    if len(set(hashes)) != 1:
        raise ValueError(f"nonreproducible benchmark: {name}")
    return {
        "name": name,
        "repeats": repeats,
        "seconds": samples,
        "median_seconds": statistics.median(samples),
        "min_seconds": min(samples),
        "max_peak_bytes": max(peaks),
        "result_sha256": hashes[0],
    }


def suite(repeats=5):
    if type(repeats) is not int or not 1 <= repeats <= 100:
        raise ValueError("repeats must be in [1,100]")

    def randoms():
        rng = RandomStream(42)
        return [rng.random() for _ in range(10000)]

    def rewrite():
        return Procedural(42).context.rewrite(
            ["a"] * 100, [RewriteRule(("a",), ("b",))], strategy="first"
        )

    source = "total=0\nfor i in range(1000):\n    total += i * i\nprint(total)"
    program = compile_source(source)

    def vm():
        machine = VirtualMachine()
        machine.execute(program)
        return {"stdout": "".join(machine.stdout), "steps": machine.steps}

    cases = [
        ("rng_10000", randoms),
        ("terrain_32x32", lambda: Procedural(42).generate("terrain")),
        ("graph_200_500", lambda: Procedural(42).generate("graph", nodes=200, edges=500)),
        ("rewrite_100", rewrite),
        ("compile_100", lambda: [compile_source(source).digest for _ in range(100)]),
        ("vm_loop_1000", vm),
    ]
    return {
        "schema": "procedural.benchmarks/1",
        "environment": {
            "python": platform.python_version(),
            "system": platform.system(),
            "machine": platform.machine(),
            "processor": platform.processor(),
        },
        "method": "one warmup; wall clock and tracemalloc per sample; no cross-machine speed claim",
        "cases": [measure(name, fn, repeats) for name, fn in cases],
    }
