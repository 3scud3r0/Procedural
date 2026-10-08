"""Multiple seeds expose variation instead of selecting a flattering single run."""

import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from procedural_lab.experiments import language_game, evolve_expression


def suite(seeds=range(8)):
    records = []
    for seed in seeds:
        communication = language_game(seed=seed)
        evolution = evolve_expression(seed=seed)
        records.append(
            {
                "seed": seed,
                "communication_baseline": communication["baseline"]["accuracy"],
                "communication_final": communication["history"][-1]["accuracy"],
                "evolution_generations": evolution["history"][-1]["generation"],
                "evolution_training_mae": evolution["training_mae"],
                "evolution_heldout_mae": evolution["heldout_mae"],
            }
        )
    return {
        "schema": "procedural.experiment-suite/1",
        "records": records,
        "communication_final_mean": statistics.mean(r["communication_final"] for r in records),
        "evolution_exact_heldout_runs": sum(r["evolution_heldout_mae"] == 0 for r in records),
        "interpretation": "Finite supplied tasks and fixed hyperparameters; these results do not establish general intelligence.",
    }


if __name__ == "__main__":
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "benchmarks/multiseed_report.json"
    result = suite()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
