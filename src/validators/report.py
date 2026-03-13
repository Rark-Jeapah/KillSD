"""Validation suite orchestration and report models."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import Field

from src.core.schemas import (
    ApprovalStatus,
    CritiqueReport,
    ExamSpec,
    FailureLevel,
    SolvedItem,
    StrictModel,
    ValidationFinding,
    ValidationReport,
    ValidationSeverity,
    ValidationStatus,
    ValidatedItem,
)
from src.distill.fingerprint import ItemFingerprint
from src.distill.item_card_schema import ItemCard
from src.distill.solution_graph import SolutionGraph
from src.validators import reason_codes as rc


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class SimilarityThresholdConfig(StrictModel):
    """Thresholds used by similarity validation."""

    surface_soft_fail: float = 0.58
    surface_hard_fail: float = 0.75
    expression_soft_fail: float = 0.72
    expression_hard_fail: float = 0.88
    solution_graph_soft_fail: float = 0.62
    solution_graph_hard_fail: float = 0.80


class DistilledValidationResources(StrictModel):
    """Runtime-safe distilled resources consumed by validators."""

    item_cards: list[ItemCard] = Field(default_factory=list)
    fingerprints: list[ItemFingerprint] = Field(default_factory=list)
    solution_graphs: list[SolutionGraph] = Field(default_factory=list)
    allowed_topics: list[str] = Field(default_factory=list)
    forbidden_topics: list[str] = Field(default_factory=list)
    diagram_asset_root: str | None = None


class DifficultyEstimate(StrictModel):
    """Proxy metrics used to approximate item difficulty."""

    expected_step_count: int
    concept_count: int
    branching_factor: float
    solver_disagreement_score: float
    predicted_band: str


class ValidatorSectionResult(StrictModel):
    """Result of a single validator module."""

    validator_name: str
    findings: list[ValidationFinding] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)


class ValidationContext(StrictModel):
    """Input bundle shared across validator modules."""

    spec: ExamSpec
    solved_item: SolvedItem
    critique_report: CritiqueReport
    resources: DistilledValidationResources
    similarity_thresholds: SimilarityThresholdConfig
    cross_check_answer: str | None = None
    expected_answer: str | None = None
    asset_refs: list[str] = Field(default_factory=list)
    xelatex_path: str | None = None


class ValidatorSuiteReport(StrictModel):
    """Artifact-friendly report for the full validator suite."""

    suite_id: str = Field(default_factory=lambda: f"vsr-{uuid4().hex[:12]}")
    spec_id: str
    item_no: int
    sections: list[ValidatorSectionResult]
    difficulty_estimate: DifficultyEstimate
    final_report: ValidationReport
    generated_at: datetime = Field(default_factory=utc_now)


DEFAULT_FORBIDDEN_TOPICS = [
    "geometry",
    "matrix",
    "vector",
    "complex_number",
    "calculus_2",
    "discrete_math",
]


def load_similarity_thresholds(config_path: Path) -> SimilarityThresholdConfig:
    """Load similarity thresholds from JSON config."""
    data = json.loads(config_path.read_text(encoding="utf-8"))
    return SimilarityThresholdConfig.model_validate(data)


def load_distilled_resources(repo_root: Path, spec_id: str) -> DistilledValidationResources:
    """Load distilled validation resources from the repository."""
    base_dir = repo_root / "data" / "distilled" / spec_id
    item_cards_payload = json.loads((base_dir / "item_cards.json").read_text(encoding="utf-8"))
    fingerprints_payload = json.loads((base_dir / "fingerprints.json").read_text(encoding="utf-8"))
    solution_graphs_payload = json.loads(
        (base_dir / "solution_graphs.json").read_text(encoding="utf-8")
    )

    item_cards = [ItemCard.model_validate(item) for item in item_cards_payload.get("items", [])]
    fingerprints = [
        ItemFingerprint.model_validate(item) for item in fingerprints_payload.get("items", [])
    ]
    solution_graphs = [
        SolutionGraph.model_validate(item)
        for item in solution_graphs_payload.get("graphs", [])
    ]
    allowed_topics = sorted(
        {
            card.subject_area
            for card in item_cards
        }
        | {
            card.topic
            for card in item_cards
        }
        | {
            subtopic
            for card in item_cards
            for subtopic in card.subtopics
        }
    )

    return DistilledValidationResources(
        item_cards=item_cards,
        fingerprints=fingerprints,
        solution_graphs=solution_graphs,
        allowed_topics=allowed_topics,
        forbidden_topics=DEFAULT_FORBIDDEN_TOPICS,
        diagram_asset_root=str(base_dir / "assets"),
    )


def build_validation_report(
    *,
    item_no: int,
    sections: list[ValidatorSectionResult],
) -> ValidationReport:
    """Compile validator sections into the canonical ValidationReport."""
    findings = [finding for section in sections for finding in section.findings]
    if not findings:
        findings = [
            ValidationFinding(
                check_name="validator_suite",
                passed=True,
                severity=rc.VALIDATOR_NO_FINDINGS.default_severity,
                message="No validator findings were emitted.",
                reason_code=rc.VALIDATOR_NO_FINDINGS.code,
                validator_name="validator_suite",
                failure_level=rc.VALIDATOR_NO_FINDINGS.default_failure_level,
            )
        ]

    failing_findings = [finding for finding in findings if not finding.passed]
    hard_fail_count = sum(
        1
        for finding in failing_findings
        if finding.failure_level == FailureLevel.HARD or finding.severity == ValidationSeverity.ERROR
    )
    soft_fail_count = max(0, len(failing_findings) - hard_fail_count)
    failing_validators = sorted({finding.validator_name for finding in failing_findings})
    reason_codes = sorted({finding.reason_code for finding in failing_findings})
    if not failing_findings:
        status = ValidationStatus.PASS
        summary = (
            f"Pass: 0 failing checks across {len(sections)} validators after {len(findings)} total checks."
        )
    elif any(
        finding.failure_level == FailureLevel.HARD or finding.severity == ValidationSeverity.ERROR
        for finding in failing_findings
    ):
        status = ValidationStatus.FAIL
        summary = (
            f"Rejected: {len(failing_findings)} failing checks "
            f"(hard={hard_fail_count}, soft={soft_fail_count}) across "
            f"{len(failing_validators)} validators. "
            f"Validators: {', '.join(failing_validators)}. "
            f"Reason codes: {', '.join(reason_codes)}."
        )
    else:
        status = ValidationStatus.NEEDS_REVISION
        summary = (
            f"Needs revision: {len(failing_findings)} failing checks "
            f"(hard=0, soft={soft_fail_count}) across {len(failing_validators)} validators. "
            f"Validators: {', '.join(failing_validators)}. "
            f"Reason codes: {', '.join(reason_codes)}."
        )

    return ValidationReport(
        item_no=item_no,
        status=status,
        findings=findings,
        summary=summary,
    )


def build_validated_item(
    *, solved_item: SolvedItem, final_report: ValidationReport, critique_report: CritiqueReport
) -> ValidatedItem:
    """Create a ValidatedItem from the suite report."""
    approval_status = {
        ValidationStatus.PASS: ApprovalStatus.APPROVED,
        ValidationStatus.NEEDS_REVISION: ApprovalStatus.NEEDS_REVISION,
        ValidationStatus.FAIL: ApprovalStatus.REJECTED,
    }[final_report.status]
    revision_notes = [
        finding.recommendation for finding in critique_report.findings if finding.recommendation
    ]
    revision_notes.extend(
        finding.recommendation for finding in final_report.findings if finding.recommendation
    )
    validated_item_kwargs = {
        "solved": solved_item,
        "validation": final_report,
        "approval_status": approval_status,
        "revision_notes": [note for note in revision_notes if note],
    }
    try:
        return ValidatedItem(**validated_item_kwargs)
    except Exception:
        # Regression fixtures intentionally bypass some solved-item invariants so the
        # validator suite can report on malformed legacy payloads instead of crashing.
        return ValidatedItem.model_construct(**validated_item_kwargs)


def run_validator_suite(
    *,
    context: ValidationContext,
) -> tuple[ValidatorSuiteReport, ValidatedItem]:
    """Run all validators and return both suite and validated item artifacts."""
    from src.validators.answer_validator import validate_answer
    from src.validators.curriculum_validator import validate_curriculum
    from src.validators.difficulty_estimator import (
        estimate_difficulty,
        validate_difficulty_proxy,
    )
    from src.validators.format_validator import validate_format
    from src.validators.render_validator import validate_render
    from src.validators.similarity_validator import validate_similarity

    difficulty_estimate = estimate_difficulty(
        solved_item=context.solved_item,
        critique_report=context.critique_report,
        cross_check_answer=context.cross_check_answer,
    )
    sections = [
        validate_format(solved_item=context.solved_item, spec=context.spec),
        validate_curriculum(
            solved_item=context.solved_item,
            spec=context.spec,
            allowed_topics=context.resources.allowed_topics,
            forbidden_topics=context.resources.forbidden_topics,
        ),
        validate_answer(
            solved_item=context.solved_item,
            expected_answer=context.expected_answer,
            cross_check_answer=context.cross_check_answer,
        ),
        validate_similarity(
            solved_item=context.solved_item,
            existing_item_cards=context.resources.item_cards,
            existing_fingerprints=context.resources.fingerprints,
            existing_solution_graphs=context.resources.solution_graphs,
            thresholds=context.similarity_thresholds,
        ),
        validate_render(
            solved_item=context.solved_item,
            asset_root=Path(context.resources.diagram_asset_root)
            if context.resources.diagram_asset_root
            else None,
            asset_refs=context.asset_refs,
            xelatex_path=context.xelatex_path,
        ),
        validate_difficulty_proxy(
            solved_item=context.solved_item,
            difficulty_estimate=difficulty_estimate,
        ),
    ]
    final_report = build_validation_report(
        item_no=context.solved_item.draft.blueprint.item_no,
        sections=sections,
    )
    suite_report = ValidatorSuiteReport(
        spec_id=context.spec.spec_id,
        item_no=context.solved_item.draft.blueprint.item_no,
        sections=sections,
        difficulty_estimate=difficulty_estimate,
        final_report=final_report,
    )
    validated_item = build_validated_item(
        solved_item=context.solved_item,
        final_report=final_report,
        critique_report=context.critique_report,
    )
    return suite_report, validated_item
