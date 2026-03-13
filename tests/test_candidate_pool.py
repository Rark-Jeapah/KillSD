"""Tests for generated candidate-pool construction and mini-alpha assembly."""

from __future__ import annotations

import json
from pathlib import Path

from src.assembly.candidate_pool import CandidatePoolBuilder
from src.assembly.mini_alpha import MiniAlphaAssembler
from src.distill.atom_extractor import InsightAtom


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


def test_generated_candidate_pool_builds_manifest_and_assembles_mini_alpha(
    tmp_path: Path,
) -> None:
    builder = CandidatePoolBuilder(repo_root=REPO_ROOT)
    pool_result = builder.build(
        output_dir=tmp_path / "candidate_pool",
        title="Generated Pool Fixture",
        slot_count=10,
        atom_ids=SUPPORTED_ATOM_IDS,
        run_id="generated-pool-test",
    )

    assert pool_result.candidate_count == len(SUPPORTED_ATOM_IDS)
    assert pool_result.eligible_candidate_count >= 10
    assert Path(pool_result.slot_plan_path).exists()
    assert Path(pool_result.candidate_pool_manifest_path).exists()
    assert Path(pool_result.mini_alpha_manifest_path).exists()

    manifest_payload = json.loads(Path(pool_result.mini_alpha_manifest_path).read_text(encoding="utf-8"))
    assert manifest_payload["title"] == "Generated Pool Fixture"
    assert len(manifest_payload["slots"]) == 10
    assert len(manifest_payload["candidates"]) == len(SUPPORTED_ATOM_IDS)
    assert all(entry["source_atom_id"] for entry in manifest_payload["candidates"])
    assert all(entry["family_id"] for entry in manifest_payload["candidates"])
    assert all(entry["atom_signatures"] for entry in manifest_payload["candidates"])

    first_candidate = pool_result.candidates[0]
    assert Path(first_candidate.validated_item_path).exists()
    assert Path(first_candidate.validator_report_path).exists()
    assert Path(first_candidate.candidate_dir, "candidate_bundle.json").exists()

    assembler = MiniAlphaAssembler(template_dir=TEMPLATE_DIR)
    result = assembler.assemble(
        run_id="generated-pool-mini-alpha",
        manifest=assembler.load_manifest(Path(pool_result.mini_alpha_manifest_path)),
        output_dir=tmp_path / "mini_alpha",
        compile_pdf=False,
    )

    assert len(result.selected) == 10
    assert all(selection.source_atom_id for selection in result.selected)
    assert all(selection.family_id for selection in result.selected)
    assert Path(result.discard_rate_report_path).exists()
    assert Path(result.regenerate_candidates_path).exists()
    assert Path(result.bundle_json_path).exists()

    discard_payload = json.loads(Path(result.discard_rate_report_path).read_text(encoding="utf-8"))
    regenerate_payload = json.loads(Path(result.regenerate_candidates_path).read_text(encoding="utf-8"))
    assert discard_payload["selected_count"] == 10
    assert discard_payload["total_candidates"] == len(SUPPORTED_ATOM_IDS)
    assert regenerate_payload == []


def test_candidate_pool_resolves_curated_batch_refs_from_atom_metadata(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    atoms_dir = repo_root / "data" / "distilled" / "csat_math_2028"
    atoms_dir.mkdir(parents=True, exist_ok=True)

    atoms = [
        InsightAtom(
            atom_id="atom-a",
            label="A",
            topic="log_equation_domain",
            allowed_answer_forms=["choice_index"],
            source_batch_ids=["batch-a"],
            source_batch_versions=["2026.03-a"],
            source_batch_hashes=["sha256:aaa"],
        ),
        InsightAtom(
            atom_id="atom-b",
            label="B",
            topic="derivative_monotonicity",
            allowed_answer_forms=["choice_index"],
            source_batch_ids=["batch-a"],
            source_batch_versions=["2026.03-b"],
            source_batch_hashes=["sha256:bbb"],
        ),
        InsightAtom(
            atom_id="atom-c",
            label="C",
            topic="conditional_probability_table",
            allowed_answer_forms=["reduced_fraction"],
            source_batch_ids=["batch-c"],
            source_batch_versions=["2026.03-c"],
            source_batch_hashes=["sha256:ccc"],
        ),
    ]
    (atoms_dir / "atoms.json").write_text(
        json.dumps({"atoms": [atom.model_dump(mode="json") for atom in atoms]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    builder = CandidatePoolBuilder(repo_root=repo_root)
    resolved_batch_only, skipped_batch_only = builder.resolve_atoms(
        curated_batch_refs=["batch-a"],
    )
    assert [atom.atom_id for atom in resolved_batch_only] == ["atom-a", "atom-b"]
    assert skipped_batch_only == []

    resolved_batch_version, skipped_batch_version = builder.resolve_atoms(
        curated_batch_refs=["batch-a@2026.03-b"],
    )
    assert [atom.atom_id for atom in resolved_batch_version] == ["atom-b"]
    assert skipped_batch_version == []
