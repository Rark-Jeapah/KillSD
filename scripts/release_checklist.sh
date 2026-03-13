#!/usr/bin/env bash
set -euo pipefail

compile_pdf=false
if [[ "${1:-}" == "--compile-pdf" ]]; then
  compile_pdf=true
  shift
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
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

if [[ "$compile_pdf" == "true" ]]; then
  python scripts/run_benchmark.py \
    --dataset data/benchmarks/csat_math_2028/release_smoke.json \
    --compile-pdf
  python -m src.cli.main render exam --run-id release-check --compile-pdf
  python -m src.cli.main render answer-key --run-id release-check --compile-pdf
fi

git status --short --ignored
