"""Run the release-hardening benchmark harness."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.config.settings import get_settings
from src.eval.benchmark_runner import BenchmarkRunner


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run CSAT benchmark harness")
    parser.add_argument(
        "--dataset",
        default="data/benchmarks/csat_math_2028/release_smoke.json",
        help="Path to the benchmark dataset fixture.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory where benchmark outputs will be written.",
    )
    parser.add_argument(
        "--compile-pdf",
        action="store_true",
        help="Override dataset cases to require XeLaTeX PDF compilation.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    dataset_path = Path(args.dataset)
    if not dataset_path.is_absolute():
        dataset_path = settings.repo_root / dataset_path

    output_dir = Path(args.output_dir) if args.output_dir else settings.repo_root / "out" / "benchmarks" / dataset_path.stem
    if not output_dir.is_absolute():
        output_dir = settings.repo_root / output_dir

    runner = BenchmarkRunner()
    dataset = runner.load_dataset(dataset_path)
    if args.compile_pdf:
        dataset = dataset.model_copy(
            update={
                "cases": [
                    case.model_copy(update={"compile_pdf": True}) for case in dataset.cases
                ]
            }
        )

    report = runner.run_dataset(dataset=dataset, output_dir=output_dir)
    report_path = output_dir / "benchmark_report.json"
    print(report_path)
    print(report.scorecard.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
