"""Central registry for validator reason codes."""

from __future__ import annotations

from dataclasses import dataclass

from src.core.schemas import FailureLevel, ValidationSeverity


@dataclass(frozen=True)
class ReasonCodeSpec:
    """Metadata attached to one canonical validator reason code."""

    code: str
    default_failure_level: FailureLevel
    default_severity: ValidationSeverity
    description: str


VALIDATOR_NO_FINDINGS = ReasonCodeSpec(
    code="validator.no_findings",
    default_failure_level=FailureLevel.SOFT,
    default_severity=ValidationSeverity.INFO,
    description="No validator emitted any check result, so the suite inserted a placeholder finding.",
)

FORMAT_ITEM_NUMBER_RANGE = ReasonCodeSpec(
    code="format.item_number_range",
    default_failure_level=FailureLevel.HARD,
    default_severity=ValidationSeverity.ERROR,
    description="The blueprint item number falls outside the exam range.",
)
FORMAT_SCORE_INVALID = ReasonCodeSpec(
    code="format.score_invalid",
    default_failure_level=FailureLevel.HARD,
    default_severity=ValidationSeverity.ERROR,
    description="The item score is not permitted by the exam spec.",
)
FORMAT_CHOICE_COUNT_INVALID = ReasonCodeSpec(
    code="format.choice_count_invalid",
    default_failure_level=FailureLevel.HARD,
    default_severity=ValidationSeverity.ERROR,
    description="A multiple-choice item does not have exactly five choices.",
)
FORMAT_MCQ_ANSWER_KEY_NOT_INTEGER = ReasonCodeSpec(
    code="format.mcq_answer_key_not_integer",
    default_failure_level=FailureLevel.HARD,
    default_severity=ValidationSeverity.ERROR,
    description="A multiple-choice answer key is stored as something other than an integer 1..5.",
)
FORMAT_SHORT_ANSWER_NOT_NATURAL = ReasonCodeSpec(
    code="format.short_answer_not_natural",
    default_failure_level=FailureLevel.HARD,
    default_severity=ValidationSeverity.ERROR,
    description="A short-answer final answer does not use the required positive-integer format.",
)
FORMAT_SHORT_ANSWER_CHOICES_PRESENT = ReasonCodeSpec(
    code="format.short_answer_choices_present",
    default_failure_level=FailureLevel.HARD,
    default_severity=ValidationSeverity.ERROR,
    description="A short-answer item still contains multiple-choice options.",
)
FORMAT_INTERNAL_METADATA_LEAK = ReasonCodeSpec(
    code="format.internal_metadata_leak",
    default_failure_level=FailureLevel.HARD,
    default_severity=ValidationSeverity.ERROR,
    description="Student-visible text leaks internal pipeline metadata or source identifiers.",
)
FORMAT_DISTRACTOR_TOO_OBVIOUS = ReasonCodeSpec(
    code="format.distractor_too_obvious",
    default_failure_level=FailureLevel.SOFT,
    default_severity=ValidationSeverity.WARNING,
    description="One or more distractors are so obvious that the item no longer discriminates meaningfully.",
)

CURRICULUM_DOMAIN_FORBIDDEN = ReasonCodeSpec(
    code="curriculum.domain_forbidden",
    default_failure_level=FailureLevel.HARD,
    default_severity=ValidationSeverity.ERROR,
    description="The blueprint domain is not one of the allowed subject areas.",
)
CURRICULUM_FORBIDDEN_TOPIC_DETECTED = ReasonCodeSpec(
    code="curriculum.forbidden_topic_detected",
    default_failure_level=FailureLevel.HARD,
    default_severity=ValidationSeverity.ERROR,
    description="The item text mentions forbidden out-of-scope topics.",
)
CURRICULUM_ALLOWED_TOPIC_MISS = ReasonCodeSpec(
    code="curriculum.allowed_topic_miss",
    default_failure_level=FailureLevel.SOFT,
    default_severity=ValidationSeverity.WARNING,
    description="The item does not map cleanly to known allowed curriculum topics.",
)
CURRICULUM_OUT_OF_CURRICULUM = ReasonCodeSpec(
    code="curriculum.out_of_curriculum",
    default_failure_level=FailureLevel.HARD,
    default_severity=ValidationSeverity.ERROR,
    description="The item is outside the permitted curriculum envelope and should be discarded.",
)

