"""Tests for the offline distillation pipeline."""

from __future__ import annotations

import copy
import csv
import json
from pathlib import Path

from src.distill.curated_batch import compute_items_content_hash
from src.distill.item_card_schema import ManualSourceItem
from src.distill.pipeline import DistillPipeline


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
    created_at: str = "2026-03-12T00:00:00+00:00",
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
        "created_at": created_at,
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


def test_distill_pipeline_generates_required_outputs(tmp_path: Path) -> None:
    pipeline = DistillPipeline(spec_id="csat_math_2028")
    output_dir = tmp_path / "distilled"

    manifest = pipeline.run(source_path=FIXTURE_PATH, output_dir=output_dir)

    assert manifest["counts"]["source_items"] == 5
    for file_name in [
        "atoms.json",
        "distractors.json",
        "topic_graph.json",
        "diagram_templates.json",
        "style_rules.yaml",
        "fingerprints.json",
    ]:
        assert (output_dir / file_name).exists()

    atoms_payload = json.loads((output_dir / "atoms.json").read_text(encoding="utf-8"))
    distractors_payload = json.loads((output_dir / "distractors.json").read_text(encoding="utf-8"))
    fingerprints_payload = json.loads((output_dir / "fingerprints.json").read_text(encoding="utf-8"))

    assert atoms_payload["atoms"]
    assert {"atom_id", "label", "topic", "prerequisites"} <= atoms_payload["atoms"][0].keys()
    assert distractors_payload["distractors"]
    assert {
        "distractor_id",
        "error_type",
        "trigger",
        "wrong_move",
        "plausible_choice_shape",
        "reject_if_too_obvious",
    } <= distractors_payload["distractors"][0].keys()
    assert fingerprints_payload["candidate_pairs"]
    assert manifest["manifest_version"] == "2.0"
    assert "coverage" in manifest
    assert "generated_files" in manifest


def test_distill_pipeline_loads_csv_manual_input(tmp_path: Path) -> None:
    pipeline = DistillPipeline(spec_id="csat_math_2028")
    source_items = _fixture_items()
    csv_path = tmp_path / "sample_items.csv"

    fieldnames = [
        "source_item_id",
        "source_kind",
        "source_label",
        "source_year",
        "source_path",
        "subject_area",
        "topic",
        "subtopics",
        "item_format",
        "score",
        "difficulty",
        "stem",
        "choices",
        "answer",
        "solution_steps",
        "distractors",
        "diagram_tags",
        "style_notes",
        "allowed_answer_forms",
        "trigger_patterns",
        "source_metadata",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for item in source_items[:2]:
            row = item.copy()
            for key in [
                "subtopics",
                "choices",
                "solution_steps",
                "distractors",
                "diagram_tags",
                "style_notes",
                "allowed_answer_forms",
                "trigger_patterns",
                "source_metadata",
            ]:
                row[key] = json.dumps(row[key], ensure_ascii=False)
            writer.writerow(row)

    loaded_items = pipeline.load_source_items(csv_path)
    assert len(loaded_items) == 2
    assert loaded_items[0].source_item_id == "fixture-log-domain-01"


def test_distill_pipeline_validates_curated_batches_from_json_and_jsonl(tmp_path: Path) -> None:
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
        items=fixture_items[:2],
        items_format="json",
    )
    _write_curated_batch(
        second_batch_dir,
        batch_id="batch-b",
        batch_version="2026.03-b",
        items=fixture_items[2:4],
        items_format="jsonl",
    )

    pipeline = DistillPipeline(spec_id="csat_math_2028")
    report = pipeline.validate_curated_batches(batch_root)

    assert report["valid"] is True
    assert report["batch_count"] == 2
    assert report["item_count"] == 4
    assert {entry["batch_id"] for entry in report["batches"]} == {"batch-a", "batch-b"}
    assert all(not entry["errors"] for entry in report["batches"])
    assert any(entry["items_path"].endswith(".jsonl") for entry in report["batches"])


def test_distill_pipeline_run_batches_deduplicates_and_versions_items(tmp_path: Path) -> None:
    fixture_items = _fixture_items()
    batch_root = tmp_path / "batches"
    first_batch_dir = batch_root / "batch_a"
    second_batch_dir = batch_root / "batch_b"
    first_batch_dir.mkdir(parents=True)
    second_batch_dir.mkdir(parents=True)

    updated_log_item = copy.deepcopy(fixture_items[0])
    updated_log_item["stem"] = (
        "실수 x에 대하여 log_2(x-1)+log_2(x-3)=2를 만족하는 x의 값을 "
        "검토한 뒤 최종 답을 고르는 문항이다."
    )

    _write_curated_batch(
        first_batch_dir,
        batch_id="batch-a",
        batch_version="2026.03-a",
        items=[fixture_items[0], fixture_items[1]],
        items_format="json",
        created_at="2026-03-10T00:00:00+00:00",
    )
    _write_curated_batch(
        second_batch_dir,
        batch_id="batch-b",
        batch_version="2026.03-b",
        items=[fixture_items[1], updated_log_item],
        items_format="jsonl",
        created_at="2026-03-11T00:00:00+00:00",
    )

    pipeline = DistillPipeline(spec_id="csat_math_2028")
    output_dir = tmp_path / "distilled"
    manifest = pipeline.run_batches(batch_path=batch_root, output_dir=output_dir)

    assert manifest["counts"]["source_items"] == 4
    assert manifest["counts"]["retained_source_items"] == 2
    assert manifest["counts"]["item_cards"] == 2
    assert manifest["dedup"]["item_cards"]["exact_duplicates"] == 1
    assert manifest["dedup"]["item_cards"]["superseded_versions"] == 1
    assert manifest["dedup"]["item_cards"]["version_groups"] == 1
    assert len(manifest["version_history"]) == 2
    assert manifest["coverage"]["by_topic"] == {
        "derivative_monotonicity": 1,
        "log_equation_domain": 1,
    }
    assert all("sha256:" in entry["sha256"] for entry in manifest["generated_files"])
    assert manifest["source_batch_hashes"] == [
        entry["content_hash"] for entry in manifest["source_batches"]
    ]

    item_cards_payload = json.loads((output_dir / "item_cards.json").read_text(encoding="utf-8"))
    derivative_card = next(
        item for item in item_cards_payload["items"] if item["source_item_id"] == "fixture-derivative-02"
    )
    log_card = next(
        item for item in item_cards_payload["items"] if item["source_item_id"] == "fixture-log-domain-01"
    )
    assert derivative_card["source_batch_ids"] == ["batch-a", "batch-b"]
    assert log_card["source_batch_ids"] == ["batch-b"]
    assert derivative_card["record_version"].startswith("sha256:")

    coverage = pipeline.coverage_stats_from_distilled_dir(output_dir)
    assert coverage["coverage"]["by_domain"] == {"algebra": 1, "calculus_1": 1}
