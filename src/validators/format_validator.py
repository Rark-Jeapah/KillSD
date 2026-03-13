"""Format validator for generated CSAT items."""

from __future__ import annotations

import re
from collections import Counter
from math import gcd

from src.core.schemas import (
    ExamSpec,
    SolvedItem,
    ValidationFinding,
)
from src.validators import reason_codes as rc
from src.validators.report import ValidatorSectionResult


NATURAL_PATTERN = re.compile(r"^[1-9]\d*$")
REDUCED_FRACTION_PATTERN = re.compile(r"^[1-9]\d*/[1-9]\d*$")
MCQ_ANSWER_KEY_PATTERN = re.compile(r"^[1-5]$")
NON_ALNUM_PATTERN = re.compile(r"[^0-9a-z]+")
INTERNAL_METADATA_PATTERNS = (
    "atom-",
    "fixture-",
    "source_item_id",
    "skill_tags",
    "trigger_patterns",
    "canonical_moves",
    "common_failures",
    "answer_constraints",
    "promptpacket",
    "response_json_schema",
    "artifact_id",
    "spec_id",
    "blueprint_id",
    "validator_suite",
)
PLACEHOLDER_PATTERNS = (
    "placeholder",
    "모의 문항",
    "평가하는 문항",
    "sample item",
    "dummy item",
)
OBVIOUS_DISTRACTOR_PATTERNS = (
    "none of the above",
    "all of the above",
    "정답 없음",
    "모두 정답",
    "계산 안 해도",
    "계산 필요 없음",
    "찍기",
    "모르겠다",
)


def _normalize_choice_text(value: str) -> str:
    return NON_ALNUM_PATTERN.sub("", value.strip().lower())


def _is_reduced_fraction(value: str) -> bool:
    if not REDUCED_FRACTION_PATTERN.match(value.strip()):
        return False
    numerator, denominator = (int(part) for part in value.strip().split("/", maxsplit=1))
    return gcd(numerator, denominator) == 1


def _short_answer_format_ok(solved_item: SolvedItem) -> tuple[bool, str]:
    answer_type = solved_item.draft.blueprint.answer_type
    answer = solved_item.final_answer.strip()
    if answer_type == "reduced_fraction":
        return _is_reduced_fraction(answer), "short-answer final answer uses reduced-fraction format"
    return bool(NATURAL_PATTERN.match(answer)), "short-answer final answer uses natural-number format"


def _short_answer_recommendation(solved_item: SolvedItem) -> str:
    if solved_item.draft.blueprint.answer_type == "reduced_fraction":
        return "Regenerate the short-answer item so the final answer is a positive reduced fraction."
    return "Regenerate the short-answer item so the final answer is a positive integer."


def _student_visible_text(solved_item: SolvedItem) -> str:
    return "\n".join([solved_item.draft.stem, *solved_item.draft.choices]).lower()


def _find_matching_patterns(*, text: str, patterns: tuple[str, ...]) -> list[str]:
    return [pattern for pattern in patterns if pattern in text]


def _find_internal_metadata_hits(solved_item: SolvedItem) -> list[str]:
    return _find_matching_patterns(
        text=_student_visible_text(solved_item),
        patterns=INTERNAL_METADATA_PATTERNS,
    )


def _find_placeholder_hits(solved_item: SolvedItem) -> list[str]:
    return _find_matching_patterns(
        text=_student_visible_text(solved_item),
        patterns=PLACEHOLDER_PATTERNS,
    )


def _find_obvious_distractor_hits(solved_item: SolvedItem) -> list[dict[str, str | int]]:
    if solved_item.draft.blueprint.format.value != "multiple_choice":
        return []

    correct_index = solved_item.correct_choice_index
    obvious_hits: list[dict[str, str | int]] = []
    for index, choice in enumerate(solved_item.draft.choices, start=1):
        if correct_index is not None and index == correct_index:
            continue
        normalized = choice.strip().lower()
        matched_patterns = [pattern for pattern in OBVIOUS_DISTRACTOR_PATTERNS if pattern in normalized]
        if matched_patterns:
            obvious_hits.append(
                {
                    "choice_index": index,
                    "choice_text": choice,
                    "matched_patterns": ", ".join(matched_patterns),
                }
            )
    return obvious_hits