ANSWER_CHOICE_INDEX_MISMATCH = ReasonCodeSpec(
    code="answer.choice_index_mismatch",
    default_failure_level=FailureLevel.HARD,
    default_severity=ValidationSeverity.ERROR,
    description="The multiple-choice answer index/value pair does not align with the declared answer key.",
)
ANSWER_MULTIPLE_CORRECT_CANDIDATES = ReasonCodeSpec(
    code="answer.multiple_correct_candidates",
    default_failure_level=FailureLevel.HARD,
    default_severity=ValidationSeverity.ERROR,
    description="The item wording or duplicated correct-value choices make more than one answer viable.",
)
ANSWER_REFERENCE_MISMATCH = ReasonCodeSpec(
    code="answer.reference_mismatch",
    default_failure_level=FailureLevel.HARD,
    default_severity=ValidationSeverity.ERROR,
    description="The produced answer does not match the supplied reference answer.",
)
ANSWER_REFERENCE_NOT_AVAILABLE = ReasonCodeSpec(
    code="answer.reference_not_available",
    default_failure_level=FailureLevel.SOFT,
    default_severity=ValidationSeverity.INFO,
    description="No external reference answer was available for direct answer verification.",
)
ANSWER_CROSS_CHECK_DISAGREEMENT = ReasonCodeSpec(
    code="answer.cross_check_disagreement",
    default_failure_level=FailureLevel.SOFT,
    default_severity=ValidationSeverity.WARNING,
    description="An independent solver disagrees with the candidate answer.",
)

SIMILARITY_SURFACE_TOO_HIGH = ReasonCodeSpec(
    code="similarity.surface_too_high",
    default_failure_level=FailureLevel.SOFT,
    default_severity=ValidationSeverity.WARNING,
    description="The item stem is too close to an existing distilled item.",
)
SIMILARITY_EXPRESSION_TOO_HIGH = ReasonCodeSpec(
    code="similarity.expression_too_high",
    default_failure_level=FailureLevel.SOFT,
    default_severity=ValidationSeverity.WARNING,
    description="The normalized expression signature is too close to an existing item.",
)
SIMILARITY_SOLUTION_GRAPH_TOO_HIGH = ReasonCodeSpec(
    code="similarity.solution_graph_too_high",
    default_failure_level=FailureLevel.SOFT,
    default_severity=ValidationSeverity.WARNING,
    description="The solution-graph signature is too close to an existing item.",
)

RENDER_UNBALANCED_INLINE_MATH = ReasonCodeSpec(
    code="render.unbalanced_inline_math",
    default_failure_level=FailureLevel.HARD,
    default_severity=ValidationSeverity.ERROR,
    description="The item contains broken inline math delimiters.",
)
RENDER_UNBALANCED_BRACES = ReasonCodeSpec(
    code="render.unbalanced_braces",
    default_failure_level=FailureLevel.HARD,
    default_severity=ValidationSeverity.ERROR,
    description="The item contains broken brace structure in math or LaTeX text.",
)
RENDER_MISSING_DIAGRAM_ASSET = ReasonCodeSpec(
    code="render.missing_diagram_asset",
    default_failure_level=FailureLevel.HARD,
    default_severity=ValidationSeverity.ERROR,
    description="A referenced diagram asset is missing.",
)
RENDER_INVALID_DIAGRAM_ASSET = ReasonCodeSpec(
    code="render.invalid_diagram_asset",
    default_failure_level=FailureLevel.HARD,
    default_severity=ValidationSeverity.ERROR,
    description="A referenced diagram asset exists but is empty or malformed.",
)
RENDER_DIAGRAM_IRRELEVANT_TO_STEM = ReasonCodeSpec(
    code="render.diagram_irrelevant_to_stem",
    default_failure_level=FailureLevel.HARD,
    default_severity=ValidationSeverity.ERROR,
    description="The attached diagram appears unrelated to the item stem or objective.",
)
RENDER_LATEX_COMPILE_FAILED = ReasonCodeSpec(
    code="render.latex_compile_failed",
    default_failure_level=FailureLevel.HARD,
    default_severity=ValidationSeverity.ERROR,
    description="The item failed a LaTeX compile dry-run.",
)
RENDER_LATEX_COMPILE_OK = ReasonCodeSpec(
    code="render.latex_compile_ok",
    default_failure_level=FailureLevel.SOFT,
    default_severity=ValidationSeverity.INFO,
    description="The item passed the LaTeX compile dry-run.",
)

