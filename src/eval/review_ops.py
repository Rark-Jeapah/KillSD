"""Review packet export/import helpers for candidate pools and generated exams."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.assembly.candidate_pool import CandidatePoolBuildResult, CandidatePoolCandidateBundle
from src.assembly.mini_alpha import (
    MiniAlphaAssemblyResult,
    MiniAlphaManifestInput,
    MiniAlphaSelectionRecord,
    build_regenerate_candidates,
)
from src.core.schemas import ApprovalStatus, StrictModel, ValidationStatus, ValidatedItem
from src.eval.discard_rate import (
    CandidateOutcomeRecord,
    build_discard_rate_report,
    write_discard_rate_report,
)
from src.eval.review_feedback import (
    CandidateReviewSummary,
    HumanReviewRecord,
    ReviewCandidateContext,
    ReviewPacketEntry,
    build_candidate_review_summaries,
    build_review_feedback_report,
    build_review_packet_markdown,
    load_human_review_records,
    merge_human_review_records,
    write_human_review_records_jsonl,
    write_review_packet_jsonl,
)


class ReviewExportResult(StrictModel):
    """Paths created by review packet export."""

    source_kind: str
    title: str
    item_count: int
    jsonl_path: str
    markdown_path: str


class ReviewImportResult(StrictModel):
    """Artifacts updated by review import."""

    source_kind: str
    title: str
    imported_count: int
    stored_label_count: int
    review_labels_path: str
    review_feedback_report_path: str | None = None
    discard_report_path: str | None = None
    regenerate_candidates_path: str | None = None


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, StrictModel):
        path.write_text(payload.model_dump_json(indent=2), encoding="utf-8")
    else:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _load_model(path: Path, model_type: type[Any]) -> Any:
    payload = _read_json(path)
    if isinstance(payload, dict) and "payload" in payload and "artifact_type" in payload:
        payload = payload["payload"]
    return model_type.model_validate(payload)


def _candidate_is_eligible(bundle: CandidatePoolCandidateBundle) -> bool:
    summary = bundle.review_summary
    return (
        bundle.approval_status == ApprovalStatus.APPROVED
        and bundle.validation_status == ValidationStatus.PASS
        and not (summary and summary.blocked_from_selection)
    )


def _bundle_sort_key(bundle: CandidatePoolCandidateBundle) -> tuple[int, str, str]:
    return (bundle.source_item_no or 10**9, bundle.family_id, bundle.candidate_id)


def _review_context_from_bundle(bundle: CandidatePoolCandidateBundle) -> ReviewCandidateContext:
    validated_item = _load_model(Path(bundle.validated_item_path), ValidatedItem)
    solved = validated_item.solved
    return ReviewCandidateContext(
        candidate_id=bundle.candidate_id,
        item_no=bundle.source_item_no,
        source_atom_id=bundle.source_atom_id,
        family_id=bundle.family_id,
        source_item_id=bundle.source_item_id,
        source_item_no=bundle.source_item_no,
        domain=bundle.domain,
        difficulty=bundle.difficulty,
        format=bundle.format.value,
        score=bundle.score,
        objective=bundle.objective,
        skill_tags=bundle.skill_tags,
        stem=solved.draft.stem,
        choices=solved.draft.choices,
        final_answer=solved.final_answer,
        solution_summary=solved.solution_summary,
        validated_item_path=bundle.validated_item_path,
        validator_report_path=bundle.validator_report_path,
        review_sheet_path=bundle.review_sheet_path,
        item_pdf_path=bundle.item_pdf_path,
        review_summary=bundle.review_summary,
    )


def _default_review_label(context: ReviewCandidateContext) -> HumanReviewRecord:
    summary = context.review_summary
    if summary is not None and summary.latest_review is not None:
        return summary.latest_review.model_copy(
            update={"candidate_id": context.candidate_id, "item_no": context.item_no}
        )
    return HumanReviewRecord(candidate_id=context.candidate_id, item_no=context.item_no)


def _packet_entries(
    *,
    contexts: list[ReviewCandidateContext],
) -> list[ReviewPacketEntry]:
    return [
        ReviewPacketEntry(
            **context.model_dump(mode="json"),
            review_label=_default_review_label(context),
        )
        for context in contexts
    ]


def _candidate_pool_manifest_path(candidate_pool_dir: Path) -> Path:
    return candidate_pool_dir / "candidate_pool_manifest.json"


def _candidate_pool_review_labels_path(candidate_pool_dir: Path) -> Path:
    return candidate_pool_dir / "review_labels.jsonl"


def _candidate_pool_feedback_report_path(candidate_pool_dir: Path) -> Path:
    return candidate_pool_dir / "review_feedback_report.json"


def load_candidate_pool_bundles(candidate_pool_dir: Path) -> tuple[str, list[CandidatePoolCandidateBundle]]:
    manifest_path = _candidate_pool_manifest_path(candidate_pool_dir)
    if manifest_path.exists():
        manifest = CandidatePoolBuildResult.model_validate(_read_json(manifest_path))
        return manifest.title, list(manifest.candidates)
    bundle_paths = sorted(
        candidate_pool_dir.glob("candidates/*/candidate_bundle.json"),
        key=lambda path: path.as_posix(),
    )
    bundles = [
        CandidatePoolCandidateBundle.model_validate(_read_json(path))
        for path in bundle_paths
    ]
    return candidate_pool_dir.name, bundles


def load_candidate_pool_review_contexts(candidate_pool_dir: Path) -> tuple[str, list[ReviewCandidateContext]]:
    title, bundles = load_candidate_pool_bundles(candidate_pool_dir)
    contexts = [_review_context_from_bundle(bundle) for bundle in sorted(bundles, key=_bundle_sort_key)]
    return title, contexts


def export_candidate_pool_review_packet(
    *,
    candidate_pool_dir: Path,
    output_dir: Path,
) -> ReviewExportResult:
    title, contexts = load_candidate_pool_review_contexts(candidate_pool_dir)
    entries = _packet_entries(contexts=contexts)
    jsonl_path = write_review_packet_jsonl(output_dir / "review_packet.jsonl", entries)
    output_dir.mkdir(parents=True, exist_ok=True)
    packet_md_path = output_dir / "review_packet.md"
    packet_md_path.write_text(
        build_review_packet_markdown(title=title, entries=entries),
        encoding="utf-8",
    )
    return ReviewExportResult(
        source_kind="candidate_pool",
        title=title,
        item_count=len(entries),
        jsonl_path=str(jsonl_path),
        markdown_path=str(packet_md_path),
    )


def _candidate_manifest_bundle_path(
    *,
    candidate_manifest_dir: Path,
    validated_item_path: str,
) -> Path | None:
    resolved_validated_path = Path(validated_item_path)
    if not resolved_validated_path.is_absolute():
        resolved_validated_path = (candidate_manifest_dir / resolved_validated_path).resolve()
    bundle_path = resolved_validated_path.parent / "candidate_bundle.json"
    return bundle_path if bundle_path.exists() else None


def _review_context_from_manifest_candidate(
    *,
    candidate_manifest_dir: Path,
    candidate_input: Any,
    selection: MiniAlphaSelectionRecord | None = None,
) -> ReviewCandidateContext:
    bundle_path = _candidate_manifest_bundle_path(
        candidate_manifest_dir=candidate_manifest_dir,
        validated_item_path=candidate_input.validated_item_path,
    )
    if bundle_path is not None:
        bundle = CandidatePoolCandidateBundle.model_validate(_read_json(bundle_path))
        context = _review_context_from_bundle(bundle)
    else:
        validated_item = _load_model(
            (candidate_manifest_dir / candidate_input.validated_item_path).resolve()
            if not Path(candidate_input.validated_item_path).is_absolute()
            else Path(candidate_input.validated_item_path),
            ValidatedItem,
        )
        solved = validated_item.solved
        context = ReviewCandidateContext(
            candidate_id=candidate_input.candidate_id,
            source_atom_id=candidate_input.source_atom_id,
            family_id=candidate_input.family_id,
            source_item_id=candidate_input.source_item_id,
            source_item_no=candidate_input.source_item_no,
            domain=solved.draft.blueprint.domain,
            difficulty=solved.draft.blueprint.difficulty.value,
            format=solved.draft.blueprint.format.value,
            score=solved.draft.blueprint.score,
            objective=solved.draft.blueprint.objective,
            skill_tags=solved.draft.blueprint.skill_tags,
            stem=solved.draft.stem,
            choices=solved.draft.choices,
            final_answer=solved.final_answer,
            solution_summary=solved.solution_summary,
            validated_item_path=str(
                (candidate_manifest_dir / candidate_input.validated_item_path).resolve()
                if not Path(candidate_input.validated_item_path).is_absolute()
                else Path(candidate_input.validated_item_path)
            ),
            validator_report_path=str(
                (candidate_manifest_dir / candidate_input.validator_report_path).resolve()
                if candidate_input.validator_report_path
                and not Path(candidate_input.validator_report_path).is_absolute()
                else candidate_input.validator_report_path
            )
            if candidate_input.validator_report_path
            else None,
            review_summary=candidate_input.review_summary,
        )
    if selection is not None:
        context = context.model_copy(update={"item_no": selection.slot.slot_no})
    return context


def load_generated_exam_review_contexts(output_dir: Path) -> tuple[str, list[ReviewCandidateContext]]:
    candidate_manifest_path = output_dir / "candidate_manifest.json"
    result_manifest_path = output_dir / "mini_alpha_manifest.json"
    candidate_manifest = MiniAlphaManifestInput.model_validate(_read_json(candidate_manifest_path))
    result_manifest = MiniAlphaAssemblyResult.model_validate(_read_json(result_manifest_path))
    candidate_by_id = {candidate.candidate_id: candidate for candidate in candidate_manifest.candidates}
    contexts = [
        _review_context_from_manifest_candidate(
            candidate_manifest_dir=candidate_manifest_path.parent,
            candidate_input=candidate_by_id[selection.candidate_id],
            selection=selection,
        )
        for selection in result_manifest.selected
        if selection.candidate_id in candidate_by_id
    ]
    title = candidate_manifest.title
    return title, contexts


def export_generated_exam_review_packet(
    *,
    output_dir: Path,
    packet_dir: Path,
) -> ReviewExportResult:
    title, contexts = load_generated_exam_review_contexts(output_dir)
    entries = _packet_entries(contexts=contexts)
    jsonl_path = write_review_packet_jsonl(packet_dir / "review_packet.jsonl", entries)
    packet_dir.mkdir(parents=True, exist_ok=True)
    packet_md_path = packet_dir / "review_packet.md"
    packet_md_path.write_text(
        build_review_packet_markdown(title=title, entries=entries),
        encoding="utf-8",
    )
    return ReviewExportResult(
        source_kind="generated_exam",
        title=title,
        item_count=len(entries),
        jsonl_path=str(jsonl_path),
        markdown_path=str(packet_md_path),
    )


def sync_candidate_pool_reviews(
    *,
    candidate_pool_dir: Path,
    incoming_reviews: list[HumanReviewRecord],
) -> ReviewImportResult:
    title, bundles = load_candidate_pool_bundles(candidate_pool_dir)
    review_labels_path = _candidate_pool_review_labels_path(candidate_pool_dir)
    existing_reviews = (
        load_human_review_records(review_labels_path) if review_labels_path.exists() else []
    )
    merged_reviews = merge_human_review_records(existing_reviews, incoming_reviews)
    write_human_review_records_jsonl(review_labels_path, merged_reviews)
    summaries = build_candidate_review_summaries(merged_reviews)

    updated_bundles: list[CandidatePoolCandidateBundle] = []
    for bundle in sorted(bundles, key=_bundle_sort_key):
        updated = bundle.model_copy(update={"review_summary": summaries.get(bundle.candidate_id)})
        _write_json(Path(updated.candidate_dir) / "candidate_bundle.json", updated)
        updated_bundles.append(updated)

    manifest_path = _candidate_pool_manifest_path(candidate_pool_dir)
    if manifest_path.exists():
        manifest = CandidatePoolBuildResult.model_validate(_read_json(manifest_path))
        manifest = manifest.model_copy(
            update={
                "candidates": updated_bundles,
                "eligible_candidate_count": sum(
                    1 for bundle in updated_bundles if _candidate_is_eligible(bundle)
                ),
            }
        )
        _write_json(manifest_path, manifest)
        if manifest.mini_alpha_manifest_path:
            mini_alpha_manifest_path = Path(manifest.mini_alpha_manifest_path)
            mini_alpha_manifest = MiniAlphaManifestInput.model_validate(_read_json(mini_alpha_manifest_path))
            mini_alpha_manifest = mini_alpha_manifest.model_copy(
                update={
                    "candidates": [
                        candidate.model_copy(update={"review_summary": summaries.get(candidate.candidate_id)})
                        for candidate in mini_alpha_manifest.candidates
                    ]
                }
            )
            _write_json(mini_alpha_manifest_path, mini_alpha_manifest)

    contexts = [_review_context_from_bundle(bundle) for bundle in updated_bundles]
    feedback_report = build_review_feedback_report(candidates=contexts, human_reviews=merged_reviews)
    feedback_report_path = _write_json(
        _candidate_pool_feedback_report_path(candidate_pool_dir),
        feedback_report,
    )
    return ReviewImportResult(
        source_kind="candidate_pool",
        title=title,
        imported_count=sum(1 for review in incoming_reviews if review.actionable),
        stored_label_count=len(merged_reviews),
        review_labels_path=str(review_labels_path),
        review_feedback_report_path=str(feedback_report_path),
    )


def _selection_reviews(
    *,
    selections: list[MiniAlphaSelectionRecord],
    summaries: dict[str, CandidateReviewSummary],
) -> list[HumanReviewRecord]:
    selected_reviews: list[HumanReviewRecord] = []
    for selection in selections:
        summary = summaries.get(selection.candidate_id)
        if summary is not None and summary.latest_review is not None and summary.latest_review.actionable:
            selected_reviews.append(
                summary.latest_review.model_copy(update={"item_no": selection.slot.slot_no})
            )
            continue
        selected_reviews.append(
            HumanReviewRecord(
                item_no=selection.slot.slot_no,
                candidate_id=selection.candidate_id,
            )
        )
    return selected_reviews


def sync_generated_exam_reviews(
    *,
    output_dir: Path,
    incoming_reviews: list[HumanReviewRecord],
) -> ReviewImportResult:
    candidate_manifest_path = output_dir / "candidate_manifest.json"
    result_manifest_path = output_dir / "mini_alpha_manifest.json"
    candidate_outcomes_path = output_dir / "candidate_outcomes.json"
    review_labels_path = output_dir / "review_labels.jsonl"

    candidate_manifest = MiniAlphaManifestInput.model_validate(_read_json(candidate_manifest_path))
    result_manifest = MiniAlphaAssemblyResult.model_validate(_read_json(result_manifest_path))
    existing_reviews = (
        load_human_review_records(review_labels_path) if review_labels_path.exists() else []
    )
    merged_exam_reviews = merge_human_review_records(existing_reviews, incoming_reviews)
    write_human_review_records_jsonl(review_labels_path, merged_exam_reviews)

    pool_dirs: dict[Path, set[str]] = {}
    for candidate in candidate_manifest.candidates:
        bundle_path = _candidate_manifest_bundle_path(
            candidate_manifest_dir=candidate_manifest_path.parent,
            validated_item_path=candidate.validated_item_path,
        )
        if bundle_path is None:
            continue
        candidate_pool_dir = bundle_path.parent.parent.parent
        if (candidate_pool_dir / "candidate_pool_manifest.json").exists():
            pool_dirs.setdefault(candidate_pool_dir, set()).add(candidate.candidate_id)

    for pool_dir, candidate_ids in pool_dirs.items():
        pool_reviews = [
            review for review in merged_exam_reviews if review.candidate_id in candidate_ids
        ]
        sync_candidate_pool_reviews(candidate_pool_dir=pool_dir, incoming_reviews=pool_reviews)

    refreshed_contexts: list[ReviewCandidateContext] = []
    for candidate in candidate_manifest.candidates:
        selection = next(
            (record for record in result_manifest.selected if record.candidate_id == candidate.candidate_id),
            None,
        )
        refreshed_contexts.append(
            _review_context_from_manifest_candidate(
                candidate_manifest_dir=candidate_manifest_path.parent,
                candidate_input=candidate,
                selection=selection,
            )
        )

    summaries = build_candidate_review_summaries(merged_exam_reviews)
    summaries.update(
        {
            context.candidate_id: context.review_summary
            for context in refreshed_contexts
            if context.review_summary is not None
        }
    )
    candidate_manifest = candidate_manifest.model_copy(
        update={
            "candidates": [
                candidate.model_copy(update={"review_summary": summaries.get(candidate.candidate_id)})
                for candidate in candidate_manifest.candidates
            ]
        }
    )
    _write_json(candidate_manifest_path, candidate_manifest)

    selected_reviews = _selection_reviews(
        selections=result_manifest.selected,
        summaries=summaries,
    )
    _write_json(
        output_dir / "human_review_template.json",
        [review.model_dump(mode="json") for review in selected_reviews],
    )

    candidate_outcomes = [
        CandidateOutcomeRecord.model_validate(payload)
        for payload in _read_json(candidate_outcomes_path)
    ]
    discard_report = build_discard_rate_report(
        outcomes=candidate_outcomes,
        human_reviews=selected_reviews,
    )
    discard_report_path = write_discard_rate_report(
        output_dir / "discard_report.json",
        discard_report,
    )
    legacy_discard_report_path = output_dir / "discard_rate_report.json"
    if legacy_discard_report_path != Path(discard_report_path):
        write_discard_rate_report(legacy_discard_report_path, discard_report)
    regenerate_candidates = build_regenerate_candidates(
        selections=result_manifest.selected,
        human_reviews=selected_reviews,
        pairwise_collisions=result_manifest.metrics.pairwise_collisions,
    )
    regenerate_candidates_path = _write_json(
        output_dir / "regenerate_candidates.json",
        [candidate.model_dump(mode="json") for candidate in regenerate_candidates],
    )

    feedback_report = build_review_feedback_report(
        candidates=refreshed_contexts,
        human_reviews=selected_reviews,
    )
    feedback_report_path = _write_json(
        output_dir / "review_feedback_report.json",
        feedback_report,
    )
    result_manifest = result_manifest.model_copy(update={"discard_rate_report": discard_report})
    _write_json(result_manifest_path, result_manifest)

    return ReviewImportResult(
        source_kind="generated_exam",
        title=candidate_manifest.title,
        imported_count=sum(1 for review in incoming_reviews if review.actionable),
        stored_label_count=len(merged_exam_reviews),
        review_labels_path=str(review_labels_path),
        review_feedback_report_path=str(feedback_report_path),
        discard_report_path=str(discard_report_path),
        regenerate_candidates_path=str(regenerate_candidates_path),
    )
