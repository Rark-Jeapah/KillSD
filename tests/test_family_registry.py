"""Tests for the modular real-item family registry."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.orchestrator.real_item_families import (
    BLUEPRINT_FAMILY_TAG_PREFIX,
    RealItemFamilySelectionError,
    build_real_item_family_registry,
)
from src.plugins import get_plugin


REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY = build_real_item_family_registry()
SPEC = get_plugin("csat_math_2028").load_exam_spec()


def test_family_registry_auto_discovers_modular_families() -> None:
    family_ids = REGISTRY.family_ids()

    assert len(family_ids) == 17
    assert len(set(family_ids)) == len(family_ids)
    assert "algebra_trigonometric_parameter_maximum_mcq" in family_ids
    assert "calculus_integral_extremum_parameter_mcq" in family_ids
    assert "probability_occupancy_adjacency_count_short" in family_ids


def test_family_registry_disambiguates_shared_probability_slot_via_blueprint_tag() -> None:
    process_family = REGISTRY.get("probability_sequential_transfer_conditional_probability_mcq")
    variance_family = REGISTRY.get("probability_sample_mean_variance_scaling_mcq")

    process_blueprint = process_family.blueprint_builder(SPEC, process_family.build_smoke_atom())
    variance_blueprint = variance_family.blueprint_builder(SPEC, variance_family.build_smoke_atom())

    assert process_blueprint.item_no == 21
    assert variance_blueprint.item_no == 21
    assert any(
        tag == f"{BLUEPRINT_FAMILY_TAG_PREFIX}{process_family.family_id}"
        for tag in process_blueprint.skill_tags
    )
    assert any(
        tag == f"{BLUEPRINT_FAMILY_TAG_PREFIX}{variance_family.family_id}"
        for tag in variance_blueprint.skill_tags
    )
    assert REGISTRY.resolve_for_blueprint(process_blueprint).family_id == process_family.family_id
    assert REGISTRY.resolve_for_blueprint(variance_blueprint).family_id == variance_family.family_id

    ambiguous_blueprint = process_blueprint.model_copy(
        update={
            "skill_tags": [
                tag
                for tag in process_blueprint.skill_tags
                if not tag.startswith(BLUEPRINT_FAMILY_TAG_PREFIX)
            ]
        }
    )
    with pytest.raises(RealItemFamilySelectionError, match="more than one real-item family"):
        REGISTRY.resolve_for_blueprint(ambiguous_blueprint)


@pytest.mark.parametrize("family_id", REGISTRY.family_ids())
def test_each_family_has_a_working_smoke_path(family_id: str) -> None:
    family = REGISTRY.get(family_id)
    atom = family.build_smoke_atom()

    selected = REGISTRY.select_for_atom(atom)
    assert selected.family_id == family.family_id

    blueprint = family.blueprint_builder(SPEC, atom)
    assert REGISTRY.resolve_for_blueprint(blueprint).family_id == family.family_id

    draft = family.draft_strategy(blueprint, atom)
    solved = family.solve_strategy(draft, atom)
    critique = family.critique_strategy(solved, atom)
    revised = family.revise_strategy(solved, critique, atom)

    assert revised.draft.blueprint.item_no == family.blueprint_item_no
    assert revised.solution_steps
    assert revised.solution_summary
    if blueprint.format.value == "multiple_choice":
        assert revised.correct_choice_index is not None
        assert revised.correct_choice_value is not None
    else:
        assert revised.correct_choice_index is None
        assert revised.correct_choice_value is None
