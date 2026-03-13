"""CLI tests for distillation v2 commands."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from src.cli.main import app
from src.distill.curated_batch import compute_items_content_hash
from src.distill.item_card_schema import ManualSourceItem


FIXTURE_PATH = Path("data/source_fixtures/csat_math_2028/sample_items.json")


def _fixture_items() -> list[dict[str, object]]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["items"]


def _write_curated_batch(
    batch_dir: Path,
    *,
    batch_id: str,
    batch_version: str,
    items: list[dict[str, object]],
    items_format: str = "json",
    manifest_overrides: dict[str, object] | None = None,
) -> Path:
    validated_items = [ManualSourceItem.model_validate(item) for item in items]
    items_path = batch_dir / f"{batch_id}.items.{items_format}"
    if items_format == "json":
        items_path.write_text(
            json.dumps({"items": items}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    elif items_format == "jsonl":
        items_path.write_text(
            "\n".join(json.dumps(item, ensure_ascii=False) for item in items) + "\n",
            encoding="utf-8",
        )
    else:  # pragma: no cover - defensive guard for test helper misuse
        raise AssertionError(f"Unsupported items_format: {items_format}")

    manifest = {
        "manifest_version": "2.0",
        "spec_id": "csat_math_2028",
        "batch_id": batch_id,
        "batch_version": batch_version,
        "created_at": "2026-03-12T00:00:00+00:00",
        "items_path": items_path.name,
        "item_count": len(items),
        "content_hash": compute_items_content_hash(validated_items),
        "provenance": {
            "exam_name": "CSAT Mathematics",
            "exam_year": 2028,
            "source_name": "offline_exam_analysis",
            "source_kind": "exam_analysis",
        },
        "metadata": {
            "curation_mode": "manual",
        },
    }
    if manifest_overrides:
        manifest.update(manifest_overrides)

    manifest_path = batch_dir / f"{batch_id}.manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def test_distill_cli_validate_batches_exits_nonzero_on_manifest_mismatch(tmp_path: Path) -> None:
    batch_dir = tmp_path / "invalid_batch"
    batch_dir.mkdir()
    _write_curated_batch(
        batch_dir,
        batch_id="batch-invalid",
        batch_version="2026.03-invalid",
        items=_fixture_items()[:1],
        manifest_overrides={"item_count": 99},
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "distill",
            "validate-batches",
            "--batch-path",
            str(batch_dir),
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["valid"] is False
    assert "item_count mismatch" in payload["batches"][0]["errors"][0]


def test_distill_cli_run_batches_and_coverage_stats(tmp_path: Path) -> None:
    fixture_items = _fixture_items()
    batch_root = tmp_path / "batches"
    first_batch_dir = batch_root / "batch_a"
    second_batch_dir = batch_root / "batch_b"
    first_batch_dir.mkdir(parents=True)
    second_batch_dir.mkdir(parents=True)

    _write_curated_batch(
        first_batch_dir,
        batch_id="batch-a",
        batch_version="2026.03-a",
        items=fixture_items[:1],
        items_format="json",
    )
    _write_curated_batch(
        second_batch_dir,
        batch_id="batch-b",
        batch_version="2026.03-b",
        items=fixture_items[1:2],
        items_format="jsonl",
    )

    output_dir = tmp_path / "distilled"
    runner = CliRunner()

    validate_result = runner.invoke(
        app,
        [
            "distill",
            "validate-batches",
            "--batch-path",
            str(batch_root),
        ],
    )
    assert validate_result.exit_code == 0
    validate_payload = json.loads(validate_result.stdout)
    assert validate_payload["valid"] is True
    assert validate_payload["batch_count"] == 2

    run_result = runner.invoke(
        app,
        [
            "distill",
            "run-batches",
            "--batch-path",
            str(batch_root),
            "--output-dir",
            str(output_dir),
        ],
    )
    assert run_result.exit_code == 0
    run_payload = json.loads(run_result.stdout)
    assert run_payload["counts"]["item_cards"] == 2
    assert run_payload["mode"] == "curated_batches"

    coverage_result = runner.invoke(
        app,
        [
            "distill",
            "coverage-stats",
            "--distilled-dir",
            str(output_dir),
        ],
    )
    assert coverage_result.exit_code == 0
    coverage_payload = json.loads(coverage_result.stdout)
    assert coverage_payload["coverage"]["by_domain"] == {"algebra": 1, "calculus_1": 1}
    assert coverage_payload["coverage"]["by_answer_form"] == {"choice_index": 2}
