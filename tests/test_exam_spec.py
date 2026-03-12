"""Exam spec and plugin tests."""

from __future__ import annotations

from src.plugins.csat_math_2028 import CSATMath2028Plugin


def test_exam_spec_loads_with_required_constraints() -> None:
    plugin = CSATMath2028Plugin()
    spec = plugin.load_exam_spec()

    assert spec.spec_id == "csat_math_2028"
    assert spec.exam_year == 2028
    assert spec.duration_minutes == 100
    assert spec.total_items == 30
    assert spec.scoring_distribution == {2: 3, 3: 14, 4: 13}
    assert spec.elective_branches is False
    assert len(spec.format_rules["multiple_choice"].item_numbers) == 21
    assert len(spec.format_rules["short_answer"].item_numbers) == 9


def test_default_blueprint_matches_exam_shape() -> None:
    plugin = CSATMath2028Plugin()
    blueprint = plugin.build_default_blueprint()

    assert blueprint.spec_id == "csat_math_2028"
    assert len(blueprint.item_blueprints) == 30
    assert sum(item.score for item in blueprint.item_blueprints) == 100
    assert blueprint.item_blueprints[0].item_no == 1
    assert blueprint.item_blueprints[-1].item_no == 30
