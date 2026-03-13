# Bootstrap Guide

This guide covers the public open-source bootstrap flow for the core plus the public `csat_math_2028` plugin.

## 1. Create A Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

## 2. Configure The Environment

Copy the example file and optionally edit it:

```bash
cp .env.example .env
```

Load it into your shell when needed:

```bash
set -a
source .env
set +a
```

Notes:

- The repo does not automatically load `.env`.
- The default smoke path uses the mock provider, so `.env` can stay unchanged.
- `OPENAI_API_KEY` is only required if you explicitly select the OpenAI provider.

## 3. Reset Local Runtime State

```bash
python scripts/reset_runtime_state.py
```

This clears the local runtime directories:

- `artifacts/`
- `out/`
- `var/`

## 4. Verify The Install

```bash
pytest
python -m src.cli.main show-spec
python scripts/run_benchmark.py --dataset data/benchmarks/csat_math_2028/release_smoke.json
```

## 5. Run The Public Smoke Flow

```bash
python -m src.cli.main build-blueprint --run-id demo-run
python -m src.cli.main exam run --run-id demo-run --mode api --provider mock
python -m src.cli.main assemble exam --run-id demo-run
python -m src.cli.main render exam --run-id demo-run --tex-only
python -m src.cli.main render answer-key --run-id demo-run --tex-only
```

## 6. Run The Distillation Smoke Flow

```bash
python -m src.cli.main distill validate-source \
  --source-path data/source_fixtures/csat_math_2028/sample_items.json

python -m src.cli.main distill run \
  --source-path data/source_fixtures/csat_math_2028/sample_items.json \
  --output-dir out/demo-distilled
```

Use an ignored output directory for smoke runs so tracked sample data remains unchanged.

## Optional: OpenAI Provider

After setting `OPENAI_API_KEY`, you can switch the exam run to:

```bash
python -m src.cli.main exam run --run-id demo-openai --mode api --provider openai
```

Relevant variables are documented in `.env.example`.

## Optional: PDF Compilation

If XeLaTeX is installed:

```bash
python -m src.cli.main render exam --run-id demo-run --compile-pdf
python -m src.cli.main render answer-key --run-id demo-run --compile-pdf
```

If your shell cannot find `xelatex`, set `CSAT_XELATEX_PATH` first.
