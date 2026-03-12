"""Answer validator with symbolic, numeric, and cross-check verification."""

from __future__ import annotations

import re
from typing import Any

from src.core.schemas import (
    SolvedItem,
    ValidationFinding,
)
from src.validators import reason_codes as rc
from src.validators.report import ValidatorSectionResult

try:
    import sympy as sp
except Exception:  # pragma: no cover - dependency fallback
    sp = None

WHITESPACE_PATTERN = re.compile(r"\s+")
MULTI_ANSWER_CUES = (
    "모두",
    "둘 이상",
    "복수",
    "해당하는 것을 모두",
    "select all",
    "choose all",
)


def _to_sympy(expr: str) -> Any | None:
    if sp is None:
        return None
    try:
        return sp.sympify(expr.replace("^", "**"))
    except Exception:
        return None


def _symbolically_equal(left: str, right: str) -> bool | None:
    left_expr = _to_sympy(left)
    right_expr = _to_sympy(right)
    if left_expr is None or right_expr is None:
        return None
    try:
        return bool(sp.simplify(left_expr - right_expr) == 0)
    except Exception:
        return None


def _numerically_equal(left: str, right: str, tolerance: float = 1e-9) -> bool | None:
    left_expr = _to_sympy(left)
    right_expr = _to_sympy(right)
    if left_expr is None or right_expr is None:
        return None
    try:
        return abs(float(left_expr.evalf()) - float(right_expr.evalf())) <= tolerance
    except Exception:
        return None


def _normalize_choice_text(value: str) -> str:
    return WHITESPACE_PATTERN.sub("", value.strip().lower())


def _multiple_correct_candidate_context(solved_item: SolvedItem) -> dict[str, Any]:
    if solved_item.draft.blueprint.format.value != "multiple_choice":
        return {"ambiguous_correct_choice_indices": [], "matched_cues": []}

    normalized_correct_value = _normalize_choice_text(solved_item.correct_choice_value or "")
    ambiguous_indices = [
        index
        for index, choice in enumerate(solved_item.draft.choices, start=1)
        if normalized_correct_value and _normalize_choice_text(choice) == normalized_correct_value
    ]
    stem_text = solved_item.draft.stem.lower()
    matched_cues = [cue for cue in MULTI_ANSWER_CUES if cue in stem_text]
    return {
        "ambiguous_correct_choice_indices": ambiguous_indices,
        "matched_cues": matched_cues,
    }


def validate_answer(
    *,
    solved_item: SolvedItem,
    expected_answer: str | None,
    cross_check_answer: str | None,
) -> ValidatorSectionResult:
    """Validate answer shape and optional reference/cross-check consistency."""
    findings: list[ValidationFinding] = []
    ambiguity_context = _multiple_correct_candidate_context(solved_item=solved_item)

    if solved_item.draft.blueprint.format.value == "multiple_choice":
        choice_index = solved_item.correct_choice_index
        expected_choice = (
            solved_item.draft.choices[choice_index - 1]
            if choice_index is not None and 1 <= choice_index <= len(solved_item.draft.choices)
            else None
        )
        findings.append(
            ValidationFinding(
                check_name="final_answer_matches_choice_index",
                validator_name="answer_validator",
                passed=(
                    choice_index is not None
                    and solved_item.final_answer == str(choice_index)
                    and solved_item.correct_choice_value == expected_choice
                ),
                severity=rc.ANSWER_CHOICE_INDEX_MISMATCH.default_severity,
                message="multiple-choice answer key uses an index and matches the indexed choice text",
                reason_code=rc.ANSWER_CHOICE_INDEX_MISMATCH.code,
                failure_level=rc.ANSWER_CHOICE_INDEX_MISMATCH.default_failure_level,
                recommendation="Regenerate the draft or solution so the answer key uses a 1..5 index and stores the matching choice value."
                if not (
                    choice_index is not None
                    and solved_item.final_answer == str(choice_index)
                    and solved_item.correct_choice_value == expected_choice
                )
                else None,
            )
        )
        findings.append(
            ValidationFinding(
                check_name="single_correct_candidate",
                validator_name="answer_validator",
                passed=(
                    len(ambiguity_context["ambiguous_correct_choice_indices"]) <= 1
                    and not ambiguity_context["matched_cues"]
                ),
                severity=rc.ANSWER_MULTIPLE_CORRECT_CANDIDATES.default_severity,
                message="the item wording and choices admit exactly one correct answer",
                reason_code=rc.ANSWER_MULTIPLE_CORRECT_CANDIDATES.code,
                failure_level=rc.ANSWER_MULTIPLE_CORRECT_CANDIDATES.default_failure_level,
                recommendation="Collapse duplicated correct-value choices and remove multi-answer wording so exactly one choice is correct."
                if (
                    len(ambiguity_context["ambiguous_correct_choice_indices"]) > 1
                    or ambiguity_context["matched_cues"]
                )
                else None,
                context=ambiguity_context,
            )
        )

    if expected_answer is not None:
        symbolic_match = _symbolically_equal(solved_item.final_answer, expected_answer)
        numeric_match = _numerically_equal(solved_item.final_answer, expected_answer)
        passed = symbolic_match is True or numeric_match is True or solved_item.final_answer == expected_answer
        findings.append(
            ValidationFinding(
                check_name="reference_answer_match",
                validator_name="answer_validator",
                passed=passed,
                severity=rc.ANSWER_REFERENCE_MISMATCH.default_severity,
                message="candidate answer matches the supplied reference answer",
                reason_code=rc.ANSWER_REFERENCE_MISMATCH.code,
                failure_level=rc.ANSWER_REFERENCE_MISMATCH.default_failure_level,
                recommendation="Discard the item or rerun solving because the reference answer does not match."
                if not passed
                else None,
                context={
                    "expected_answer": expected_answer,
                    "symbolic_match": symbolic_match,
                    "numeric_match": numeric_match,
                },
            )
        )
    else:
        findings.append(
            ValidationFinding(
                check_name="reference_answer_available",
                validator_name="answer_validator",
                passed=True,
                severity=rc.ANSWER_REFERENCE_NOT_AVAILABLE.default_severity,
                message="No external reference answer was supplied; direct answer verification was skipped.",
                reason_code=rc.ANSWER_REFERENCE_NOT_AVAILABLE.code,
                failure_level=rc.ANSWER_REFERENCE_NOT_AVAILABLE.default_failure_level,
            )
        )

    if cross_check_answer is not None:
        symbolic_match = _symbolically_equal(solved_item.final_answer, cross_check_answer)
        numeric_match = _numerically_equal(solved_item.final_answer, cross_check_answer)
        passed = symbolic_match is True or numeric_match is True or solved_item.final_answer == cross_check_answer
        findings.append(
            ValidationFinding(
                check_name="solver_cross_check",
                validator_name="answer_validator",
                passed=passed,
                severity=rc.ANSWER_CROSS_CHECK_DISAGREEMENT.default_severity,
                message="candidate answer agrees with the independent cross-check answer",
                reason_code=rc.ANSWER_CROSS_CHECK_DISAGREEMENT.code,
                failure_level=rc.ANSWER_CROSS_CHECK_DISAGREEMENT.default_failure_level,
                recommendation="Route the item through another solve/revise cycle because solver outputs disagree."
                if not passed
                else None,
                context={
                    "cross_check_answer": cross_check_answer,
                    "symbolic_match": symbolic_match,
                    "numeric_match": numeric_match,
                },
            )
        )

    return ValidatorSectionResult(
        validator_name="answer_validator",
        findings=findings,
        metrics={"final_answer": solved_item.final_answer},
    )
