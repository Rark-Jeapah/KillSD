"""Benchmark-harness E2E test focused on manual mode equivalence."""

from __future__ import annotations

from pathlib import Path

from src.core.storage import ArtifactStore
from src.eval.benchmark_runner import BenchmarkRunner


REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = REPO_ROOT / "data" / "benchmarks" / "csat_math_2028" / "release_smoke.json"


def test_benchmark_runner_manual_mode_equivalence(tmp_path: Path) -> None:
    store = ArtifactStore(root_dir=tmp_path / "artifacts", db_path=tmp_path / "app.db")
    runner = BenchmarkRunner(
        artifact_store=store,
        prompt_dir=REPO_ROOT / "src" / "prompts",
        template_dir=REPO_ROOT / "src" / "render" / "templates",
    )
    dataset = runner.load_dataset(DATASET_PATH)

    report = runner.run_dataset(dataset=dataset, output_dir=tmp_path / "benchmark")

    manual_attempts = [attempt for attempt in report.attempts if attempt.mode.value == "manual"]
    assert len(manual_attempts) == 1
    assert manual_attempts[0].succeeded is True
    assert manual_attempts[0].cost_summary.prompt_count > 0
    assert manual_attempts[0].scorecard is not None
    assert manual_attempts[0].scorecard.artifact_audit.passed is True
    assert report.mode_comparisons
    assert all(comparison.equivalent for comparison in report.mode_comparisons)
    assert report.scorecard.manual_api_equivalent is True
