"""Difficulty proxy estimator and associated validator."""

from __future__ import annotations

from statistics import pvariance

from src.core.schemas import (
    CritiqueReport,
    DifficultyBand,
    SolvedItem,
    ValidationFinding,
    ValidationSeverity,
)
from src.validators import reason_codes as rc
from src.validators.report import DifficultyEstimate, ValidatorSectionResult


DIFFICULTY_ORDER = {
    DifficultyBand.BASIC.value: 0,
    DifficultyBand.STANDARD.value: 1,
    DifficultyBand.CHALLENGING.value: 2,
    DifficultyBand.ADVANCED.value: 3,
}
ORDER_TO_BAND = {value: key for key, value in DIFFICULTY_ORDER.items()}


def estimate_difficulty(
    *,
    solved_item: SolvedItem,
    critique_report: CritiqueReport,
    cross_check_answer: str | None,
) -> DifficultyEstimate:
    """Estimate difficulty using proxy metrics instead of model confidence."""
    expected_step_count = len(solved_item.solution_steps)
    concept_count = len(
        set(solved_item.draft.blueprint.skill_tags + solved_item.draft.answer_constraints)
    ) or 1
    branch_tokens = sum(
        step.count("또는") + step.count("or") + step.count("경우") for step in solved_item.solution_steps
    )
    branching_factor = round(
        max(1.0, branch_tokens / max(expected_step_count, 1) + len(solved_item.draft.choices) / 5.0),
        2,
    )
    solver_disagreement_score = (
        0.0
        if cross_check_answer is None or cross_check_answer == solved_item.final_answer
        else 1.0
    )
    critique_penalty = 0.5 if critique_report.requires_revision else 0.0
    raw_score = expected_step_count * 0.8 + concept_count * 0.7 + branching_factor + solver_disagreement_score + critique_penalty
    if raw_score < 4:
        predicted_band = DifficultyBand.BASIC.value
    elif raw_score < 5.5:
        predicted_band = DifficultyBand.STANDARD.value
    elif raw_score < 7:
        predicted_band = DifficultyBand.CHALLENGING.value
    else:
        predicted_band = DifficultyBand.ADVANCED.value

    return DifficultyEstimate(
        expected_step_count=expected_step_count,
        concept_count=concept_count,
        branching_factor=branching_factor,
        solver_disagreement_score=solver_disagreement_score,
        predicted_band=predicted_band,
    )


def validate_difficulty_proxy(
    *,
    solved_item: SolvedItem,
    difficulty_estimate: DifficultyEstimate,
) -> ValidatorSectionResult:
    """Validate whether the proxy difficulty is broadly aligned with the blueprint."""
    blueprint_band = solved_item.draft.blueprint.difficulty.value
    delta = abs(
        DIFFICULTY_ORDER[difficulty_estimate.predicted_band] - DIFFICULTY_ORDER[blueprint_band]
    )
    return ValidatorSectionResult(
        validator_name="difficulty_estimator",
        findings=[
            ValidationFinding(
                check_name="difficulty_band_alignment",
                validator_name="difficulty_estimator",
                passed=delta <= 2,
                severity=(
                    rc.DIFFICULTY_BAND_MISMATCH.default_severity
                    if delta > 2
                    else ValidationSeverity.INFO
                ),
                message="proxy difficulty remains close to the blueprint difficulty band",
                reason_code=rc.DIFFICULTY_BAND_MISMATCH.code,
                failure_level=rc.DIFFICULTY_BAND_MISMATCH.default_failure_level,
                recommendation="Revise the reasoning depth or discard the item if the proxy difficulty is far from the target."
                if delta > 2
                else None,
                context={
                    "target_band": blueprint_band,
                    "predicted_band": difficulty_estimate.predicted_band,
                    "delta": delta,
                },
            )
        ],
        metrics=difficulty_estimate.model_dump(mode="json"),
    )


def validate_difficulty_variance(
    *,
    estimates: list[DifficultyEstimate],
) -> ValidatorSectionResult:
    """Reject sets whose difficulty estimates are implausibly flat."""

    if not estimates:
        raise ValueError("estimates must not be empty")

    band_values = [DIFFICULTY_ORDER[estimate.predicted_band] for estimate in estimates]
    step_counts = [estimate.expected_step_count for estimate in estimates]
    branching_factors = [estimate.branching_factor for estimate in estimates]
    disagreement_scores = [estimate.solver_disagreement_score for estimate in estimates]

    band_variance = pvariance(band_values) if len(band_values) > 1 else 0.0
    step_variance = pvariance(step_counts) if len(step_counts) > 1 else 0.0
    branching_variance = pvariance(branching_factors) if len(branching_factors) > 1 else 0.0
    disagreement_variance = pvariance(disagreement_scores) if len(disagreement_scores) > 1 else 0.0

    too_flat = (
        len(estimates) >= 4
        and band_variance <= 0.05
        and step_variance <= 0.25
        and branching_variance <= 0.02
        and disagreement_variance <= 0.02
    )

    return ValidatorSectionResult(
        validator_name="difficulty_estimator",
        findings=[
            ValidationFinding(
                check_name="difficulty_estimate_variance",
                validator_name="difficulty_estimator",
                passed=not too_flat,
                severity=rc.DIFFICULTY_VARIANCE_TOO_FLAT.default_severity,
                message="difficulty estimates vary enough across the set to support exam spread",
                reason_code=rc.DIFFICULTY_VARIANCE_TOO_FLAT.code,
                failure_level=rc.DIFFICULTY_VARIANCE_TOO_FLAT.default_failure_level,
                recommendation="Regenerate the set with wider variation in step count, branching, and target difficulty."
                if too_flat
                else None,
                context={
                    "band_variance": round(band_variance, 4),
                    "step_variance": round(step_variance, 4),
                    "branching_variance": round(branching_variance, 4),
                    "disagreement_variance": round(disagreement_variance, 4),
                    "unique_predicted_bands": sorted({estimate.predicted_band for estimate in estimates}),
                },
            )
        ],
        metrics={
            "estimate_count": len(estimates),
            "band_variance": round(band_variance, 4),
            "step_variance": round(step_variance, 4),
            "branching_variance": round(branching_variance, 4),
            "disagreement_variance": round(disagreement_variance, 4),
        },
    )