def _find_duplicate_choice_values(solved_item: SolvedItem) -> list[str]:
    normalized_choices = [_normalize_choice_text(choice) for choice in solved_item.draft.choices]
    counts = Counter(choice for choice in normalized_choices if choice)
    return sorted(choice for choice, count in counts.items() if count > 1)


def validate_format(*, solved_item: SolvedItem, spec: ExamSpec) -> ValidatorSectionResult:
    """Validate item format constraints and basic answer shape."""
    blueprint = solved_item.draft.blueprint
    findings: list[ValidationFinding] = []
    metadata_hits = _find_internal_metadata_hits(solved_item=solved_item)
    placeholder_hits = _find_placeholder_hits(solved_item=solved_item)
    obvious_distractor_hits = _find_obvious_distractor_hits(solved_item=solved_item)
    duplicate_choice_values = _find_duplicate_choice_values(solved_item=solved_item)

    findings.append(
        ValidationFinding(
            check_name="item_number_range",
            validator_name="format_validator",
            passed=1 <= blueprint.item_no <= spec.total_items,
            severity=rc.FORMAT_ITEM_NUMBER_RANGE.default_severity,
            message=f"item_no={blueprint.item_no} is within 1..{spec.total_items}",
            reason_code=rc.FORMAT_ITEM_NUMBER_RANGE.code,
            failure_level=rc.FORMAT_ITEM_NUMBER_RANGE.default_failure_level,
            recommendation="Fix the blueprint item number." if not (1 <= blueprint.item_no <= spec.total_items) else None,
        )
    )
    findings.append(
        ValidationFinding(
            check_name="score_allowed",
            validator_name="format_validator",
            passed=blueprint.score in spec.scoring_distribution,
            severity=rc.FORMAT_SCORE_INVALID.default_severity,
            message="score is permitted by the exam spec",
            reason_code=rc.FORMAT_SCORE_INVALID.code,
            failure_level=rc.FORMAT_SCORE_INVALID.default_failure_level,
            recommendation="Use one of the allowed score buckets from the exam spec."
            if blueprint.score not in spec.scoring_distribution
            else None,
        )
    )
    findings.append(
        ValidationFinding(
            check_name="student_visible_text_has_no_internal_metadata",
            validator_name="format_validator",
            passed=not metadata_hits,
            severity=rc.FORMAT_INTERNAL_METADATA_LEAK.default_severity,
            message="student-visible text does not leak source ids, prompt schema tokens, or internal metadata",
            reason_code=rc.FORMAT_INTERNAL_METADATA_LEAK.code,
            failure_level=rc.FORMAT_INTERNAL_METADATA_LEAK.default_failure_level,
            recommendation="Delete leaked artifact ids, source ids, schema tokens, and other internal metadata from the item."
            if metadata_hits
            else None,
            context={"matched_tokens": metadata_hits},
        )
    )
    findings.append(
        ValidationFinding(
            check_name="student_visible_text_has_no_placeholder_wording",
            validator_name="format_validator",
            passed=not placeholder_hits,
            severity=rc.FORMAT_PLACEHOLDER_WORDING.default_severity,
            message="student-visible text does not contain placeholder boilerplate or mock scaffolding",
            reason_code=rc.FORMAT_PLACEHOLDER_WORDING.code,
            failure_level=rc.FORMAT_PLACEHOLDER_WORDING.default_failure_level,
            recommendation="Rewrite the stem and choices with concrete mathematical conditions and remove placeholder-style wording."
            if placeholder_hits
            else None,
            context={"matched_tokens": placeholder_hits},
        )
    )

    if blueprint.format.value == "multiple_choice":
        findings.append(
            ValidationFinding(
                check_name="choice_count",
                validator_name="format_validator",
                passed=len(solved_item.draft.choices) == 5,
                severity=rc.FORMAT_CHOICE_COUNT_INVALID.default_severity,
                message="multiple-choice item contains exactly 5 options",
                reason_code=rc.FORMAT_CHOICE_COUNT_INVALID.code,
                failure_level=rc.FORMAT_CHOICE_COUNT_INVALID.default_failure_level,
                recommendation="Regenerate the draft with exactly five answer choices."
                if len(solved_item.draft.choices) != 5
                else None,
            )
        )
        findings.append(
            ValidationFinding(
                check_name="mcq_answer_key_integer",
                validator_name="format_validator",
                passed=bool(MCQ_ANSWER_KEY_PATTERN.match(solved_item.final_answer.strip())),
                severity=rc.FORMAT_MCQ_ANSWER_KEY_NOT_INTEGER.default_severity,
                message="MCQ answer key must be integer 1..5",
                reason_code=rc.FORMAT_MCQ_ANSWER_KEY_NOT_INTEGER.code,
                failure_level=rc.FORMAT_MCQ_ANSWER_KEY_NOT_INTEGER.default_failure_level,
                recommendation="Store the answer key as a choice index from 1 to 5."
                if not MCQ_ANSWER_KEY_PATTERN.match(solved_item.final_answer.strip())
                else None,
            )
        )
        findings.append(
            ValidationFinding(
                check_name="distractors_are_non_obvious",
                validator_name="format_validator",
                passed=not obvious_distractor_hits,
                severity=rc.FORMAT_DISTRACTOR_TOO_OBVIOUS.default_severity,
                message="distractors require actual mathematical discrimination instead of giveaway wording",
                reason_code=rc.FORMAT_DISTRACTOR_TOO_OBVIOUS.code,
                failure_level=rc.FORMAT_DISTRACTOR_TOO_OBVIOUS.default_failure_level,
                recommendation="Rewrite or replace giveaway distractors so every wrong choice is mathematically plausible."
                if obvious_distractor_hits
                else None,
                context={
                    "obvious_distractors": obvious_distractor_hits,
                    "duplicate_choice_values": duplicate_choice_values,
                },
            )
        )
    else:
        short_answer_passed, short_answer_message = _short_answer_format_ok(solved_item)
        findings.append(
            ValidationFinding(
                check_name="short_answer_natural",
                validator_name="format_validator",
                passed=short_answer_passed,
                severity=rc.FORMAT_SHORT_ANSWER_NOT_NATURAL.default_severity,
                message=short_answer_message,
                reason_code=rc.FORMAT_SHORT_ANSWER_NOT_NATURAL.code,
                failure_level=rc.FORMAT_SHORT_ANSWER_NOT_NATURAL.default_failure_level,
                recommendation=_short_answer_recommendation(solved_item) if not short_answer_passed else None,
            )
        )
        findings.append(
            ValidationFinding(
                check_name="short_answer_no_choices",
                validator_name="format_validator",
                passed=not solved_item.draft.choices,
                severity=rc.FORMAT_SHORT_ANSWER_CHOICES_PRESENT.default_severity,
                message="short-answer item does not include multiple-choice options",
                reason_code=rc.FORMAT_SHORT_ANSWER_CHOICES_PRESENT.code,
                failure_level=rc.FORMAT_SHORT_ANSWER_CHOICES_PRESENT.default_failure_level,
                recommendation="Remove multiple-choice options from the short-answer item."
                if solved_item.draft.choices
                else None,
            )
        )

    return ValidatorSectionResult(
        validator_name="format_validator",
        findings=findings,
        metrics={
            "item_no": blueprint.item_no,
            "score": blueprint.score,
            "choice_count": len(solved_item.draft.choices),
        },
    )
