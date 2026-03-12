"""Curriculum validator for allowed and forbidden topics."""

from __future__ import annotations

from src.core.schemas import (
    ExamSpec,
    SolvedItem,
    ValidationFinding,
)
from src.validators import reason_codes as rc
from src.validators.report import ValidatorSectionResult


def validate_curriculum(
    *,
    solved_item: SolvedItem,
    spec: ExamSpec,
    allowed_topics: list[str],
    forbidden_topics: list[str],
) -> ValidatorSectionResult:
    """Validate subject-area alignment and forbidden-topic leakage."""
    blueprint = solved_item.draft.blueprint
    combined_text = " ".join(
        [
            blueprint.domain,
            blueprint.objective,
            solved_item.draft.stem,
            " ".join(blueprint.skill_tags),
        ]
    ).lower()
    domain_allowed = blueprint.domain in spec.subject_areas

    findings: list[ValidationFinding] = [
        ValidationFinding(
            check_name="domain_allowed",
            validator_name="curriculum_validator",
            passed=domain_allowed,
            severity=rc.CURRICULUM_DOMAIN_FORBIDDEN.default_severity,
            message="blueprint domain is allowed by the exam spec",
            reason_code=rc.CURRICULUM_DOMAIN_FORBIDDEN.code,
            failure_level=rc.CURRICULUM_DOMAIN_FORBIDDEN.default_failure_level,
            recommendation="Regenerate the item under an allowed subject area."
            if not domain_allowed
            else None,
        )
    ]

    forbidden_hits = [topic for topic in forbidden_topics if topic.lower() in combined_text]
    findings.append(
        ValidationFinding(
            check_name="forbidden_topics_absent",
            validator_name="curriculum_validator",
            passed=not forbidden_hits,
            severity=rc.CURRICULUM_FORBIDDEN_TOPIC_DETECTED.default_severity,
            message="no forbidden topics were detected in the item text",
            reason_code=rc.CURRICULUM_FORBIDDEN_TOPIC_DETECTED.code,
            failure_level=rc.CURRICULUM_FORBIDDEN_TOPIC_DETECTED.default_failure_level,
            recommendation="Discard the item and regenerate within the 2028 CSAT math scope."
            if forbidden_hits
            else None,
            context={"forbidden_hits": forbidden_hits},
        )
    )
    findings.append(
        ValidationFinding(
            check_name="curriculum_envelope",
            validator_name="curriculum_validator",
            passed=domain_allowed and not forbidden_hits,
            severity=rc.CURRICULUM_OUT_OF_CURRICULUM.default_severity,
            message="the item stays within the allowed 2028 CSAT curriculum envelope",
            reason_code=rc.CURRICULUM_OUT_OF_CURRICULUM.code,
            failure_level=rc.CURRICULUM_OUT_OF_CURRICULUM.default_failure_level,
            recommendation="Discard the item instead of revising locally because the content is out of curriculum."
            if (not domain_allowed or forbidden_hits)
            else None,
            context={"domain_allowed": domain_allowed, "forbidden_hits": forbidden_hits},
        )
    )

    allowed_hits = [
        topic
        for topic in allowed_topics
        if topic.lower() in combined_text or topic == blueprint.domain
    ]
    findings.append(
        ValidationFinding(
            check_name="allowed_topic_overlap",
            validator_name="curriculum_validator",
            passed=bool(allowed_hits) or not (domain_allowed and not forbidden_hits),
            severity=rc.CURRICULUM_ALLOWED_TOPIC_MISS.default_severity,
            message="item text overlaps with known allowed topics or subtopics",
            reason_code=rc.CURRICULUM_ALLOWED_TOPIC_MISS.code,
            failure_level=rc.CURRICULUM_ALLOWED_TOPIC_MISS.default_failure_level,
            recommendation="Tighten the item objective and stem so they clearly map to an allowed topic."
            if not allowed_hits and domain_allowed and not forbidden_hits
            else None,
            context={"allowed_hits": allowed_hits[:12]},
        )
    )

    return ValidatorSectionResult(
        validator_name="curriculum_validator",
        findings=findings,
        metrics={"allowed_hits": len(allowed_hits), "forbidden_hits": forbidden_hits},
    )
