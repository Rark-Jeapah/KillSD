"""Integration tests for the generated-exam pipeline against real candidate-pool output."""

from __future__ import annotations

import json
from pathlib import Path

from src.assembly.candidate_pool import CandidatePoolBuilder
from src.pipeline.generated_exam import GeneratedExamPipeline


REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = REPO_ROOT / "src" / "render" / "templates"
SUPPORTED_ATOM_IDS = [
    "atom-d1170f7c15a9",
    "atom-f81b2ab6c767",
    "atom-f9684d631a8c",
    "atom-bb0d073139cc",
    "atom-1c4317d67e80",
    "atom-311a529ea04c",
    "atom-991b78d60850",
    "atom-c2ed46456b9d",
    "atom-5d39a6b6e0f6",
    "atom-5480edcc0dcb",
    "atom-aaa349a7160b",
    "atom-0ce427cc63df",
]


def test_generated_exam_runs_from_real_candidate_pool_output(tmp_path: Path) -> None:
    builder = CandidatePoolBuilder(repo_root=REPO_ROOT)
    pool_result = builder.build(
        output_dir=tmp_path / "candidate_pool",
        title="Generated Pool Fixture",
        slot_count=10,
        atom_ids=SUPPORTED_ATOM_IDS,
        run_id="generated-pool-for-generated-exam",
    )

    pipeline = GeneratedExamPipeline(template_dir=TEMPLATE_DIR)
    result = pipeline.run(
        run_id="generated-exam-test",
        candidate_pool_dir=Path(pool_result.output_dir),
        output_dir=tmp_path / "generated_exam",
        slot_count=10,
        title="Generated Exam Fixture",
        compile_pdf=False,
    )

    assert result.slot_count == 10
    assert result.candidate_count == len(SUPPORTED_ATOM_IDS)
    assert result.eligible_candidate_count >= 10
    assert len(result.selected) == 10

    candidate_manifest_path = Path(result.candidate_manifest_path)
    exam_bundle_path = Path(result.exam_bundle_path)
    discard_report_path = Path(result.discard_report_path)
    exam_tex_path = Path(result.exam_tex_path)
    answer_key_tex_path = Path(result.answer_key_tex_path)
    validation_report_tex_path = Path(result.validation_report_tex_path)

    assert candidate_manifest_path.exists()
    assert exam_bundle_path.exists()
    assert discard_report_path.exists()
    assert exam_tex_path.exists()
    assert answer_key_tex_path.exists()
    assert validation_report_tex_path.exists()

    candidate_manifest = json.loads(candidate_manifest_path.read_text(encoding="utf-8"))
    exam_bundle = json.loads(exam_bundle_path.read_text(encoding="utf-8"))
    discard_report = json.loads(discard_report_path.read_text(encoding="utf-8"))
    exam_tex = exam_tex_path.read_text(encoding="utf-8")

    assert candidate_manifest["title"] == "Generated Exam Fixture"
    assert len(candidate_manifest["slots"]) == 10
    assert len(candidate_manifest["candidates"]) == len(SUPPORTED_ATOM_IDS)
    assert all("candidate_pool" in entry["validated_item_path"] for entry in candidate_manifest["candidates"])

    assert exam_bundle["student_metadata"]["title"] == "Generated Exam Fixture"
    assert len(exam_bundle["items"]) == 10
    assert discard_report["selected_count"] == 10
    assert discard_report["total_candidates"] == len(SUPPORTED_ATOM_IDS)

    assert "Generated Exam Fixture" in exam_tex
    assert "source_atom_id" not in exam_tex
    assert "family_id" not in exam_tex
    assert "candidate_id" not in exam_tex
