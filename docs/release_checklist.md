# Release Checklist

This checklist is designed to work from a clean clone and to keep all generated state inside ignored runtime directories.

## Preflight

- Python 3.11+ is available.
- Optional: XeLaTeX is installed if you want the PDF compilation gate.
- Optional: `.env` is present and sourced if you need custom runtime paths or the OpenAI provider.

## Clean-Clone Command Sequence

```bash
git clone <REPO_URL> killsd
cd killsd

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'

if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

python scripts/reset_runtime_state.py
pytest

python scripts/run_benchmark.py --dataset data/benchmarks/csat_math_2028/release_smoke.json

python -m src.cli.main distill validate-source \
  --source-path data/source_fixtures/csat_math_2028/sample_items.json

python -m src.cli.main distill run \
  --source-path data/source_fixtures/csat_math_2028/sample_items.json \
  --output-dir out/release_check/distilled

python -m src.cli.main show-spec
python -m src.cli.main build-blueprint --run-id release-check
python -m src.cli.main exam run --run-id release-check --mode api --provider mock
python -m src.cli.main assemble exam --run-id release-check
python -m src.cli.main render exam --run-id release-check --tex-only
python -m src.cli.main render answer-key --run-id release-check --tex-only

git status --short --ignored
```

## Optional PDF Gate

Run this only on a machine with XeLaTeX available:

```bash
python scripts/run_benchmark.py \
  --dataset data/benchmarks/csat_math_2028/release_smoke.json \
  --compile-pdf

python -m src.cli.main render exam --run-id release-check --compile-pdf
python -m src.cli.main render answer-key --run-id release-check --compile-pdf
```

If `xelatex` is not on `PATH`, export `CSAT_XELATEX_PATH` before the PDF gate.

## Release Gates

- `pytest` passes from the clean clone.
- `scripts/run_benchmark.py` succeeds on `release_smoke`.
- `distill validate-source` succeeds on the public synthetic fixture.
- `distill run` writes only to ignored runtime output paths.
- `render exam` and `render answer-key` succeed in `--tex-only` mode on a clean clone.
- `git status --short --ignored` shows only expected ignored runtime paths after running the checklist.

## Helper Script

The same flow is available as:

```bash
./scripts/release_checklist.sh
```

To include the PDF gate:

```bash
./scripts/release_checklist.sh --compile-pdf
```
