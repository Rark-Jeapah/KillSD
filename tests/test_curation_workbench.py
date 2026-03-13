"""Tests for curated batch authoring helpers and coverage reporting."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

from src.distill.curated_batch import compute_items_content_hash
from src.distill.item_card_schema import ManualSourceItem


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = REPO_ROOT / "data" / "source_fixtures" / "csat_math_2028" / "sample_items.json"


def _fixture_items() -> list[dict[str, object]]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["items"]


def _run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _write_curated_batch(
    batch_dir: Path,
    *,
    batch_id: str,
    batch_version: str,
    items: list[dict[str, object]],
    manifest_overrides: dict[str, object] | None = None,
) -> Path:
    validated_items = [ManualSourceItem.model_validate(item) for item in items]
    items_path = batch_dir / f"{batch_id}.items.json"
    items_path.write_text(
        json.dumps({"items": items}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

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


def test_init_curated_batch_creates_empty_draft_batch(tmp_path: Path) -> None:
    output_dir = tmp_path / "draft_batch"
    result = _run_script(
        "scripts/init_curated_batch.py",
        "--template",
        "empty",
        "--batch-id",
        "draft-batch",
        "--batch-version",
        "2026.03.13",
        "--output-dir",
        str(output_dir),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["batch_id"] == "draft-batch"
    assert payload["template_name"] == "empty"
    assert payload["item_count"] == 0

    manifest_path = output_dir / "draft-batch.manifest.json"
    items_path = output_dir / "draft-batch.items.json"
    assert manifest_path.exists()
    assert items_path.exists()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    items_payload = json.loads(items_path.read_text(encoding="utf-8"))
    assert manifest["item_count"] == 0
    assert items_payload["items"] == []


def test_validate_curated_batches_reports_semantic_errors_and_conflicts(tmp_path: Path) -> None:
    fixture_items = _fixture_items()
    batch_root = tmp_path / "batches"
    batch_root.mkdir()

    batch_a = batch_root / "batch_a"
    batch_b = batch_root / "batch_b"
    batch_c = batch_root / "batch_c"
    batch_a.mkdir()
    batch_b.mkdir()
    batch_c.mkdir()

    conflicting_log_item = copy.deepcopy(fixture_items[0])
    conflicting_log_item["stem"] = "Updated version of the same log source item."

    invalid_short_answer = copy.deepcopy(fixture_items[2])
    invalid_short_answer["allowed_answer_forms"] = []
    invalid_short_answer["solution_steps"][1]["dependencies"] = ["missing-step"]

    _write_curated_batch(
        batch_a,
        batch_id="batch-a",
        batch_version="2026.03-a",
        items=[fixture_items[0]],
    )
    _write_curated_batch(
        batch_b,
        batch_id="batch-b",
        batch_version="2026.03-b",
        items=[conflicting_log_item],
    )
    _write_curated_batch(
        batch_c,
        batch_id="batch-c",
        batch_version="2026.03-c",
        items=[invalid_short_answer],
    )

    result = _run_script(
        "scripts/validate_curated_batches.py",
        "--batch-path",
        str(batch_root),
    )

    assert result.returncode == 1, result.stdout
    payload = json.loads(result.stdout)
    assert payload["valid"] is False
    assert payload["batch_count"] == 3
    assert len(payload["duplicates"]["source_item_conflicts"]) == 1

    invalid_batch = next(batch for batch in payload["batches"] if batch["batch_id"] == "batch-c")
    item_errors = invalid_batch["item_issues"][0]["errors"]
    assert any("allowed_answer_form" in error for error in item_errors)
    assert any("unknown dependency" in error for error in item_errors)


def test_report_coverage_gaps_reports_missing_areas_and_unsupported_atoms(tmp_path: Path) -> None:
    fixture_items = _fixture_items()
    batch_root = tmp_path / "batches"
    batch_dir = batch_root / "batch_gap"
    batch_dir.mkdir(parents=True)

    _write_curated_batch(
        batch_dir,
        batch_id="batch-gap",
        batch_version="2026.03-gap",
        items=[fixture_items[0], fixture_items[2], fixture_items[3]],
    )

    result = _run_script(
        "scripts/report_coverage_gaps.py",
        "--batch-path",
        str(batch_root),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["validation"]["valid"] is True
    assert payload["counts"]["retained_items"] == 3
    assert payload["counts"]["by_domain"] == {
        "algebra": 1,
        "calculus_1": 1,
        "probability_statistics": 1,
    }
    assert payload["counts"]["by_answer_form"] == {
        "choice_index": 1,
        "reduced_fraction": 2,
    }
    assert payload["family_coverage"]["supported_atom_count"] > 0
    assert any(
        any(reason["code"] == "topic_not_supported" for reason in atom["reasons"])
        for atom in payload["unsupported_atoms"]
    )
    assert any(area["skill_tag"] == "limit" for area in payload["missing_topic_areas"])
