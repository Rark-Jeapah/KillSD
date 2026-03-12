"""Benchmark-harness E2E test focused on API mode and reproducibility."""

from __future__ import annotations

from pathlib import Path

from src.core.storage import ArtifactStore
from src.eval.benchmark_runner import BenchmarkRunner


REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = REPO_ROOT / "data" / "benchmarks" / "csat_math_2028" / "release_smoke.json"


def test_benchmark_runner_api_reproducibility(tmp_path: Path) -> None:
    store = ArtifactStore(root_dir=tmp_path / "artifacts", db_path=tmp_path / "app.db")
    runner = BenchmarkRunner(
        artifact_store=store,
        prompt_dir=REPO_ROOT / "src" / "prompts",
        template_dir=REPO_ROOT / "src" / "render" / "templates",
    )
    dataset = runner.load_dataset(DATASET_PATH)

    report = runner.run_dataset(dataset=dataset, output_dir=tmp_path / "benchmark")

    api_attempts = [attempt for attempt in report.attempts if attempt.mode.value == "api"]
    assert len(api_attempts) == 2
    assert all(attempt.succeeded for attempt in api_attempts)
    assert all(attempt.cost_summary.prompt_count > 0 for attempt in api_attempts)
    assert all(attempt.scorecard is not None for attempt in api_attempts)
    assert all(attempt.scorecard.prompt_version_audit.passed for attempt in api_attempts if attempt.scorecard)
    assert report.reproducibility_reports
    assert all(report_item.equivalent for report_item in report.reproducibility_reports)
