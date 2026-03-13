# Open-Source Boundary

This repository is intentionally split between a reusable public core, one public subject plugin, and a clean extension point for future private plugins.

## Public Surface In This Repository

| Area | Purpose | Public status |
| --- | --- | --- |
| `src/core`, `src/config`, `src/cli`, `src/orchestrator`, `src/validators`, `src/render`, `src/providers`, `src/eval`, `src/distill` | Reusable pipeline core | Public |
| `src/plugins/csat_math_2028` | Public CSAT math plugin implementation | Public |
| `exam_specs/csat_math_2028.yaml` | Canonical public CSAT math exam spec | Public |
| `data/source_fixtures/csat_math_2028/` | Synthetic source fixtures for distillation and tests | Public |
| `data/distilled/csat_math_2028/` | Distilled sample outputs derived from synthetic fixtures | Public |
| `data/benchmarks/csat_math_2028/release_smoke.json` | Clean-clone benchmark fixture using the mock provider | Public |
| `tests/fixtures/` | Open-source-safe validator and portability fixtures | Public |

## Future Private Repositories

These should move to separate private packages or repos instead of living in this public repository:

- Plugins for other exams or licensed subject domains.
- Raw exam corpora, scans, PDFs, answer booklets, or any material with redistribution limits.
- Proprietary prompt variants, private rubrics, or internal reasoning datasets.
- Internal evaluation runs, benchmark outputs, reports, and machine-local runtime databases.
- Provider credentials, billing configuration, and private deployment glue.

## Plugin Contract

Subject plugins implement `SubjectPlugin` from `src/plugins/__init__.py`.

The public core resolves plugins in two ways:

1. Built-in public plugins shipped in this repository.
2. External packages registered through the `csat_math_mvp.plugins` entry-point group.

Example for a future private plugin package:

```toml
[project.entry-points."csat_math_mvp.plugins"]
private_exam_2030 = "private_exam_2030.plugin:PrivateExam2030Plugin"
```

That package should own:

- Its plugin implementation
- Its exam spec files
- Any private distilled data or source fixture inputs
- Any private benchmark fixtures or proprietary prompt assets

## Data Policy

Only keep data in this public repo if all of the following are true:

- It is synthetic, contributor-authored, or otherwise safe to redistribute.
- It does not depend on machine-local file paths.
- It does not require secrets to validate the public smoke path.
- It is small enough to serve as a fixture, not a runtime dump.

Runtime-generated directories such as `artifacts/`, `out/`, and `var/` are not part of the public data surface.
