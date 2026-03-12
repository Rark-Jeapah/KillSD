"""Mini-alpha assembly workflow for a 10-item pilot exam."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import Field

from src.config.settings import get_settings
from src.core.schemas import (
    DifficultyBand,
    DraftItem,
    ItemBlueprint,
    ItemFormat,
    SolvedItem,
    StrictModel,
    ValidatedItem,
    utc_now,
)
from src.distill.fingerprint import normalize_text
from src.eval.discard_rate import (
    CandidateOutcome,
    CandidateOutcomeRecord,
    DiscardRateReport,
    HumanReviewDecision,
    HumanReviewRecord,
    build_discard_rate_report,
    write_discard_rate_report,
)
from src.plugins.csat_math_2028 import CSATMath2028Plugin
from src.render.contracts import RendererConfig
from src.render.latex_renderer import LaTeXRenderer, RenderJobResult
from src.validators import similarity_validator as sv
from src.validators.report import (
    DifficultyEstimate,
    SimilarityThresholdConfig,
    ValidatorSectionResult,
    ValidatorSuiteReport,
    load_similarity_thresholds,
)


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
DEFAULT_SCOPE_NOTE = (
    "대수, 미적분Ⅰ, 확률과 통계 범위 안에서 콘텐츠 품질과 폐기율을 측정하는 10문항 파일럿이다."
)
METADATA_LEAK_REASON = "format.internal_metadata_leak"


class MiniAlphaAssemblyError(Exception):
    """Raised when the mini-alpha bundle cannot be assembled safely."""


class MiniAlphaCandidateInput(StrictModel):
    """Filesystem-backed input record for one candidate."""

    candidate_id: str
    validated_item_path: str
    validator_report_path: str | None = None
    source_run_id: str | None = None
    source_item_id: str | None = None
    source_item_no: int | None = None
    atom_signatures: list[str] = Field(default_factory=list)
    distractor_signatures: list[str] = Field(default_factory=list)


class MiniAlphaManifestInput(StrictModel):
    """JSON manifest consumed by the runner script."""

    spec_id: str = "csat_math_2028"
    title: str = "CSAT Math Mini Alpha"
    candidates: list[MiniAlphaCandidateInput]


class MiniAlphaSlotSpec(StrictModel):
    """One target slot in the 10-item pilot blueprint."""

    slot_no: int
    sampled_from_item_no: int
    domain: str
    format: ItemFormat
    score: int
    difficulty: DifficultyBand
    objective: str
    skill_tags: list[str] = Field(default_factory=list)


class MiniAlphaCandidate(StrictModel):
    """Loaded candidate with resolved payloads and normalized signatures."""

    candidate_id: str
    source_run_id: str | None = None
    source_item_id: str | None = None
    source_item_no: int | None = None
    validated_item: ValidatedItem
    validator_report: ValidatorSuiteReport
    atom_signatures: list[str] = Field(default_factory=list)
    distractor_signatures: list[str] = Field(default_factory=list)


class MiniAlphaPairwiseSimilarity(StrictModel):
    """Pairwise collision details between two selected items."""

    left_candidate_id: str
    right_candidate_id: str
    left_item_no: int
    right_item_no: int
    surface_similarity: float
    expression_similarity: float
    solution_graph_similarity: float
    hard_collision: bool
    shared_atom_signatures: list[str] = Field(default_factory=list)
    shared_distractor_signatures: list[str] = Field(default_factory=list)


class MiniAlphaSelectionRecord(StrictModel):
    """Selected slot assignment with source provenance."""

    slot: MiniAlphaSlotSpec
    candidate_id: str
    source_item_no: int | None = None
    atom_signatures: list[str] = Field(default_factory=list)
    distractor_signatures: list[str] = Field(default_factory=list)


class MiniAlphaMetrics(StrictModel):
    """Release-gate and overlap metrics for the assembled mini-alpha bundle."""

    topic_coverage: dict[str, int]
    expected_topic_coverage: dict[str, int]
    difficulty_curve: list[str]
    expected_difficulty_curve: list[str]
    score_distribution: dict[int, int]
    expected_score_distribution: dict[int, int]
    structure_errors: int
    answer_errors: int
    metadata_leaks: int
    hard_similarity_collisions: int
    repeated_atom_signatures: dict[str, int] = Field(default_factory=dict)
    repeated_distractor_signatures: dict[str, int] = Field(default_factory=dict)
    pairwise_collisions: list[MiniAlphaPairwiseSimilarity] = Field(default_factory=list)


class MiniAlphaRenderBundle(StrictModel):
    """Bundle shape consumed by the existing LaTeX renderer."""

    bundle_id: str = Field(default_factory=lambda: f"mini-{uuid4().hex[:12]}")
    spec_id: str
    blueprint_id: str
    generated_at: Any = Field(default_factory=utc_now)
    items: list[ValidatedItem]
    student_metadata: dict[str, str] = Field(default_factory=dict)
    internal_metadata: dict[str, str] = Field(default_factory=dict)
    output_targets: list[str] = Field(default_factory=list)
    answer_key: dict[int, str]
    asset_refs: list[str] = Field(default_factory=list)


class MiniAlphaRegenerateCandidate(StrictModel):
    """Item flagged for follow-up regeneration after human review."""

    item_no: int
    candidate_id: str
    source_item_no: int | None = None
    decision: HumanReviewDecision
    reasons: list[str] = Field(default_factory=list)
    notes: str | None = None
    suggested_action: str
    atom_signatures: list[str] = Field(default_factory=list)
    distractor_signatures: list[str] = Field(default_factory=list)
    overlap_notes: list[str] = Field(default_factory=list)


class MiniAlphaAssemblyResult(StrictModel):
    """Materialized outputs and metrics for one mini-alpha run."""

    run_id: str
    output_dir: str
    review_packet_path: str
    human_review_template_path: str
    discard_rate_report_path: str
    regenerate_candidates_path: str
    bundle_json_path: str
    manifest_path: str
    render_result: RenderJobResult
    metrics: MiniAlphaMetrics
    discard_rate_report: DiscardRateReport
    selected: list[MiniAlphaSelectionRecord]


def _unique_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def _signature(value: str) -> str:
    tokens = re.findall(r"[0-9a-zA-Z가-힣]+", value.lower())
    return "_".join(tokens)


def _load_model(path: Path, model_type: type[Any]) -> Any:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "payload" in payload and "artifact_type" in payload:
        payload = payload["payload"]
    return model_type.model_validate(payload)


def _synthesize_validator_report(
    *, validated_item: ValidatedItem, spec_id: str
) -> ValidatorSuiteReport:
    blueprint = validated_item.solved.draft.blueprint
    solution_steps = validated_item.solved.solution_steps
    concept_count = max(1, len(set(blueprint.skill_tags)) or 1)
    branching_factor = round(len(solution_steps) / concept_count, 4)
    return ValidatorSuiteReport(
        spec_id=spec_id,
        item_no=blueprint.item_no,
        sections=[
            ValidatorSectionResult(
                validator_name="mini_alpha_fallback",
                findings=validated_item.validation.findings,
                metrics={"fallback": True},
            )
        ],
        difficulty_estimate=DifficultyEstimate(
            expected_step_count=len(solution_steps),
            concept_count=concept_count,
            branching_factor=branching_factor,
            solver_disagreement_score=0.0,
            predicted_band=blueprint.difficulty.value,
        ),
        final_report=validated_item.validation,
    )


def _infer_atom_signatures(validated_item: ValidatedItem) -> list[str]:
    blueprint = validated_item.solved.draft.blueprint
    return _unique_preserve_order(
        [_signature(tag) for tag in blueprint.skill_tags]
        + [_signature(blueprint.objective)]
    )


def _infer_distractor_signatures(validated_item: ValidatedItem) -> list[str]:
    solved = validated_item.solved
    if solved.draft.blueprint.format != ItemFormat.MULTIPLE_CHOICE:
        return []
    correct_index = solved.correct_choice_index
    distractors = [
        _signature(choice)
        for index, choice in enumerate(solved.draft.choices, start=1)
        if correct_index is None or index != correct_index
    ]
    return _unique_preserve_order(distractors)


def _metadata_hits(validated_item: ValidatedItem) -> list[str]:
    solved = validated_item.solved
    all_text = "\n".join(
        [
            solved.draft.stem,
            solved.draft.rubric,
            solved.solution_summary,
            *solved.draft.choices,
            *solved.solution_steps,
        ]
    ).lower()
    return [pattern for pattern in INTERNAL_METADATA_PATTERNS if pattern in all_text]


def _structure_error_count(report: ValidatorSuiteReport) -> int:
    count = 0
    for finding in report.final_report.findings:
        if finding.passed or finding.reason_code == METADATA_LEAK_REASON:
            continue
        if finding.reason_code.startswith(("format.", "curriculum.", "render.")):
            count += 1
    return count


def _answer_error_count(report: ValidatorSuiteReport) -> int:
    return sum(
        1
        for finding in report.final_report.findings
        if not finding.passed and finding.reason_code.startswith("answer.")
    )


def _metadata_leak_count(report: ValidatorSuiteReport) -> int:
    return sum(
        1
        for finding in report.final_report.findings
        if not finding.passed and finding.reason_code == METADATA_LEAK_REASON
    )


def _scaled_duration_minutes(total_items: int, full_exam_items: int, full_duration: int) -> int:
    scaled = full_duration * total_items / full_exam_items
    return int(math.ceil(scaled / 5.0) * 5)


def _sample_blueprints(spec: Any, sample_size: int = 10) -> list[MiniAlphaSlotSpec]:
    blueprints = spec.default_item_blueprints
    if sample_size > len(blueprints):
        raise MiniAlphaAssemblyError("mini-alpha sample_size cannot exceed the canonical blueprint size")

    last_index = len(blueprints) - 1
    sampled_indices: list[int] = []
    for slot_index in range(sample_size):
        raw_index = round(slot_index * last_index / max(sample_size - 1, 1))
        if sampled_indices and raw_index <= sampled_indices[-1]:
            raw_index = sampled_indices[-1] + 1
        sampled_indices.append(raw_index)

    slots: list[MiniAlphaSlotSpec] = []
    for slot_no, blueprint_index in enumerate(sampled_indices, start=1):
        blueprint = blueprints[blueprint_index]
        slots.append(
            MiniAlphaSlotSpec(
                slot_no=slot_no,
                sampled_from_item_no=blueprint.item_no,
                domain=blueprint.domain,
                format=blueprint.format,
                score=blueprint.score,
                difficulty=blueprint.difficulty,
                objective=blueprint.objective,
                skill_tags=blueprint.skill_tags,
            )
        )
    return slots


def _reindex_validated_item(validated_item: ValidatedItem, *, slot: MiniAlphaSlotSpec) -> ValidatedItem:
    solved = validated_item.solved
    blueprint = solved.draft.blueprint.model_copy(
        update={
            "item_no": slot.slot_no,
            "domain": slot.domain,
            "format": slot.format,
            "score": slot.score,
            "difficulty": slot.difficulty,
        }
    )
    draft = solved.draft.model_copy(update={"blueprint": blueprint})
    solved_item = solved.model_copy(update={"draft": draft})
    validation = validated_item.validation.model_copy(update={"item_no": slot.slot_no})
    return validated_item.model_copy(update={"solved": solved_item, "validation": validation})


def _reindex_validator_report(report: ValidatorSuiteReport, *, slot: MiniAlphaSlotSpec) -> ValidatorSuiteReport:
    final_report = report.final_report.model_copy(update={"item_no": slot.slot_no})
    return report.model_copy(update={"item_no": slot.slot_no, "final_report": final_report})


def _pairwise_similarity(
    left: MiniAlphaCandidate,
    right: MiniAlphaCandidate,
    *,
    thresholds: SimilarityThresholdConfig,
) -> MiniAlphaPairwiseSimilarity:
    left_solved = left.validated_item.solved
    right_solved = right.validated_item.solved
    left_stem = normalize_text(left_solved.draft.stem)
    right_stem = normalize_text(right_solved.draft.stem)
    surface = sv._sequence_similarity(left_stem, right_stem)

    left_expr = sv._expression_signature(
        " ".join([left_solved.draft.stem, " ".join(left_solved.draft.choices)])
    )
    right_expr = sv._expression_signature(
        " ".join([right_solved.draft.stem, " ".join(right_solved.draft.choices)])
    )
    expression = sv._sequence_similarity(left_expr, right_expr) if left_expr and right_expr else 0.0

    left_graph = sv._solution_graph_signature_from_item(left_solved)
    right_graph = sv._solution_graph_signature_from_item(right_solved)
    solution_graph = sv._jaccard(left_graph, right_graph)

    hard_collision = any(
        (
            surface >= thresholds.surface_hard_fail,
            expression >= thresholds.expression_hard_fail,
            solution_graph >= thresholds.solution_graph_hard_fail,
        )
    )
    left_item_no = left_solved.draft.blueprint.item_no
    right_item_no = right_solved.draft.blueprint.item_no
    return MiniAlphaPairwiseSimilarity(
        left_candidate_id=left.candidate_id,
        right_candidate_id=right.candidate_id,
        left_item_no=left_item_no,
        right_item_no=right_item_no,
        surface_similarity=round(surface, 4),
        expression_similarity=round(expression, 4),
        solution_graph_similarity=round(solution_graph, 4),
        hard_collision=hard_collision,
        shared_atom_signatures=sorted(set(left.atom_signatures) & set(right.atom_signatures)),
        shared_distractor_signatures=sorted(
            set(left.distractor_signatures) & set(right.distractor_signatures)
        ),
    )


def _overlap_penalty(
    candidate: MiniAlphaCandidate,
    selected: list[MiniAlphaCandidate],
    *,
    thresholds: SimilarityThresholdConfig,
    slot: MiniAlphaSlotSpec,
) -> tuple[int, bool]:
    penalty = abs((candidate.source_item_no or slot.sampled_from_item_no) - slot.sampled_from_item_no)
    for existing in selected:
        similarity = _pairwise_similarity(candidate, existing, thresholds=thresholds)
        if similarity.hard_collision:
            return 0, True
        penalty += len(similarity.shared_atom_signatures) * 20
        penalty += len(similarity.shared_distractor_signatures) * 14
        penalty += int(similarity.surface_similarity * 100)
        penalty += int(similarity.expression_similarity * 100)
        penalty += int(similarity.solution_graph_similarity * 100)
        if similarity.surface_similarity >= thresholds.surface_soft_fail:
            penalty += 40
        if similarity.expression_similarity >= thresholds.expression_soft_fail:
            penalty += 40
        if similarity.solution_graph_similarity >= thresholds.solution_graph_soft_fail:
            penalty += 40
    return penalty, False


def _review_packet_text(
    *,
    title: str,
    selections: list[MiniAlphaSelectionRecord],
    selected_candidates: list[MiniAlphaCandidate],
    metrics: MiniAlphaMetrics,
) -> str:
    candidate_by_id = {candidate.candidate_id: candidate for candidate in selected_candidates}
    pairwise_by_candidate: dict[str, list[MiniAlphaPairwiseSimilarity]] = {}
    for collision in metrics.pairwise_collisions:
        pairwise_by_candidate.setdefault(collision.left_candidate_id, []).append(collision)
        pairwise_by_candidate.setdefault(collision.right_candidate_id, []).append(collision)

    lines = [
        "# Mini Alpha Review Packet",
        "",
        "## 목표",
        "- 10문항 mini alpha의 콘텐츠 품질과 human review 폐기율을 측정한다.",
        "- 구조 오류 0 / 정답 오류 0 / metadata leak 0 / hard similarity collision 0를 유지한다.",
        "",
        "## 조립 요약",
        f"- title: `{title}`",
        f"- topic coverage: `{metrics.topic_coverage}`",
        f"- difficulty curve: `{metrics.difficulty_curve}`",
        f"- structure errors: `{metrics.structure_errors}`",
        f"- answer errors: `{metrics.answer_errors}`",
        f"- metadata leaks: `{metrics.metadata_leaks}`",
        f"- hard similarity collisions: `{metrics.hard_similarity_collisions}`",
    ]

    for record in selections:
        candidate = candidate_by_id[record.candidate_id]
        solved = candidate.validated_item.solved
        blueprint = solved.draft.blueprint
        lines.extend(
            [
                "",
                f"## Item {record.slot.slot_no}",
                f"- candidate_id: `{record.candidate_id}`",
                f"- source_item_no: `{record.source_item_no}`",
                f"- sampled_from_item_no: `{record.slot.sampled_from_item_no}`",
                f"- domain: `{record.slot.domain}`",
                f"- difficulty: `{record.slot.difficulty.value}`",
                f"- format: `{record.slot.format.value}`",
                f"- score: `{record.slot.score}`",
                f"- objective: `{blueprint.objective}`",
                f"- answer: `{solved.final_answer}`",
                "",
                "### Stem",
                solved.draft.stem,
            ]
        )
        if solved.draft.choices:
            lines.extend(["", "### Choices"])
            for index, choice in enumerate(solved.draft.choices, start=1):
                lines.append(f"{index}. {choice}")

        lines.extend(
            [
                "",
                "### Validation Summary",
                f"- status: `{candidate.validator_report.final_report.status.value}`",
                f"- recommendation: `{candidate.validator_report.final_report.regenerate_recommendation.value}`",
                f"- summary: {candidate.validator_report.final_report.summary}",
                "",
                "### Overlap Signals",
                f"- atom_signatures: `{record.atom_signatures}`",
                f"- distractor_signatures: `{record.distractor_signatures}`",
            ]
        )
        if pairwise_by_candidate.get(record.candidate_id):
            for overlap in pairwise_by_candidate[record.candidate_id]:
                other_id = (
                    overlap.right_candidate_id
                    if overlap.left_candidate_id == record.candidate_id
                    else overlap.left_candidate_id
                )
                lines.append(
                    "- pairwise_with="
                    f"`{other_id}` surface={overlap.surface_similarity} "
                    f"expression={overlap.expression_similarity} "
                    f"solution_graph={overlap.solution_graph_similarity}"
                )
        lines.extend(
            [
                "",
                "### Reviewer Decision",
                "- decision: `pending | accept | revise | discard`",
                "- reasons: `[]`",
                "- notes:",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def _write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _build_regenerate_candidates(
    *,
    selections: list[MiniAlphaSelectionRecord],
    selected_candidates: list[MiniAlphaCandidate],
    human_reviews: list[HumanReviewRecord],
    pairwise_collisions: list[MiniAlphaPairwiseSimilarity],
) -> list[MiniAlphaRegenerateCandidate]:
    selected_by_id = {candidate.candidate_id: candidate for candidate in selected_candidates}
    slot_by_candidate = {selection.candidate_id: selection for selection in selections}
    overlap_notes_by_candidate: dict[str, list[str]] = {}
    for collision in pairwise_collisions:
        note = (
            f"with {collision.right_candidate_id}: surface={collision.surface_similarity}, "
            f"expression={collision.expression_similarity}, "
            f"solution_graph={collision.solution_graph_similarity}"
        )
        overlap_notes_by_candidate.setdefault(collision.left_candidate_id, []).append(note)
        reverse_note = (
            f"with {collision.left_candidate_id}: surface={collision.surface_similarity}, "
            f"expression={collision.expression_similarity}, "
            f"solution_graph={collision.solution_graph_similarity}"
        )
        overlap_notes_by_candidate.setdefault(collision.right_candidate_id, []).append(reverse_note)

    regenerate: list[MiniAlphaRegenerateCandidate] = []
    for review in human_reviews:
        if review.decision not in {HumanReviewDecision.REVISE, HumanReviewDecision.DISCARD}:
            continue
        candidate = selected_by_id.get(review.candidate_id)
        selection = slot_by_candidate.get(review.candidate_id)
        if candidate is None or selection is None:
            continue
        regenerate.append(
            MiniAlphaRegenerateCandidate(
                item_no=review.item_no,
                candidate_id=review.candidate_id,
                source_item_no=selection.source_item_no,
                decision=review.decision,
                reasons=review.reasons,
                notes=review.notes,
                suggested_action="regenerate" if review.decision == HumanReviewDecision.DISCARD else "revise_or_regenerate",
                atom_signatures=selection.atom_signatures,
                distractor_signatures=selection.distractor_signatures,
                overlap_notes=overlap_notes_by_candidate.get(review.candidate_id, []),
            )
        )
    return sorted(
        regenerate,
        key=lambda item: (0 if item.decision == HumanReviewDecision.DISCARD else 1, item.item_no),
    )


class MiniAlphaAssembler:
    """Assemble a 10-item mini-alpha exam from validated candidates."""

    def __init__(
        self,
        *,
        template_dir: Path | None = None,
        similarity_thresholds: SimilarityThresholdConfig | None = None,
        xelatex_path: str | None = None,
    ) -> None:
        settings = get_settings()
        self.repo_root = settings.repo_root
        self.plugin = CSATMath2028Plugin()
        self.spec = self.plugin.load_exam_spec()
        self.template_dir = template_dir or (self.repo_root / "src" / "render" / "templates")
        self.thresholds = similarity_thresholds or load_similarity_thresholds(
            self.repo_root / "config" / "similarity_thresholds.json"
        )
        self.renderer = LaTeXRenderer(
            template_dir=self.template_dir,
            config=RendererConfig(xelatex_path=xelatex_path),
        )

    def load_manifest(self, path: Path) -> MiniAlphaManifestInput:
        """Load a candidate manifest from disk."""
        manifest = MiniAlphaManifestInput.model_validate(
            json.loads(path.read_text(encoding="utf-8"))
        )
        base_dir = path.parent
        return manifest.model_copy(
            update={
                "candidates": [
                    candidate.model_copy(
                        update={
                            "validated_item_path": str(
                                (base_dir / candidate.validated_item_path).resolve()
                            )
                            if not Path(candidate.validated_item_path).is_absolute()
                            else candidate.validated_item_path,
                            "validator_report_path": (
                                str((base_dir / candidate.validator_report_path).resolve())
                                if candidate.validator_report_path
                                and not Path(candidate.validator_report_path).is_absolute()
                                else candidate.validator_report_path
                            ),
                        }
                    )
                    for candidate in manifest.candidates
                ]
            }
        )

    def load_candidates(self, manifest: MiniAlphaManifestInput) -> list[MiniAlphaCandidate]:
        """Resolve candidate payloads from the manifest."""
        candidates: list[MiniAlphaCandidate] = []
        seen_candidate_ids: set[str] = set()
        for entry in manifest.candidates:
            if entry.candidate_id in seen_candidate_ids:
                raise MiniAlphaAssemblyError(f"Duplicate candidate_id in manifest: {entry.candidate_id}")
            seen_candidate_ids.add(entry.candidate_id)
            validated_item = _load_model(Path(entry.validated_item_path), ValidatedItem)
            validator_report = (
                _load_model(Path(entry.validator_report_path), ValidatorSuiteReport)
                if entry.validator_report_path
                else _synthesize_validator_report(validated_item=validated_item, spec_id=manifest.spec_id)
            )
            candidates.append(
                MiniAlphaCandidate(
                    candidate_id=entry.candidate_id,
                    source_run_id=entry.source_run_id,
                    source_item_id=entry.source_item_id,
                    source_item_no=entry.source_item_no
                    or validated_item.solved.draft.blueprint.item_no,
                    validated_item=validated_item,
                    validator_report=validator_report,
                    atom_signatures=_unique_preserve_order(
                        entry.atom_signatures + _infer_atom_signatures(validated_item)
                    ),
                    distractor_signatures=_unique_preserve_order(
                        entry.distractor_signatures + _infer_distractor_signatures(validated_item)
                    ),
                )
            )
        return candidates

    def verify_real_item_gate(self, path: Path) -> None:
        """Ensure the single-item gate has passed before bundle assembly."""
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and "payload" in payload and "artifact_type" in payload:
            payload = payload["payload"]
        status = payload.get("status")
        approval_status = payload.get("approval_status")
        item_id = payload.get("item_id")
        if item_id != "real_item_001" or status != "pass" or approval_status != "approved":
            raise MiniAlphaAssemblyError(
                "real_item_001 gate must be approved before mini-alpha assembly"
            )

    def _candidate_outcomes(
        self,
        candidates: list[MiniAlphaCandidate],
        slots: list[MiniAlphaSlotSpec],
    ) -> tuple[list[MiniAlphaCandidate], dict[str, CandidateOutcomeRecord]]:
        slot_keys = {
            (slot.domain, slot.difficulty.value, slot.format.value, slot.score)
            for slot in slots
        }
        clean_candidates: list[MiniAlphaCandidate] = []
        outcomes: dict[str, CandidateOutcomeRecord] = {}
        for candidate in candidates:
            blueprint = candidate.validated_item.solved.draft.blueprint
            reasons: list[str] = []
            if candidate.validated_item.approval_status.value != "approved":
                reasons.append("not_approved")
            if _structure_error_count(candidate.validator_report) > 0:
                reasons.append("structure_error")
            if _answer_error_count(candidate.validator_report) > 0:
                reasons.append("answer_error")
            if _metadata_leak_count(candidate.validator_report) > 0 or _metadata_hits(candidate.validated_item):
                reasons.append("metadata_leak")

            key = (blueprint.domain, blueprint.difficulty.value, blueprint.format.value, blueprint.score)
            if reasons:
                outcomes[candidate.candidate_id] = CandidateOutcomeRecord(
                    candidate_id=candidate.candidate_id,
                    source_item_no=candidate.source_item_no,
                    domain=blueprint.domain,
                    difficulty=blueprint.difficulty.value,
                    outcome=CandidateOutcome.AUTO_DISCARDED,
                    reasons=_unique_preserve_order(reasons),
                )
                continue
            if key not in slot_keys:
                outcomes[candidate.candidate_id] = CandidateOutcomeRecord(
                    candidate_id=candidate.candidate_id,
                    source_item_no=candidate.source_item_no,
                    domain=blueprint.domain,
                    difficulty=blueprint.difficulty.value,
                    outcome=CandidateOutcome.RESERVE,
                    reasons=["outside_mini_alpha_target_mix"],
                )
                continue
            outcomes[candidate.candidate_id] = CandidateOutcomeRecord(
                candidate_id=candidate.candidate_id,
                source_item_no=candidate.source_item_no,
                domain=blueprint.domain,
                difficulty=blueprint.difficulty.value,
                outcome=CandidateOutcome.RESERVE,
                reasons=["clean_pool_candidate"],
            )
            clean_candidates.append(candidate)
        return clean_candidates, outcomes

    def _select_candidates(
        self,
        *,
        slots: list[MiniAlphaSlotSpec],
        candidates: list[MiniAlphaCandidate],
    ) -> list[tuple[MiniAlphaSlotSpec, MiniAlphaCandidate]]:
        compatibility: dict[int, list[MiniAlphaCandidate]] = {}
        for slot in slots:
            compatible = [
                candidate
                for candidate in candidates
                if candidate.validated_item.solved.draft.blueprint.domain == slot.domain
                and candidate.validated_item.solved.draft.blueprint.difficulty == slot.difficulty
                and candidate.validated_item.solved.draft.blueprint.format == slot.format
                and candidate.validated_item.solved.draft.blueprint.score == slot.score
            ]
            if not compatible:
                raise MiniAlphaAssemblyError(
                    "No clean candidate matches "
                    f"slot={slot.slot_no} domain={slot.domain} difficulty={slot.difficulty.value} "
                    f"format={slot.format.value} score={slot.score}"
                )
            compatibility[slot.slot_no] = compatible

        search_slots = sorted(slots, key=lambda slot: (len(compatibility[slot.slot_no]), slot.slot_no))
        best_assignment: dict[int, MiniAlphaCandidate] | None = None
        best_penalty: int | None = None

        def dfs(
            *,
            index: int,
            chosen: dict[int, MiniAlphaCandidate],
            used_ids: set[str],
            penalty: int,
        ) -> None:
            nonlocal best_assignment, best_penalty
            if best_penalty is not None and penalty >= best_penalty:
                return
            if index == len(search_slots):
                best_assignment = dict(chosen)
                best_penalty = penalty
                return

            slot = search_slots[index]
            selected_candidates = list(chosen.values())
            ranked = sorted(
                compatibility[slot.slot_no],
                key=lambda candidate: (
                    _overlap_penalty(
                        candidate,
                        selected_candidates,
                        thresholds=self.thresholds,
                        slot=slot,
                    )[0],
                    abs((candidate.source_item_no or slot.sampled_from_item_no) - slot.sampled_from_item_no),
                    candidate.candidate_id,
                ),
            )
            for candidate in ranked:
                if candidate.candidate_id in used_ids:
                    continue
                overlap_penalty, hard_collision = _overlap_penalty(
                    candidate,
                    selected_candidates,
                    thresholds=self.thresholds,
                    slot=slot,
                )
                if hard_collision:
                    continue
                chosen[slot.slot_no] = candidate
                used_ids.add(candidate.candidate_id)
                dfs(index=index + 1, chosen=chosen, used_ids=used_ids, penalty=penalty + overlap_penalty)
                used_ids.remove(candidate.candidate_id)
                chosen.pop(slot.slot_no, None)

        dfs(index=0, chosen={}, used_ids=set(), penalty=0)
        if best_assignment is None:
            raise MiniAlphaAssemblyError("Unable to find a 10-item assignment without hard collisions")
        return [(slot, best_assignment[slot.slot_no]) for slot in sorted(slots, key=lambda item: item.slot_no)]

    def _metrics(
        self,
        *,
        slots: list[MiniAlphaSlotSpec],
        selected_candidates: list[MiniAlphaCandidate],
        selected_reports: list[ValidatorSuiteReport],
    ) -> MiniAlphaMetrics:
        expected_topic_coverage = Counter(slot.domain for slot in slots)
        expected_difficulty_curve = [slot.difficulty.value for slot in slots]
        expected_score_distribution = Counter(slot.score for slot in slots)

        actual_topic_coverage = Counter(
            candidate.validated_item.solved.draft.blueprint.domain
            for candidate in selected_candidates
        )
        actual_difficulty_curve = [
            candidate.validated_item.solved.draft.blueprint.difficulty.value
            for candidate in selected_candidates
        ]
        actual_score_distribution = Counter(
            candidate.validated_item.solved.draft.blueprint.score
            for candidate in selected_candidates
        )

        pairwise_collisions: list[MiniAlphaPairwiseSimilarity] = []
        atom_counts: Counter[str] = Counter()
        distractor_counts: Counter[str] = Counter()
        for candidate in selected_candidates:
            atom_counts.update(candidate.atom_signatures)
            distractor_counts.update(candidate.distractor_signatures)
        for index, left in enumerate(selected_candidates):
            for right in selected_candidates[index + 1 :]:
                pairwise_collisions.append(
                    _pairwise_similarity(left, right, thresholds=self.thresholds)
                )

        return MiniAlphaMetrics(
            topic_coverage=dict(actual_topic_coverage),
            expected_topic_coverage=dict(expected_topic_coverage),
            difficulty_curve=actual_difficulty_curve,
            expected_difficulty_curve=expected_difficulty_curve,
            score_distribution=dict(actual_score_distribution),
            expected_score_distribution=dict(expected_score_distribution),
            structure_errors=sum(_structure_error_count(report) for report in selected_reports),
            answer_errors=sum(_answer_error_count(report) for report in selected_reports),
            metadata_leaks=sum(_metadata_leak_count(report) for report in selected_reports),
            hard_similarity_collisions=sum(1 for item in pairwise_collisions if item.hard_collision),
            repeated_atom_signatures={
                signature: count for signature, count in atom_counts.items() if count > 1
            },
            repeated_distractor_signatures={
                signature: count for signature, count in distractor_counts.items() if count > 1
            },
            pairwise_collisions=pairwise_collisions,
        )

    def assemble(
        self,
        *,
        run_id: str,
        manifest: MiniAlphaManifestInput,
        output_dir: Path,
        compile_pdf: bool = True,
        real_item_validation_path: Path | None = None,
        human_reviews: list[HumanReviewRecord] | None = None,
    ) -> MiniAlphaAssemblyResult:
        """Assemble the bundle, render outputs, and write review/discard artifacts."""
        if manifest.spec_id != self.spec.spec_id:
            raise MiniAlphaAssemblyError(
                f"Manifest spec_id={manifest.spec_id} does not match plugin spec_id={self.spec.spec_id}"
            )
        if real_item_validation_path is not None:
            self.verify_real_item_gate(real_item_validation_path)

        output_dir.mkdir(parents=True, exist_ok=True)
        slots = _sample_blueprints(self.spec, sample_size=10)
        candidates = self.load_candidates(manifest)
        clean_candidates, outcome_map = self._candidate_outcomes(candidates, slots)
        selected_pairs = self._select_candidates(slots=slots, candidates=clean_candidates)

        selections: list[MiniAlphaSelectionRecord] = []
        selected_candidates: list[MiniAlphaCandidate] = []
        reindexed_items: list[ValidatedItem] = []
        reindexed_reports: list[ValidatorSuiteReport] = []
        for slot, candidate in selected_pairs:
            outcome_map[candidate.candidate_id] = CandidateOutcomeRecord(
                candidate_id=candidate.candidate_id,
                source_item_no=candidate.source_item_no,
                target_item_no=slot.slot_no,
                domain=slot.domain,
                difficulty=slot.difficulty.value,
                outcome=CandidateOutcome.SELECTED,
                reasons=["selected_for_bundle"],
            )
            selected_candidates.append(candidate)
            reindexed_items.append(_reindex_validated_item(candidate.validated_item, slot=slot))
            reindexed_reports.append(_reindex_validator_report(candidate.validator_report, slot=slot))
            selections.append(
                MiniAlphaSelectionRecord(
                    slot=slot,
                    candidate_id=candidate.candidate_id,
                    source_item_no=candidate.source_item_no,
                    atom_signatures=candidate.atom_signatures,
                    distractor_signatures=candidate.distractor_signatures,
                )
            )

        metrics = self._metrics(
            slots=slots,
            selected_candidates=selected_candidates,
            selected_reports=reindexed_reports,
        )
        if metrics.structure_errors or metrics.answer_errors or metrics.metadata_leaks or metrics.hard_similarity_collisions:
            raise MiniAlphaAssemblyError(
                "Mini-alpha release gates failed: "
                f"struct={metrics.structure_errors}, answer={metrics.answer_errors}, "
                f"metadata={metrics.metadata_leaks}, hard_similarity={metrics.hard_similarity_collisions}"
            )

        first_short_slot = next(
            (slot.slot_no for slot in slots if slot.format == ItemFormat.SHORT_ANSWER),
            None,
        )
        if first_short_slot is None:
            composition_note = f"1번부터 {len(slots)}번까지는 5지선다형이다."
        elif first_short_slot == 1:
            composition_note = f"1번부터 {len(slots)}번까지는 단답형이다."
        else:
            composition_note = (
                f"1번부터 {first_short_slot - 1}번까지는 5지선다형, "
                f"{first_short_slot}번부터 {len(slots)}번까지는 단답형이다."
            )

        bundle = MiniAlphaRenderBundle(
            spec_id=self.spec.spec_id,
            blueprint_id=f"mini-alpha-{run_id}",
            items=reindexed_items,
            student_metadata={
                "title": manifest.title,
                "duration_minutes": str(
                    _scaled_duration_minutes(
                        total_items=len(slots),
                        full_exam_items=self.spec.total_items,
                        full_duration=self.spec.duration_minutes,
                    )
                ),
                "total_score": str(sum(slot.score for slot in slots)),
                "composition_note": composition_note,
                "scope_note": DEFAULT_SCOPE_NOTE,
            },
            internal_metadata={
                "slot_sampled_from": json.dumps(
                    {slot.slot_no: slot.sampled_from_item_no for slot in slots},
                    ensure_ascii=False,
                ),
                "topic_coverage": json.dumps(metrics.topic_coverage, ensure_ascii=False),
                "difficulty_curve": ",".join(metrics.difficulty_curve),
                "score_distribution": json.dumps(metrics.score_distribution, ensure_ascii=False),
            },
            output_targets=["exam_pdf", "answer_key_pdf", "validation_report_pdf"],
            answer_key={
                item.solved.draft.blueprint.item_no: item.solved.final_answer
                for item in reindexed_items
            },
        )
        render_result = self.renderer.render_exam_set(
            run_id=run_id,
            bundle=bundle,
            bundle_artifact_id=bundle.bundle_id,
            validator_reports=reindexed_reports,
            validator_suite_artifact_ids=[],
            output_dir=output_dir,
            compile_pdf=compile_pdf,
        )

        review_packet_path = output_dir / "review_packet.md"
        review_packet_path.write_text(
            _review_packet_text(
                title=manifest.title,
                selections=selections,
                selected_candidates=selected_candidates,
                metrics=metrics,
            ),
            encoding="utf-8",
        )

        merged_human_reviews: list[HumanReviewRecord] = [
            HumanReviewRecord(item_no=selection.slot.slot_no, candidate_id=selection.candidate_id)
            for selection in selections
        ]
        if human_reviews is not None:
            overrides = {
                (review.item_no, review.candidate_id): review
                for review in human_reviews
            }
            merged_human_reviews = [
                overrides.get((review.item_no, review.candidate_id), review)
                for review in merged_human_reviews
            ]
        human_reviews = merged_human_reviews
        human_review_template_path = output_dir / "human_review_template.json"
        _write_json(
            human_review_template_path,
            [review.model_dump(mode="json") for review in human_reviews],
        )

        discard_rate_report = build_discard_rate_report(
            outcomes=sorted(outcome_map.values(), key=lambda item: item.candidate_id),
            human_reviews=human_reviews,
        )
        discard_rate_report_path = write_discard_rate_report(
            output_dir / "discard_rate_report.json",
            discard_rate_report,
        )

        regenerate_candidates = _build_regenerate_candidates(
            selections=selections,
            selected_candidates=selected_candidates,
            human_reviews=human_reviews,
            pairwise_collisions=metrics.pairwise_collisions,
        )
        regenerate_candidates_path = _write_json(
            output_dir / "regenerate_candidates.json",
            [candidate.model_dump(mode="json") for candidate in regenerate_candidates],
        )
        bundle_json_path = _write_json(
            output_dir / "mini_alpha_bundle.json",
            bundle.model_dump(mode="json"),
        )

        result = MiniAlphaAssemblyResult(
            run_id=run_id,
            output_dir=str(output_dir),
            review_packet_path=str(review_packet_path),
            human_review_template_path=str(human_review_template_path),
            discard_rate_report_path=str(discard_rate_report_path),
            regenerate_candidates_path=str(regenerate_candidates_path),
            bundle_json_path=str(bundle_json_path),
            manifest_path=str(output_dir / "mini_alpha_manifest.json"),
            render_result=render_result,
            metrics=metrics,
            discard_rate_report=discard_rate_report,
            selected=selections,
        )
        _write_json(Path(result.manifest_path), result.model_dump(mode="json"))
        return result
