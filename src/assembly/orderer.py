"""Ordering and assembly checks for final exam bundles."""

from __future__ import annotations

from collections import Counter
import re

from pydantic import Field

from src.core.schemas import ApprovalStatus, ExamBlueprint, StrictModel, ValidatedItem


class OrderingMetrics(StrictModel):
    """Assembly metrics derived from the ordered exam."""

    topic_coverage: dict[str, int]
    expected_topic_coverage: dict[str, int]
    difficulty_curve: list[str]
    expected_difficulty_curve: list[str]
    score_distribution: dict[int, int]
    expected_score_distribution: dict[int, int]
    repeated_skill_signatures: dict[str, int] = Field(default_factory=dict)
    repeated_objective_signatures: dict[str, int] = Field(default_factory=dict)


class OrderingError(Exception):
    """Raised when validated items cannot be assembled safely."""


def _skill_signature(item: ValidatedItem) -> str:
    blueprint = item.solved.draft.blueprint
    return "|".join(sorted(set(blueprint.skill_tags))) or blueprint.objective


def _objective_signature(item: ValidatedItem) -> str:
    """Normalize the high-level objective to a compact duplication signature."""
    objective = item.solved.draft.blueprint.objective.lower()
    tokens = [
        token
        for token in re.split(r"[^0-9a-zA-Z가-힣]+", objective)
        if token
    ]
    return " ".join(tokens[:4]) if tokens else objective


def order_validated_items(
    exam_blueprint: ExamBlueprint,
    validated_items: list[ValidatedItem],
    *,
    max_signature_reuse: int = 4,
    max_objective_reuse: int = 2,
) -> tuple[list[ValidatedItem], OrderingMetrics]:
    """Order validated items by item number and enforce assembly constraints."""
    ordered_items = sorted(validated_items, key=lambda item: item.solved.draft.blueprint.item_no)
    item_numbers = [item.solved.draft.blueprint.item_no for item in ordered_items]
    expected_numbers = list(range(1, len(exam_blueprint.item_blueprints) + 1))
    if item_numbers != expected_numbers:
        raise OrderingError("Validated items must cover item numbers 1..N exactly once")

    blueprint_by_no = {item.item_no: item for item in exam_blueprint.item_blueprints}
    expected_topic_coverage = Counter(item.domain for item in exam_blueprint.item_blueprints)
    expected_score_distribution = Counter(item.score for item in exam_blueprint.item_blueprints)
    expected_difficulty_curve = [item.difficulty.value for item in exam_blueprint.item_blueprints]
    topic_coverage: Counter[str] = Counter()
    score_distribution: Counter[int] = Counter()
    difficulty_curve: list[str] = []
    signature_counts: Counter[str] = Counter()
    objective_signature_counts: Counter[str] = Counter()

    for validated_item in ordered_items:
        if validated_item.approval_status != ApprovalStatus.APPROVED:
            raise OrderingError(
                f"Only approved items can be assembled: item {validated_item.solved.draft.blueprint.item_no}"
            )
        blueprint = validated_item.solved.draft.blueprint
        target = blueprint_by_no[blueprint.item_no]
        if blueprint.domain != target.domain:
            raise OrderingError(f"Domain mismatch for item {blueprint.item_no}")
        if blueprint.score != target.score:
            raise OrderingError(f"Score mismatch for item {blueprint.item_no}")
        if blueprint.format != target.format:
            raise OrderingError(f"Format mismatch for item {blueprint.item_no}")
        if blueprint.difficulty != target.difficulty:
            raise OrderingError(f"Difficulty mismatch for item {blueprint.item_no}")
        if set(blueprint.skill_tags) != set(target.skill_tags):
            raise OrderingError(f"Skill tag mismatch for item {blueprint.item_no}")

        topic_coverage[blueprint.domain] += 1
        score_distribution[blueprint.score] += 1
        difficulty_curve.append(blueprint.difficulty.value)
        signature_counts[_skill_signature(validated_item)] += 1
        objective_signature_counts[_objective_signature(validated_item)] += 1

    if topic_coverage != expected_topic_coverage:
        raise OrderingError("Topic coverage no longer matches the exam blueprint")
    if score_distribution != expected_score_distribution:
        raise OrderingError("Score distribution no longer matches the exam blueprint")
    if difficulty_curve != expected_difficulty_curve:
        raise OrderingError("Difficulty curve no longer matches the exam blueprint")

    excessive = {
        signature: count
        for signature, count in signature_counts.items()
        if count > max_signature_reuse
    }
    excessive_objectives = {
        signature: count
        for signature, count in objective_signature_counts.items()
        if count > max_objective_reuse
    }
    if excessive:
        raise OrderingError(
            f"Atom/skill over-reuse detected: {', '.join(f'{key}:{value}' for key, value in excessive.items())}"
        )
    if excessive_objectives:
        raise OrderingError(
            "Objective over-reuse detected: "
            + ", ".join(f"{key}:{value}" for key, value in excessive_objectives.items())
        )

    metrics = OrderingMetrics(
        topic_coverage=dict(topic_coverage),
        expected_topic_coverage=dict(expected_topic_coverage),
        difficulty_curve=difficulty_curve,
        expected_difficulty_curve=expected_difficulty_curve,
        score_distribution=dict(score_distribution),
        expected_score_distribution=dict(expected_score_distribution),
        repeated_skill_signatures={
            signature: count for signature, count in signature_counts.items() if count > 1
        },
        repeated_objective_signatures={
            signature: count for signature, count in objective_signature_counts.items() if count > 1
        },
    )
    return ordered_items, metrics
