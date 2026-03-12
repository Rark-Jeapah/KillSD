"""Core schemas for the CSAT mathematics pipeline MVP."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class StrictModel(BaseModel):
    """Base model with strict validation defaults for pipeline artifacts."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ExamMode(str, Enum):
    """Supported runtime modes."""

    MANUAL = "manual"
    API = "api"


class ItemFormat(str, Enum):
    """Supported item presentation formats."""

    MULTIPLE_CHOICE = "multiple_choice"
    SHORT_ANSWER = "short_answer"


class PipelineStage(str, Enum):
    """Stages in the item production pipeline."""

    DESIGN = "design"
    GENERATION = "generation"
    SOLVING = "solving"
    VALIDATION = "validation"
    REVISION = "revision"
    ASSEMBLY = "assembly"
    RENDER = "render"


class DifficultyBand(str, Enum):
    """Coarse difficulty buckets for MVP planning."""

    BASIC = "basic"
    STANDARD = "standard"
    CHALLENGING = "challenging"
    ADVANCED = "advanced"


class ValidationSeverity(str, Enum):
    """Severity for validation findings."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ValidationStatus(str, Enum):
    """Aggregate validation outcome."""

    PASS = "pass"
    NEEDS_REVISION = "needs_revision"
    FAIL = "fail"


class FailureLevel(str, Enum):
    """Failure strength for validation findings."""

    HARD = "hard"
    SOFT = "soft"


class RegenerateRecommendation(str, Enum):
    """Recommended next action after validation."""

    KEEP = "keep"
    REVISE = "revise"
    REGENERATE = "regenerate"


class ExchangeStatus(str, Enum):
    """Manual exchange lifecycle status."""

    PENDING = "pending"
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ApprovalStatus(str, Enum):
    """Validated item approval status."""

    APPROVED = "approved"
    NEEDS_REVISION = "needs_revision"
    REJECTED = "rejected"


class FormatRule(StrictModel):
    """Formatting rule for a contiguous or non-contiguous item set."""

    item_numbers: list[int]
    choice_count: int | None = None

    @model_validator(mode="after")
    def validate_item_numbers(self) -> "FormatRule":
        """Ensure item numbers are unique and positive."""
        numbers = self.item_numbers
        if not numbers:
            raise ValueError("item_numbers must not be empty")
        if any(number < 1 for number in numbers):
            raise ValueError("item_numbers must be positive")
        if len(numbers) != len(set(numbers)):
            raise ValueError("item_numbers must be unique")
        if self.choice_count is not None and self.choice_count < 2:
            raise ValueError("choice_count must be at least 2")
        return self


class ItemBlueprint(StrictModel):
    """Planning record for a single exam item before generation."""

    item_id: str = Field(default_factory=lambda: f"ibl-{uuid4().hex[:12]}")
    item_no: int
    domain: str
    format: ItemFormat
    score: int
    difficulty: DifficultyBand
    objective: str
    skill_tags: list[str] = Field(default_factory=list)
    choice_count: int | None = None
    answer_type: str = "symbolic_or_numeric"

    @model_validator(mode="after")
    def validate_blueprint(self) -> "ItemBlueprint":
        """Check item numbering and format-specific constraints."""
        if self.item_no < 1:
            raise ValueError("item_no must be positive")
        if self.score not in {2, 3, 4}:
            raise ValueError("score must be one of 2, 3, or 4")
        if self.format == ItemFormat.MULTIPLE_CHOICE and self.choice_count != 5:
            raise ValueError("multiple_choice items must declare choice_count=5")
        if self.format == ItemFormat.SHORT_ANSWER and self.choice_count is not None:
            raise ValueError("short_answer items must not declare choice_count")
        return self


class ExamSpec(StrictModel):
    """Immutable exam contract for one target assessment."""

    spec_id: str
    title: str
    exam_year: int
    subject: str
    duration_minutes: int
    total_items: int
    total_score: int
    elective_branches: bool
    subject_areas: list[str]
    supported_modes: list[ExamMode]
    scoring_distribution: dict[int, int]
    format_rules: dict[ItemFormat, FormatRule]
    pipeline_stages: list[PipelineStage]
    default_item_blueprints: list[ItemBlueprint]

    @model_validator(mode="after")
    def validate_exam_spec(self) -> "ExamSpec":
        """Enforce item counts, format layout, and score totals."""
        if self.exam_year != 2028:
            raise ValueError("This MVP is scoped to the 2028 exam year")
        if self.elective_branches:
            raise ValueError("2028 CSAT math MVP must not enable elective branches")
        if self.duration_minutes != 100:
            raise ValueError("duration_minutes must be 100")
        if self.total_items != 30:
            raise ValueError("total_items must be 30")
        if sorted(self.subject_areas) != ["algebra", "calculus_1", "probability_statistics"]:
            raise ValueError(
                "subject_areas must exactly match algebra, calculus_1, probability_statistics"
            )
        if set(self.supported_modes) != {ExamMode.MANUAL, ExamMode.API}:
            raise ValueError("supported_modes must include both manual and api")
        if sum(self.scoring_distribution.values()) != self.total_items:
            raise ValueError("scoring_distribution must sum to total_items")
        if self.scoring_distribution != {2: 3, 3: 14, 4: 13}:
            raise ValueError("scoring_distribution must be {2: 3, 3: 14, 4: 13}")
        if len(self.default_item_blueprints) != self.total_items:
            raise ValueError("default_item_blueprints length must equal total_items")

        item_numbers = [blueprint.item_no for blueprint in self.default_item_blueprints]
        if sorted(item_numbers) != list(range(1, self.total_items + 1)):
            raise ValueError("default_item_blueprints must cover items 1..30 exactly once")

        multiple_choice_numbers = set(
            self.format_rules[ItemFormat.MULTIPLE_CHOICE].item_numbers
        )
        short_answer_numbers = set(self.format_rules[ItemFormat.SHORT_ANSWER].item_numbers)
        all_numbers = multiple_choice_numbers | short_answer_numbers
        if all_numbers != set(range(1, self.total_items + 1)):
            raise ValueError("format_rules must cover all item numbers")
        if multiple_choice_numbers & short_answer_numbers:
            raise ValueError("format_rules item number sets must not overlap")

        blueprint_score_sum = sum(item.score for item in self.default_item_blueprints)
        if blueprint_score_sum != self.total_score:
            raise ValueError("Sum of blueprint scores must equal total_score")

        for item in self.default_item_blueprints:
            if item.item_no in multiple_choice_numbers and item.format != ItemFormat.MULTIPLE_CHOICE:
                raise ValueError("Multiple-choice slots must use multiple_choice format")
            if item.item_no in short_answer_numbers and item.format != ItemFormat.SHORT_ANSWER:
                raise ValueError("Short-answer slots must use short_answer format")

        return self


class ExamBlueprint(StrictModel):
    """Concrete exam plan ready for drafting/generation."""

    blueprint_id: str = Field(default_factory=lambda: f"bp-{uuid4().hex[:12]}")
    spec_id: str
    created_at: datetime = Field(default_factory=utc_now)
    generator: str = "default_blueprint_builder"
    notes: list[str] = Field(default_factory=list)
    item_blueprints: list[ItemBlueprint]

    @model_validator(mode="after")
    def validate_exam_blueprint(self) -> "ExamBlueprint":
        """Ensure blueprint item ordering is complete and unique."""
        item_numbers = [item.item_no for item in self.item_blueprints]
        if sorted(item_numbers) != list(range(1, len(self.item_blueprints) + 1)):
            raise ValueError("item_blueprints must be contiguous from 1..N")
        return self


class DraftItem(StrictModel):
    """Drafted item content before solving/validation."""

    draft_id: str = Field(default_factory=lambda: f"drf-{uuid4().hex[:12]}")
    blueprint: ItemBlueprint
    stem: str
    choices: list[str] = Field(default_factory=list)
    rubric: str
    answer_constraints: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_draft_item(self) -> "DraftItem":
        """Enforce format-specific content rules."""
        if self.blueprint.format == ItemFormat.MULTIPLE_CHOICE:
            if len(self.choices) != self.blueprint.choice_count:
                raise ValueError("choices must match the blueprint choice_count")
        elif self.choices:
            raise ValueError("short_answer items must not contain choices")
        return self


class SolvedItem(StrictModel):
    """Draft item enriched with a worked solution and answer."""

    solved_id: str = Field(default_factory=lambda: f"slv-{uuid4().hex[:12]}")
    draft: DraftItem
    final_answer: str
    correct_choice_index: int | None = None
    correct_choice_value: str | None = None
    solution_steps: list[str]
    solution_summary: str

    @model_validator(mode="after")
    def validate_solved_item(self) -> "SolvedItem":
        """Require at least one solution step."""
        if not self.solution_steps:
            raise ValueError("solution_steps must not be empty")
        if self.draft.blueprint.format == ItemFormat.MULTIPLE_CHOICE:
            if self.correct_choice_index is None:
                raise ValueError("multiple_choice items must declare correct_choice_index")
            if self.correct_choice_value is None:
                raise ValueError("multiple_choice items must declare correct_choice_value")
            if not 1 <= self.correct_choice_index <= len(self.draft.choices):
                raise ValueError("correct_choice_index must be within the declared choice range")
            if self.final_answer.strip() != str(self.correct_choice_index):
                raise ValueError("multiple_choice final_answer must equal correct_choice_index")
            expected_choice_value = self.draft.choices[self.correct_choice_index - 1]
            if self.correct_choice_value != expected_choice_value:
                raise ValueError("correct_choice_value must match the indexed choice text")
        elif self.correct_choice_index is not None or self.correct_choice_value is not None:
            raise ValueError("short_answer items must not declare correct_choice_index/value")
        return self


class CritiqueFinding(StrictModel):
    """Issue found during the critique stage before final validation."""

    issue_id: str = Field(default_factory=lambda: f"crf-{uuid4().hex[:12]}")
    severity: ValidationSeverity
    message: str
    recommendation: str
    blocking: bool = False


class CritiqueReport(StrictModel):
    """Critique output used to drive revision decisions."""

    critique_id: str = Field(default_factory=lambda: f"crt-{uuid4().hex[:12]}")
    item_no: int
    summary: str
    findings: list[CritiqueFinding] = Field(default_factory=list)
    requires_revision: bool = False
    reviewed_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_requires_revision(self) -> "CritiqueReport":
        """Keep the requires_revision flag aligned with findings."""
        should_require_revision = any(
            finding.blocking or finding.severity in {ValidationSeverity.WARNING, ValidationSeverity.ERROR}
            for finding in self.findings
        )
        if self.requires_revision != should_require_revision:
            raise ValueError(
                f"requires_revision must be {should_require_revision} for the supplied findings"
            )
        return self


class ValidationFinding(StrictModel):
    """Single validation check result."""

    check_name: str
    passed: bool
    severity: ValidationSeverity
    message: str
    reason_code: str = "unspecified"
    failure_level: FailureLevel = FailureLevel.SOFT
    validator_name: str = "unspecified"
    recommendation: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class ValidationReport(StrictModel):
    """Aggregate item validation output."""

    report_id: str = Field(default_factory=lambda: f"val-{uuid4().hex[:12]}")
    item_no: int
    status: ValidationStatus
    findings: list[ValidationFinding]
    summary: str
    reason_codes: list[str] = Field(default_factory=list)
    hard_fail: bool = False
    soft_fail: bool = False
    regenerate_recommendation: RegenerateRecommendation = RegenerateRecommendation.KEEP
    checked_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_status(self) -> "ValidationReport":
        """Ensure status is consistent with findings."""
        if not self.findings:
            raise ValueError("findings must not be empty")

        failed_findings = [finding for finding in self.findings if not finding.passed]
        object.__setattr__(
            self,
            "reason_codes",
            sorted({finding.reason_code for finding in failed_findings}),
        )
        object.__setattr__(
            self,
            "hard_fail",
            any(finding.failure_level == FailureLevel.HARD for finding in failed_findings),
        )
        object.__setattr__(
            self,
            "soft_fail",
            any(finding.failure_level == FailureLevel.SOFT for finding in failed_findings),
        )

        if not failed_findings:
            expected = ValidationStatus.PASS
            recommendation = RegenerateRecommendation.KEEP
        elif self.hard_fail or any(
            finding.severity == ValidationSeverity.ERROR for finding in failed_findings
        ):
            expected = ValidationStatus.FAIL
            recommendation = RegenerateRecommendation.REGENERATE
        else:
            expected = ValidationStatus.NEEDS_REVISION
            recommendation = RegenerateRecommendation.REVISE

        if self.status != expected:
            raise ValueError(f"status must be {expected.value} for the supplied findings")
        object.__setattr__(self, "regenerate_recommendation", recommendation)
        return self


class ValidatedItem(StrictModel):
    """Solved item paired with validation output and approval state."""

    validated_id: str = Field(default_factory=lambda: f"vld-{uuid4().hex[:12]}")
    solved: SolvedItem
    validation: ValidationReport
    approval_status: ApprovalStatus
    revision_notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_approval(self) -> "ValidatedItem":
        """Keep approval state aligned with validation status."""
        status_map = {
            ValidationStatus.PASS: ApprovalStatus.APPROVED,
            ValidationStatus.NEEDS_REVISION: ApprovalStatus.NEEDS_REVISION,
            ValidationStatus.FAIL: ApprovalStatus.REJECTED,
        }
        expected = status_map[self.validation.status]
        if self.approval_status != expected:
            raise ValueError(f"approval_status must be {expected.value}")
        return self


class RenderBundle(StrictModel):
    """Assembly payload handed to the future PDF renderer."""

    bundle_id: str = Field(default_factory=lambda: f"rnd-{uuid4().hex[:12]}")
    spec_id: str
    blueprint_id: str
    generated_at: datetime = Field(default_factory=utc_now)
    items: list[ValidatedItem]
    student_metadata: dict[str, str] = Field(default_factory=dict)
    internal_metadata: dict[str, str] = Field(default_factory=dict)
    output_targets: list[str] = Field(default_factory=list)
    answer_key: dict[int, str]
    asset_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_render_metadata(cls, data: Any) -> Any:
        """Promote legacy mixed cover metadata into explicit student/internal buckets."""
        if not isinstance(data, dict):
            return data
        if "cover_metadata" not in data or "student_metadata" in data or "internal_metadata" in data:
            return data

        cover_metadata = dict(data.pop("cover_metadata") or {})
        student_keys = {"title", "duration_minutes", "total_score"}
        data["student_metadata"] = {
            key: value for key, value in cover_metadata.items() if key in student_keys
        }
        data["internal_metadata"] = {
            key: value for key, value in cover_metadata.items() if key not in student_keys
        }
        return data

    @model_validator(mode="after")
    def validate_render_bundle(self) -> "RenderBundle":
        """Ensure the rendered bundle stays aligned with 30-item exam shape."""
        if len(self.items) != 30:
            raise ValueError("RenderBundle must contain 30 validated items")
        if sorted(self.answer_key) != list(range(1, 31)):
            raise ValueError("answer_key must contain entries for items 1..30")
        required_student_keys = {"title", "duration_minutes", "total_score"}
        missing_student_keys = sorted(required_student_keys - set(self.student_metadata))
        if missing_student_keys:
            raise ValueError(
                "student_metadata must define title, duration_minutes, and total_score"
            )
        canonical_answer_key: dict[int, str] = {}
        for item in self.items:
            item_no = item.solved.draft.blueprint.item_no
            expected_answer = item.solved.final_answer
            actual_answer = self.answer_key[item_no]
            if actual_answer != expected_answer:
                raise ValueError("answer_key must align with solved item final_answer values")
            canonical_answer_key[item_no] = expected_answer
        object.__setattr__(self, "answer_key", canonical_answer_key)
        return self


class PromptPacket(StrictModel):
    """Shared contract for manual and API prompt execution."""

    packet_id: str = Field(default_factory=lambda: f"pkt-{uuid4().hex[:12]}")
    mode: ExamMode
    stage: PipelineStage
    stage_name: str = "unspecified"
    spec_id: str
    run_id: str
    blueprint_id: str | None = None
    item_no: int | None = None
    instructions: list[str]
    input_artifact_ids: list[str] = Field(default_factory=list)
    lineage_parent_ids: list[str] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    expected_output_model: str
    response_schema_version: str = "1.0"
    response_json_schema: dict[str, Any] = Field(default_factory=dict)
    prompt_template_path: str | None = None
    prompt_version: str | None = None
    prompt_hash: str | None = None
    seed: int | None = None
    attempt: int = 1
    provider_name: str | None = None


class ManualExchangePacket(StrictModel):
    """Manual-mode wrapper using the same prompt contract as API mode."""

    exchange_id: str = Field(default_factory=lambda: f"mxl-{uuid4().hex[:12]}")
    prompt_packet: PromptPacket
    submitted_output: dict[str, Any] | None = None
    operator_notes: list[str] = Field(default_factory=list)
    status: ExchangeStatus = ExchangeStatus.PENDING
    responded_at: datetime | None = None

    @model_validator(mode="after")
    def validate_manual_packet(self) -> "ManualExchangePacket":
        """Restrict this wrapper to manual-mode exchanges."""
        if self.prompt_packet.mode != ExamMode.MANUAL:
            raise ValueError("prompt_packet.mode must be manual")
        if self.status == ExchangeStatus.SUBMITTED and self.submitted_output is None:
            raise ValueError("submitted_output is required when status=submitted")
        if self.responded_at and self.submitted_output is None:
            raise ValueError("responded_at requires submitted_output")
        return self


ArtifactModel = (
    ExamSpec
    | ExamBlueprint
    | DraftItem
    | SolvedItem
    | CritiqueReport
    | ValidationReport
    | ValidatedItem
    | RenderBundle
    | PromptPacket
    | ManualExchangePacket
)

PipelineStageName = Literal[
    "design",
    "generation",
    "solving",
    "validation",
    "revision",
    "assembly",
    "render",
]
