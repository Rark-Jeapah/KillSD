# Contributing

## Scope

This repository is the public open-source release of the reusable CSAT math pipeline core plus the public `csat_math_2028` plugin.

Keep contributions inside that public scope:

- core pipeline code
- public plugin code and spec
- synthetic/open-source-safe fixtures
- tests, docs, and release automation

Do not contribute:

- raw or licensed exam PDFs
- private plugins for other exams
- secrets, API keys, or provider billing metadata
- runtime outputs from `artifacts/`, `out/`, or `var/`
- machine-local paths captured in docs, fixtures, or reports

## Development Setup

See `docs/bootstrap.md` for the full bootstrap flow.

Minimal setup:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
python scripts/reset_runtime_state.py
pytest
```

## Contribution Rules

- Keep the boundary between core and subject plugins explicit.
- Keep new sample data synthetic or otherwise safe to publish.
- Write outputs from smoke tests and benchmarks into ignored runtime directories only.
- Do not check in `.env`, runtime databases, render outputs, or benchmark dumps.
- Prefer repo-relative paths in serialized metadata and docs.
- Update `README.md`, `docs/bootstrap.md`, or `docs/release_checklist.md` when the public bootstrap or release flow changes.

## Before Opening A PR

Run the public release checks:

```bash
python scripts/reset_runtime_state.py
pytest
python scripts/run_benchmark.py --dataset data/benchmarks/csat_math_2028/release_smoke.json
python -m src.cli.main distill validate-source \
  --source-path data/source_fixtures/csat_math_2028/sample_items.json
git status --short --ignored
```

Optional PDF gate:

```bash
python scripts/run_benchmark.py \
  --dataset data/benchmarks/csat_math_2028/release_smoke.json \
  --compile-pdf
```

## Plugin Extensions

Future private plugins should live in separate repos or packages and implement `SubjectPlugin` from `src/plugins/__init__.py`.

If you are working on the public plugin boundary itself, update `docs/open_source_boundary.md` together with the code change.

## Licensing

By contributing to this repository, you agree that your contributions will be licensed under the MIT License in `LICENSE`.
