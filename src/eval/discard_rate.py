"""Discard-rate reporting for mini-alpha assembly and human review."""

from __future__ import annotations

from collections import Counter
from enum import Enum
from pathlib import Path

from pydantic import Field

from src.core.schemas import StrictModel
from src.eval.review_feedback import (
    HumanReviewDecision,
    HumanReviewRecord,
    ReviewCandidateContext,
    ReviewFeedbackReport,
    load_human_review_records,
    build_review_feedback_report,
)


class CandidateOutcome(str, Enum):
    """Selection outcome for one candidate in the mini-alpha pool."""

    SELECTED = "selected"
    RESERVE = "reserve"
    AUTO_DISCARDED = "auto_discarded"


class CandidateOutcomeRecord(StrictModel):
    """Outcome and rationale for a candidate considered during assembly."""

    candidate_id: str
    source_atom_id: str | None = None
    family_id: str | None = None
    source_item_id: str | None = None
    source_item_no: int | None = None
    target_item_no: int | None = None
    domain: str
    difficulty: str
    outcome: CandidateOutcome
    reasons: list[str] = Field(default_factory=list)

    def to_review_context(self) -> ReviewCandidateContext:
        """Return the subset of metadata needed for review aggregation."""

        return ReviewCandidateContext(
            candidate_id=self.candidate_id,
            item_no=self.target_item_no,
            source_atom_id=self.source_atom_id,
            family_id=self.family_id,
            source_item_id=self.source_item_id,
            source_item_no=self.source_item_no,
            domain=self.domain,
            difficulty=self.difficulty,
        )


class DiscardRateReport(StrictModel):
    """Aggregated automated and human-review discard metrics."""

    total_candidates: int
    selected_count: int
    reserve_count: int
    auto_discarded_count: int
    auto_discard_rate: float
    auto_discard_reason_counts: dict[str, int] = Field(default_factory=dict)
    human_review_expected_count: int
    human_reviewed_count: int
    human_pending_count: int
    human_discarded_count: int
    human_revision_count: int
    human_discard_rate: float | None = None
    human_reason_counts: dict[str, int] = Field(default_factory=dict)
    collection_ready: bool = True
    review_feedback: ReviewFeedbackReport | None = None


def build_discard_rate_report(
    *,
    outcomes: list[CandidateOutcomeRecord],
    human_reviews: list[HumanReviewRecord] | None = None,
) -> DiscardRateReport:
    """Aggregate automated discard counts and optional human-review results."""

    auto_reason_counts: Counter[str] = Counter()
    for outcome in outcomes:
        if outcome.outcome != CandidateOutcome.AUTO_DISCARDED:
            continue
        auto_reason_counts.update(outcome.reasons or ["unspecified"])

    selected_candidate_ids = {
        outcome.candidate_id
        for outcome in outcomes
        if outcome.outcome == CandidateOutcome.SELECTED
    }
    selected_count = len(selected_candidate_ids)
    reviews = [
        review
        for review in (human_reviews or [])
        if review.candidate_id in selected_candidate_ids
    ]
    reviewed = [review for review in reviews if review.actionable]
    human_reason_counts: Counter[str] = Counter()
    for review in reviewed:
        human_reason_counts.update([review.reason_code or "unspecified"])

    human_discarded_count = sum(
        1 for review in reviewed if review.decision == HumanReviewDecision.REJECT
    )
    human_revision_count = sum(
        1 for review in reviewed if review.decision == HumanReviewDecision.REVISE
    )
    human_reviewed_count = len(reviewed)
    human_pending_count = max(0, selected_count - human_reviewed_count)
    human_discard_rate = (
        round(human_discarded_count / human_reviewed_count, 4)
        if human_reviewed_count
        else None
    )

    total_candidates = len(outcomes)
    auto_discarded_count = sum(
        1 for outcome in outcomes if outcome.outcome == CandidateOutcome.AUTO_DISCARDED
    )
    reserve_count = sum(
        1 for outcome in outcomes if outcome.outcome == CandidateOutcome.RESERVE
    )
    auto_discard_rate = round(auto_discarded_count / total_candidates, 4) if total_candidates else 0.0

    return DiscardRateReport(
        total_candidates=total_candidates,
        selected_count=selected_count,
        reserve_count=reserve_count,
        auto_discarded_count=auto_discarded_count,
        auto_discard_rate=auto_discard_rate,
        auto_discard_reason_counts=dict(sorted(auto_reason_counts.items())),
        human_review_expected_count=selected_count,
        human_reviewed_count=human_reviewed_count,
        human_pending_count=human_pending_count,
        human_discarded_count=human_discarded_count,
        human_revision_count=human_revision_count,
        human_discard_rate=human_discard_rate,
        human_reason_counts=dict(sorted(human_reason_counts.items())),
        collection_ready=True,
        review_feedback=build_review_feedback_report(
            candidates=[outcome.to_review_context() for outcome in outcomes],
            human_reviews=human_reviews,
        ),
    )


def write_discard_rate_report(output_path: Path, report: DiscardRateReport) -> Path:
    """Persist the discard-rate report as JSON."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return output_path
