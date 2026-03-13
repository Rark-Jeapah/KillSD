"""Tests for real family coverage reporting against curated batch fixtures."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BATCH_FIXTURE = REPO_ROOT / "data" / "curated_batches" / "csat_math_2028" / "batch_01"


def test_family_coverage_report_for_batch_01_is_explicit_and_gap_free() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/report_coverage_gaps.py",
            "--batch-path",
            str(BATCH_FIXTURE),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    family_coverage = payload["family_coverage"]

    assert payload["validation"]["valid"] is True
    assert payload["counts"]["retained_items"] == 12
    assert payload["counts"]["by_domain"] == {
        "algebra": 4,
        "calculus_1": 4,
        "probability_statistics": 4,
    }
    assert family_coverage["family_count"] == 17
    assert family_coverage["matched_atom_count"] == 48
    assert family_coverage["unmatched_atom_count"] == 0
    assert family_coverage["ambiguous_atom_count"] == 0
    assert family_coverage["overloaded_families"] == []
    assert payload["unsupported_atoms"] == []

    matched_families = {
        row["family_id"]
        for row in family_coverage["by_family"]
        if row["matched_atom_count"] > 0
    }
    assert len(matched_families) == 12
    assert matched_families == {
        "algebra_arithmetic_sequence_rationalized_sum_mcq",
        "algebra_continuity_branch_selection_mcq",
        "algebra_geometric_sequence_ratio_lock_mcq",
        "algebra_trigonometric_parameter_maximum_mcq",
        "calculus_integral_extremum_parameter_mcq",
        "calculus_integral_zero_balance_mcq",
        "calculus_piecewise_linear_replacement_area_max_mcq",
        "calculus_relative_motion_distance_monotonicity_mcq",
        "probability_normal_interval_probability_optimization_short",
        "probability_occupancy_adjacency_count_short",
        "probability_sample_mean_variance_scaling_mcq",
        "probability_sequential_transfer_conditional_probability_mcq",
    }

    atom_to_family = {
        row["atom_id"]: row["family_id"] for row in family_coverage["atom_mappings"]
    }
    assert atom_to_family["atom-3f37cf4df82a"] == "algebra_trigonometric_parameter_maximum_mcq"
    assert atom_to_family["atom-aeed409368c6"] == "calculus_integral_extremum_parameter_mcq"
    assert atom_to_family["atom-44753ee430ea"] == "probability_occupancy_adjacency_count_short"
