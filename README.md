# CSAT Math Core and Public Plugin

This repository publishes an open-source exam-generation pipeline core plus one public subject plugin: `csat_math_2028`.

The public release includes only reusable pipeline code, the CSAT math plugin/spec, and synthetic or open-source-safe fixtures. It does not include proprietary exam corpora, internal benchmark outputs, or future private plugins for other exams.

## What Is In This Repository

- Public pipeline core for artifact storage, orchestration, validation, rendering, benchmarking, and provider adapters.
- Public `csat_math_2028` plugin and its canonical exam spec.
- Synthetic source fixtures and distilled sample outputs that are safe to publish.
- Mock-provider benchmark fixtures that work from a clean clone without API credentials.

## What Is Not In This Repository

- Raw copyrighted past exams or private source PDFs.
- Machine-local runtime outputs under `artifacts/`, `out/`, or `var/`.
- Private plugins for other exams, proprietary prompts, or internal evaluation datasets.

## Public and Private Boundary

- Open-source core:
  `src/core`, `src/config`, `src/cli`, `src/orchestrator`, `src/validators`, `src/render`, `src/providers`, `src/eval`, `src/distill`, and shared prompt contracts.
- Public subject plugin in this repo:
  `src/plugins/csat_math_2028`, `exam_specs/csat_math_2028.yaml`, `data/source_fixtures/csat_math_2028/`, `data/distilled/csat_math_2028/`, and `data/benchmarks/csat_math_2028/release_smoke.json`.
- Future private plugins:
  separate packages or repos that implement `SubjectPlugin` from `src/plugins/__init__.py` and register themselves through the `csat_math_mvp.plugins` Python entry-point group.

Detailed guidance lives in `docs/open_source_boundary.md`.

## Architecture

- `ExamSpec` fixes the exam invariants for a subject plugin.
- `PromptPacket` and `ManualExchangePacket` keep manual mode and API mode on the same data contract.
- JSON artifact envelopes are written to disk, while SQLite stores the artifact index only.
- Rendering consumes `RenderBundle` artifacts and produces exam papers, answer keys, and validation reports.
- Offline distillation converts manual fixtures into runtime-safe distilled data.

## Requirements

- Python 3.11+
- macOS or Linux shell environment
- Optional: XeLaTeX for PDF compilation
- Optional: `OPENAI_API_KEY` only if you want to use the OpenAI provider instead of the mock provider

## Quick Start From A Clean Clone

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
cp .env.example .env
set -a
source .env
set +a

python scripts/reset_runtime_state.py
pytest

python -m src.cli.main show-spec
python -m src.cli.main build-blueprint --run-id demo-run
python -m src.cli.main exam run --run-id demo-run --mode api --provider mock
python -m src.cli.main assemble exam --run-id demo-run
python -m src.cli.main render exam --run-id demo-run --tex-only
python -m src.cli.main render answer-key --run-id demo-run --tex-only

python -m src.cli.main distill validate-source \
  --source-path data/source_fixtures/csat_math_2028/sample_items.json

python -m src.cli.main distill run \
  --source-path data/source_fixtures/csat_math_2028/sample_items.json \
  --output-dir out/demo-distilled

python scripts/run_benchmark.py --dataset data/benchmarks/csat_math_2028/release_smoke.json
uvicorn src.api.app:app --reload
```

Notes:

- The repository does not auto-load `.env`; source it in your shell if you use it.
- The clean-clone smoke path uses the mock provider, so no API key is required.
- `--tex-only` skips XeLaTeX compilation and still verifies the render pipeline plus manifest generation.

More detailed setup guidance lives in `docs/bootstrap.md`.

## Environment Configuration

Use `.env.example` as the starting point for local configuration.

Important variables:

- `CSAT_DEFAULT_SPEC_ID`: default plugin/spec to load.
- `CSAT_ARTIFACT_ROOT`, `CSAT_DATABASE_PATH`, `CSAT_DATA_ROOT`: override runtime locations if needed.
- `CSAT_XELATEX_PATH`: optional XeLaTeX binary path for PDF builds.
- `OPENAI_API_KEY`: required only for the OpenAI provider.
- `CSAT_OPENAI_MODEL`, `CSAT_OPENAI_TIMEOUT_SECONDS`, `CSAT_OPENAI_MAX_RETRIES`: optional OpenAI tuning.

## Runtime Outputs

- `artifacts/`: JSON artifact envelopes
- `out/`: rendered documents, benchmark outputs, and scratch pipeline outputs
- `var/`: SQLite index and other local runtime state

These paths are intentionally ignored in git. To clear local runtime state:

```bash
python scripts/reset_runtime_state.py
```

If artifact files still exist but the SQLite index is missing, rebuild it with:

```bash
python scripts/reindex_artifacts.py
```

## Release Workflow

- Clean-clone release checklist:
  `docs/release_checklist.md`
- One-command helper:
  `scripts/release_checklist.sh`
- Contributor guidance:
  `CONTRIBUTING.md`

## Release Notes

### 0.1.0-oss-preview (2026-03-13)

- First public packaging pass for the open-source core plus the `csat_math_2028` plugin.
- Added explicit OSS documentation for bootstrap, contribution policy, release verification, and public/private plugin boundaries.
- Standardized runtime cleanup and ignore rules so local benchmark, render, and SQLite outputs are not part of the release surface.
- Kept only synthetic/open-source-safe sample fixtures and release-smoke benchmark data in the documented public dataset set.

## License

This project is released under the MIT License. See `LICENSE`.
