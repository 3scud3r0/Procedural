# Project instructions

- This repository, `3scud3r0/Procedural`, is the destination requested by the user for `procedural.py` and future derivative work in this project.
- Preserve `procedural.py` as a standalone, standard-library-only file. Version changes that alter seeded sequences or semantics explicitly.
- Put compiler/runtime/tooling in `procedural_lab/`; document executable syntax and reject unsupported features rather than ignoring them.
- Keep the PCL interpreter free of Python `eval` and `exec`. Expose host operations through explicit capabilities. Do not claim OS sandboxing.
- Validate changes with meaningful tests; use `python -m unittest discover -s tests -v` and the formatter/linter configured in `pyproject.toml`.
- Keep experiments reproducible and report baselines, limits and held-out results. Never label consensus or self-modification as evidence of AGI/ASI.
- Preserve existing user work. Use this repo for new files; do not move unrelated MarkovJunior assets here.
- Source line count is a delivery metric, not a correctness metric. Prefer clear modules and executable examples over padding.
