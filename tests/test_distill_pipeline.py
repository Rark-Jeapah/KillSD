"""Tests for the offline distillation pipeline."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from src.distill.pipeline import DistillPipeline


FIXTURE_PATH = Path("data/source_fixtures/csat_math_2028/sample_items.json")


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


def test_distill_pipeline_loads_csv_manual_input(tmp_path: Path) -> None:
    pipeline = DistillPipeline(spec_id="csat_math_2028")
    source_items = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["items"]
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