DIFFICULTY_BAND_MISMATCH = ReasonCodeSpec(
    code="difficulty.band_mismatch",
    default_failure_level=FailureLevel.SOFT,
    default_severity=ValidationSeverity.WARNING,
    description="The proxy difficulty band is far from the blueprint target band.",
)
DIFFICULTY_VARIANCE_TOO_FLAT = ReasonCodeSpec(
    code="difficulty.variance_too_flat",
    default_failure_level=FailureLevel.HARD,
    default_severity=ValidationSeverity.ERROR,
    description="A set of difficulty estimates is unnaturally flat and likely under-differentiated.",
)


ALL_REASON_CODE_SPECS = [
    VALIDATOR_NO_FINDINGS,
    FORMAT_ITEM_NUMBER_RANGE,
    FORMAT_SCORE_INVALID,
    FORMAT_CHOICE_COUNT_INVALID,
    FORMAT_MCQ_ANSWER_KEY_NOT_INTEGER,
    FORMAT_SHORT_ANSWER_NOT_NATURAL,
    FORMAT_SHORT_ANSWER_CHOICES_PRESENT,
    FORMAT_INTERNAL_METADATA_LEAK,
    FORMAT_DISTRACTOR_TOO_OBVIOUS,
    CURRICULUM_DOMAIN_FORBIDDEN,
    CURRICULUM_FORBIDDEN_TOPIC_DETECTED,
    CURRICULUM_ALLOWED_TOPIC_MISS,
    CURRICULUM_OUT_OF_CURRICULUM,
    ANSWER_CHOICE_INDEX_MISMATCH,
    ANSWER_MULTIPLE_CORRECT_CANDIDATES,
    ANSWER_REFERENCE_MISMATCH,
    ANSWER_REFERENCE_NOT_AVAILABLE,
    ANSWER_CROSS_CHECK_DISAGREEMENT,
    SIMILARITY_SURFACE_TOO_HIGH,
    SIMILARITY_EXPRESSION_TOO_HIGH,
    SIMILARITY_SOLUTION_GRAPH_TOO_HIGH,
    RENDER_UNBALANCED_INLINE_MATH,
    RENDER_UNBALANCED_BRACES,
    RENDER_MISSING_DIAGRAM_ASSET,
    RENDER_INVALID_DIAGRAM_ASSET,
    RENDER_DIAGRAM_IRRELEVANT_TO_STEM,
    RENDER_LATEX_COMPILE_FAILED,
    RENDER_LATEX_COMPILE_OK,
    DIFFICULTY_BAND_MISMATCH,
    DIFFICULTY_VARIANCE_TOO_FLAT,
]

REASON_CODE_REGISTRY = {spec.code: spec for spec in ALL_REASON_CODE_SPECS}


def get_reason_code(code: str) -> ReasonCodeSpec:
    """Return the canonical spec for a reason code."""

    try:
        return REASON_CODE_REGISTRY[code]
    except KeyError as exc:  # pragma: no cover - defensive guard
        raise KeyError(f"Unknown validator reason code: {code}") from exc
