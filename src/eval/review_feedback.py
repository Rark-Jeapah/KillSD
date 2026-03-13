"""Human-review schemas and feedback-loop helpers."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import Field, model_validator

from src.core.schemas import DifficultyBand, StrictModel


class HumanReviewDecision(str, Enum):
    """Normalized reviewer decision labels."""

    PENDING = "pending"
    ACCEPT = "accept"
    REVISE = "revise"
    REJECT = "reject"
    DISCARD = "reject"


class HumanReviewRecord(StrictModel):
    """Reviewer label attached to one generated candidate."""

    item_no: int | None = None
    candidate_id: str
    decision: HumanReviewDecision = HumanReviewDecision.PENDING
    reason_code: str | None = None
    difficulty_label: DifficultyBand | None = None
    wording_naturalness: int | None = Field(default=None, ge=1, le=5)
    distractor_quality: int | None = Field(default=None, ge=1, le=5)
    curriculum_fit: int | None = Field(default=None, ge=1, le=5)
    notes: str | None = None
    reviewer_id: str | None = None
    reviewed_at: datetime | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_payload(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        if payload.get("decision") == "discard":
            payload["decision"] = HumanReviewDecision.REJECT.value
        reasons = payload.pop("reasons", None)
        if payload.get("reason_code") is None and isinstance(reasons, list) and reasons:
            payload["reason_code"] = str(reasons[0]).strip() or None
        return payload

    @model_validator(mode="after")
    def _normalize_strings(self) -> "HumanReviewRecord":
        object.__setattr__(self, "reason_code", _normalized_text(self.reason_code))
        object.__setattr__(self, "notes", _normalized_text(self.notes))
        object.__setattr__(self, "reviewer_id", _normalized_text(self.reviewer_id))
        return self

    @property
    def reasons(self) -> list[str]:
        """Legacy compatibility shim for older tests and callers."""
        return [self.reason_code] if self.reason_code else []

    @property
    def actionable(self) -> bool:
        return self.decision != HumanReviewDecision.PENDING


ReviewLabel = HumanReviewRecord


class CandidateReviewSummary(StrictModel):
    """Collapsed per-candidate review state stored on bundles/manifests."""

    total_labels: int = 0
    actionable_labels: int = 0
    accept_count: int = 0
    revise_count: int = 0
    reject_count: int = 0
    latest_decision: HumanReviewDecision = HumanReviewDecision.PENDING
    latest_reason_code: str | None = None
    latest_review: HumanReviewRecord | None = None
    blocked_from_selection: bool = False


class ReviewCandidateContext(StrictModel):
    """Metadata needed to export/import review packets and aggregate feedback."""

    candidate_id: str
    item_no: int | None = None
    source_atom_id: str | None = None
    family_id: str | None = None
    source_item_id: str | None = None
    source_item_no: int | None = None
    domain: str | None = None
    difficulty: str | None = None
    format: str | None = None
    score: int | None = None
    objective: str | None = None
    skill_tags: list[str] = Field(default_factory=list)
    stem: str | None = None
    choices: list[str] = Field(default_factory=list)
    final_answer: str | None = None
    solution_summary: str | None = None
    validated_item_path: str | None = None
    validator_report_path: str | None = None
    review_sheet_path: str | None = None
    item_pdf_path: str | None = None
    review_summary: CandidateReviewSummary | None = None


class ReviewPacketEntry(ReviewCandidateContext):
    """Offline review packet row with embedded editable label fields."""

    review_label: HumanReviewRecord


class RejectRateBreakdown(StrictModel):
    """Reject-rate summary for one family or atom bucket."""

    key: str
    reviewed_count: int
    accept_count: int
    revise_count: int
    reject_count: int
    reject_rate: float


class ReviewReasonCodeCount(StrictModel):
    """Frequency summary for review reason codes."""

    reason_code: str
    count: int


class RegeneratePriorityRecord(StrictModel):
    """Aggregated regenerate recommendation for weak atoms."""

    source_atom_id: str | None = None
    family_id: str | None = None
    candidate_ids: list[str] = Field(default_factory=list)
    reviewed_count: int
    reject_count: int
    revise_count: int
    priority_score: int
    top_reason_codes: list[str] = Field(default_factory=list)
    mean_wording_naturalness: float | None = None
    mean_distractor_quality: float | None = None
    mean_curriculum_fit: float | None = None
    recommended_action: str


class ReviewFeedbackReport(StrictModel):
    """Human-review feedback summary used by import/reporting flows."""

    candidate_count: int
    reviewed_candidate_count: int
    pending_candidate_count: int
    accepted_candidate_count: int
    revised_candidate_count: int
    rejected_candidate_count: int
    family_reject_rates: list[RejectRateBreakdown] = Field(default_factory=list)
    atom_reject_rates: list[RejectRateBreakdown] = Field(default_factory=list)
    top_reason_codes: list[ReviewReasonCodeCount] = Field(default_factory=list)
    regenerate_priority_list: list[RegeneratePriorityRecord] = Field(default_factory=list)


def _normalized_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _load_review_payload(path: Path) -> list[Any]:
    if path.suffix == ".jsonl":
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("entries"), list):
        return payload["entries"]
    raise ValueError("Review label payload must be a JSON list, JSONL, or {\"entries\": [...]} object")


def _extract_review_payload(entry: Any) -> Any:
    if not isinstance(entry, dict):
        return entry
    if "review_label" not in entry:
        return entry
    review_payload = dict(entry["review_label"])
    review_payload.setdefault("candidate_id", entry.get("candidate_id"))
    review_payload.setdefault("item_no", entry.get("item_no"))
    return review_payload


def load_human_review_records(path: Path) -> list[HumanReviewRecord]:
    """Load review labels from JSON or JSONL."""

    return [
        HumanReviewRecord.model_validate(_extract_review_payload(entry))
        for entry in _load_review_payload(path)
    ]


def dedupe_human_review_records(records: list[HumanReviewRecord]) -> list[HumanReviewRecord]:
    """Deduplicate records while preserving input order."""

    seen: set[str] = set()
    deduped: list[HumanReviewRecord] = []
    for record in records:
        key = json.dumps(record.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def merge_human_review_records(
    existing: list[HumanReviewRecord],
    incoming: list[HumanReviewRecord],
) -> list[HumanReviewRecord]:
    """Append non-pending labels and deduplicate the combined history."""

    actionable_incoming = [record for record in incoming if record.actionable]
    return dedupe_human_review_records([*existing, *actionable_incoming])


def write_human_review_records_jsonl(
    path: Path,
    records: list[HumanReviewRecord],
) -> Path:
    """Persist review labels as JSONL."""

    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(record.model_dump(mode="json"), ensure_ascii=False)
        for record in records
    ]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return path


def build_candidate_review_summaries(
    reviews: list[HumanReviewRecord],
) -> dict[str, CandidateReviewSummary]:
    """Collapse review history into one summary per candidate."""

    grouped: dict[str, list[HumanReviewRecord]] = defaultdict(list)
    for review in reviews:
        grouped[review.candidate_id].append(review)

    summaries: dict[str, CandidateReviewSummary] = {}
    for candidate_id, records in grouped.items():
        actionable = [record for record in records if record.actionable]
        latest = actionable[-1] if actionable else (records[-1] if records else None)
        accept_count = sum(1 for record in actionable if record.decision == HumanReviewDecision.ACCEPT)
        revise_count = sum(1 for record in actionable if record.decision == HumanReviewDecision.REVISE)
        reject_count = sum(1 for record in actionable if record.decision == HumanReviewDecision.REJECT)
        summaries[candidate_id] = CandidateReviewSummary(
            total_labels=len(records),
            actionable_labels=len(actionable),
            accept_count=accept_count,
            revise_count=revise_count,
            reject_count=reject_count,
            latest_decision=latest.decision if latest is not None else HumanReviewDecision.PENDING,
            latest_reason_code=latest.reason_code if latest is not None else None,
            latest_review=latest,
            blocked_from_selection=(
                latest is not None and latest.decision == HumanReviewDecision.REJECT
            ),
        )
    return summaries


def review_selection_penalty(summary: CandidateReviewSummary | None) -> int:
    """Softly deprioritize previously reviewed candidates that still need work."""

    if summary is None or summary.latest_review is None:
        return 0
    if summary.latest_decision == HumanReviewDecision.REJECT:
        return 1000
    if summary.latest_decision != HumanReviewDecision.REVISE:
        return 0
    review = summary.latest_review
    penalty = 150
    for metric in (
        review.wording_naturalness,
        review.distractor_quality,
        review.curriculum_fit,
    ):
        if metric is None:
            continue
        penalty += max(0, 3 - metric) * 25
    return penalty


def candidate_blocked_from_selection(summary: CandidateReviewSummary | None) -> bool:
    """Return whether the latest review blocks the candidate from selection."""

    return bool(summary and summary.blocked_from_selection)


def _bucket_key(value: str | None, *, fallback: str) -> str:
    return value or fallback


def _reject_rate_breakdowns(
    grouped: dict[str, list[tuple[ReviewCandidateContext, HumanReviewRecord]]],
) -> list[RejectRateBreakdown]:
    rows: list[RejectRateBreakdown] = []
    for key, items in grouped.items():
        reviewed_count = len(items)
        accept_count = sum(1 for _, review in items if review.decision == HumanReviewDecision.ACCEPT)
        revise_count = sum(1 for _, review in items if review.decision == HumanReviewDecision.REVISE)
        reject_count = sum(1 for _, review in items if review.decision == HumanReviewDecision.REJECT)
        rows.append(
            RejectRateBreakdown(
                key=key,
                reviewed_count=reviewed_count,
                accept_count=accept_count,
                revise_count=revise_count,
                reject_count=reject_count,
                reject_rate=round(reject_count / reviewed_count, 4) if reviewed_count else 0.0,
            )
        )
    return sorted(
        rows,
        key=lambda row: (-row.reject_rate, -row.reject_count, -row.reviewed_count, row.key),
    )


def _mean_score(values: list[int | None]) -> float | None:
    numeric = [value for value in values if value is not None]
    if not numeric:
        return None
    return round(sum(numeric) / len(numeric), 2)


def _priority_score(review: HumanReviewRecord) -> int:
    base = 18 if review.decision == HumanReviewDecision.REJECT else 10
    if review.reason_code:
        base += 2
    for metric in (
        review.wording_naturalness,
        review.distractor_quality,
        review.curriculum_fit,
    ):
        if metric is None:
            continue
        base += max(0, 4 - metric)
    return base


def build_review_feedback_report(
    *,
    candidates: list[ReviewCandidateContext],
    human_reviews: list[HumanReviewRecord] | None = None,
) -> ReviewFeedbackReport:
    """Aggregate review labels into family/atom weakness reports."""

    summaries = build_candidate_review_summaries(human_reviews or [])
    reviewed_items: list[tuple[ReviewCandidateContext, HumanReviewRecord]] = []
    for candidate in candidates:
        summary = summaries.get(candidate.candidate_id)
        if summary is None or summary.latest_review is None or not summary.latest_review.actionable:
            continue
        reviewed_items.append((candidate, summary.latest_review))

    family_grouped: dict[str, list[tuple[ReviewCandidateContext, HumanReviewRecord]]] = defaultdict(list)
    atom_grouped: dict[str, list[tuple[ReviewCandidateContext, HumanReviewRecord]]] = defaultdict(list)
    reason_counts: Counter[str] = Counter()
    priority_groups: dict[str, list[tuple[ReviewCandidateContext, HumanReviewRecord]]] = defaultdict(list)

    for candidate, review in reviewed_items:
        family_grouped[_bucket_key(candidate.family_id, fallback="unknown_family")].append(
            (candidate, review)
        )
        atom_key = _bucket_key(candidate.source_atom_id, fallback=candidate.candidate_id)
        atom_grouped[atom_key].append((candidate, review))
        if review.decision in {HumanReviewDecision.REJECT, HumanReviewDecision.REVISE}:
            reason_counts.update([review.reason_code or "unspecified"])
            priority_groups[atom_key].append((candidate, review))

    priority_records: list[RegeneratePriorityRecord] = []
    for atom_key, items in priority_groups.items():
        family_id = next((candidate.family_id for candidate, _ in items if candidate.family_id), None)
        reject_count = sum(1 for _, review in items if review.decision == HumanReviewDecision.REJECT)
        revise_count = sum(1 for _, review in items if review.decision == HumanReviewDecision.REVISE)
        reason_counter = Counter(review.reason_code or "unspecified" for _, review in items)
        priority_records.append(
            RegeneratePriorityRecord(
                source_atom_id=next(
                    (candidate.source_atom_id for candidate, _ in items if candidate.source_atom_id),
                    None,
                ),
                family_id=family_id,
                candidate_ids=sorted({candidate.candidate_id for candidate, _ in items}),
                reviewed_count=len(items),
                reject_count=reject_count,
                revise_count=revise_count,
                priority_score=sum(_priority_score(review) for _, review in items),
                top_reason_codes=[
                    reason
                    for reason, _ in reason_counter.most_common(3)
                ],
                mean_wording_naturalness=_mean_score(
                    [review.wording_naturalness for _, review in items]
                ),
                mean_distractor_quality=_mean_score(
                    [review.distractor_quality for _, review in items]
                ),
                mean_curriculum_fit=_mean_score(
                    [review.curriculum_fit for _, review in items]
                ),
                recommended_action="regenerate" if reject_count > 0 else "revise_then_regenerate",
            )
        )
    priority_records.sort(
        key=lambda record: (
            -record.priority_score,
            -record.reject_count,
            -record.revise_count,
            record.source_atom_id or "",
            record.family_id or "",
        )
    )

    reviewed_candidate_ids = {candidate.candidate_id for candidate, _ in reviewed_items}
    accepted_candidate_count = sum(
        1 for _, review in reviewed_items if review.decision == HumanReviewDecision.ACCEPT
    )
    revised_candidate_count = sum(
        1 for _, review in reviewed_items if review.decision == HumanReviewDecision.REVISE
    )
    rejected_candidate_count = sum(
        1 for _, review in reviewed_items if review.decision == HumanReviewDecision.REJECT
    )

    return ReviewFeedbackReport(
        candidate_count=len(candidates),
        reviewed_candidate_count=len(reviewed_candidate_ids),
        pending_candidate_count=max(0, len(candidates) - len(reviewed_candidate_ids)),
        accepted_candidate_count=accepted_candidate_count,
        revised_candidate_count=revised_candidate_count,
        rejected_candidate_count=rejected_candidate_count,
        family_reject_rates=_reject_rate_breakdowns(family_grouped),
        atom_reject_rates=_reject_rate_breakdowns(atom_grouped),
        top_reason_codes=[
            ReviewReasonCodeCount(reason_code=reason_code, count=count)
            for reason_code, count in reason_counts.most_common(10)
        ],
        regenerate_priority_list=priority_records,
    )


def build_review_packet_markdown(
    *,
    title: str,
    entries: list[ReviewPacketEntry],
) -> str:
    """Render a markdown-friendly offline review packet."""

    lines = [
        "# Review Packet",
        "",
        f"- title: `{title}`",
        f"- item_count: `{len(entries)}`",
        "- editable_fields: `decision`, `reason_code`, `difficulty_label`, "
        "`wording_naturalness`, `distractor_quality`, `curriculum_fit`, `notes`",
        "- decision_values: `accept | revise | reject`",
    ]
    for entry in entries:
        lines.extend(
            [
                "",
                f"## Item {entry.item_no or '-'}",
                f"- candidate_id: `{entry.candidate_id}`",
                f"- family_id: `{entry.family_id}`",
                f"- source_atom_id: `{entry.source_atom_id}`",
                f"- source_item_no: `{entry.source_item_no}`",
                f"- domain: `{entry.domain}`",
                f"- difficulty: `{entry.difficulty}`",
                f"- format: `{entry.format}`",
                f"- score: `{entry.score}`",
                f"- objective: `{entry.objective}`",
            ]
        )
        if entry.item_pdf_path:
            lines.append(f"- item_pdf_path: `{entry.item_pdf_path}`")
        if entry.review_sheet_path:
            lines.append(f"- review_sheet_path: `{entry.review_sheet_path}`")
        lines.extend(["", "### Stem", entry.stem or ""])
        if entry.choices:
            lines.extend(["", "### Choices"])
            for index, choice in enumerate(entry.choices, start=1):
                lines.append(f"{index}. {choice}")
        if entry.solution_summary:
            lines.extend(["", "### Solution Summary", entry.solution_summary])
        if entry.final_answer is not None:
            lines.extend(["", f"- final_answer: `{entry.final_answer}`"])
        lines.extend(
            [
                "",
                "### Review Label",
                f"- decision: `{entry.review_label.decision.value}`",
                f"- reason_code: `{entry.review_label.reason_code}`",
                f"- difficulty_label: `{entry.review_label.difficulty_label.value if entry.review_label.difficulty_label else None}`",
                f"- wording_naturalness: `{entry.review_label.wording_naturalness}`",
                f"- distractor_quality: `{entry.review_label.distractor_quality}`",
                f"- curriculum_fit: `{entry.review_label.curriculum_fit}`",
                f"- notes: `{entry.review_label.notes}`",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def write_review_packet_jsonl(path: Path, entries: list[ReviewPacketEntry]) -> Path:
    """Persist export packet entries as JSONL."""

    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(entry.model_dump(mode="json"), ensure_ascii=False)
        for entry in entries
    ]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return path
