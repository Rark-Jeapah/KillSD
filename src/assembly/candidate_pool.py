"""Build a generated candidate pool that can feed the mini-alpha assembler."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import Field

from src.assembly.mini_alpha import (
    MiniAlphaCandidateInput,
    MiniAlphaManifestInput,
    MiniAlphaSlotSpec,
)
from src.config.settings import get_settings
from src.core.schemas import (
    ApprovalStatus,
    ExamMode,
    ItemFormat,
    StrictModel,
    ValidationStatus,
    ValidatedItem,
    utc_now,
)
from src.core.storage import ArtifactStore
from src.distill.atom_extractor import InsightAtom
from src.distill.curated_batch import LoadedCuratedBatch
from src.distill.pipeline import DistillPipeline
from src.eval.review_feedback import (
    CandidateReviewSummary,
    candidate_blocked_from_selection,
)
from src.orchestrator.real_item_gauntlet import (
    RealItemGauntlet,
    RealItemValidationArtifact,
)
from src.orchestrator.real_item_families import RealItemFamilySelectionError
from src.orchestrator.state_machine import RunStatus
from src.providers.base import BaseProvider
from src.providers.real_item_runtime import RealItemProviderConfig
from src.validators.report import ValidatorSuiteReport


class CandidatePoolBuildError(RuntimeError):
    """Raised when the generated candidate pool cannot satisfy mini-alpha needs."""


class CandidatePoolCandidateBundle(StrictModel):
    """Persisted metadata for one generated candidate bundle."""

    candidate_id: str
    run_id: str
    gauntlet_status: str
    source_atom_id: str
    family_id: str
    source_item_id: str | None = None
    source_item_no: int | None = None
    domain: str
    difficulty: str
    format: ItemFormat
    score: int
    objective: str
    skill_tags: list[str] = Field(default_factory=list)
    approval_status: ApprovalStatus
    validation_status: ValidationStatus
    atom_signatures: list[str] = Field(default_factory=list)
    distractor_signatures: list[str] = Field(default_factory=list)
    candidate_dir: str
    validated_item_path: str
    validator_report_path: str
    gauntlet_validation_path: str | None = None
    bundle_dir: str | None = None
    item_json_path: str | None = None
    solution_json_path: str | None = None
    review_sheet_path: str | None = None
    item_pdf_path: str | None = None
    lineage_json_path: str | None = None
    review_summary: CandidateReviewSummary | None = None


class CandidatePoolBuildResult(StrictModel):
    """Top-level build metadata for the generated candidate pool."""

    spec_id: str
    title: str
    output_dir: str
    status: RunStatus = RunStatus.COMPLETED
    provider_name: str = "deterministic"
    provider_settings: dict[str, Any] = Field(default_factory=dict)
    generated_at: Any = Field(default_factory=utc_now)
    resolved_atom_ids: list[str] = Field(default_factory=list)
    curated_batch_refs: list[str] = Field(default_factory=list)
    skipped_atom_ids: list[str] = Field(default_factory=list)
    pending_prompt_paths: list[str] = Field(default_factory=list)
    candidate_count: int
    eligible_candidate_count: int
    slot_count: int
    slot_plan_path: str | None = None
    candidate_pool_manifest_path: str | None = None
    mini_alpha_manifest_path: str | None = None
    candidates: list[CandidatePoolCandidateBundle] = Field(default_factory=list)


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


def _relative_to(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, StrictModel):
        text = payload.model_dump_json(indent=2)
    else:
        text = json.dumps(payload, ensure_ascii=False, indent=2)
    path.write_text(text, encoding="utf-8")
    return path


def _load_atoms(repo_root: Path, spec_id: str) -> list[InsightAtom]:
    payload = json.loads(
        (repo_root / "data" / "distilled" / spec_id / "atoms.json").read_text(encoding="utf-8")
    )
    return [InsightAtom.model_validate(item) for item in payload.get("atoms", [])]


def _resolve_batch_ref_path(repo_root: Path, ref: str) -> Path | None:
    candidate = Path(ref)
    if candidate.exists():
        return candidate.resolve()
    repo_candidate = repo_root / ref
    if repo_candidate.exists():
        return repo_candidate.resolve()
    return None


def _atoms_for_loaded_batches(
    *,
    atoms: list[InsightAtom],
    batches: list[LoadedCuratedBatch],
) -> list[InsightAtom]:
    batch_ids = {batch.manifest.batch_id for batch in batches}
    batch_versions = {batch.manifest.batch_version for batch in batches}
    batch_hashes = {batch.manifest.content_hash for batch in batches}
    matched: list[InsightAtom] = []
    for atom in atoms:
        if batch_ids.intersection(atom.source_batch_ids):
            matched.append(atom)
            continue
        if batch_versions.intersection(atom.source_batch_versions):
            matched.append(atom)
            continue
        if batch_hashes.intersection(atom.source_batch_hashes):
            matched.append(atom)
            continue
    return matched


def _atoms_for_batch_ref(*, atoms: list[InsightAtom], batch_ref: str) -> list[InsightAtom]:
    if "@" in batch_ref:
        batch_id, batch_version = batch_ref.split("@", maxsplit=1)
        return [
            atom
            for atom in atoms
            if batch_id in atom.source_batch_ids and batch_version in atom.source_batch_versions
        ]
    return [atom for atom in atoms if batch_ref in atom.source_batch_ids]


def _atom_signatures(atom: InsightAtom) -> list[str]:
    return _unique_preserve_order(
        [_signature(f"atom:{atom.atom_id}"), _signature(atom.topic), _signature(atom.label)]
        + [_signature(move) for move in atom.canonical_moves]
        + [_signature(source_item_id) for source_item_id in atom.source_item_ids]
    )


def _distractor_signatures(validated_item: ValidatedItem) -> list[str]:
    solved = validated_item.solved
    if solved.draft.blueprint.format != ItemFormat.MULTIPLE_CHOICE:
        return []
    correct_index = solved.correct_choice_index
    signatures = [
        _signature(choice)
        for index, choice in enumerate(solved.draft.choices, start=1)
        if correct_index is None or index != correct_index
    ]
    return _unique_preserve_order(signatures)


def _candidate_is_eligible(candidate: CandidatePoolCandidateBundle) -> bool:
    return (
        candidate.approval_status == ApprovalStatus.APPROVED
        and candidate.validation_status == ValidationStatus.PASS
        and not candidate_blocked_from_selection(candidate.review_summary)
    )


def _profile_key(candidate: CandidatePoolCandidateBundle) -> tuple[str, str, str, int]:
    return (
        candidate.domain,
        candidate.difficulty,
        candidate.format.value,
        candidate.score,
    )


def _slot_plan(candidates: list[CandidatePoolCandidateBundle], slot_count: int) -> list[MiniAlphaSlotSpec]:
    eligible = [candidate for candidate in candidates if _candidate_is_eligible(candidate)]
    if len(eligible) < slot_count:
        raise CandidatePoolBuildError(
            f"Need at least {slot_count} eligible generated candidates, found {len(eligible)}"
        )

    grouped: dict[tuple[str, str, str, int], list[CandidatePoolCandidateBundle]] = {}
    for candidate in eligible:
        grouped.setdefault(_profile_key(candidate), []).append(candidate)
    ordered_profiles = sorted(
        grouped.items(),
        key=lambda item: (
            item[0][2] == ItemFormat.SHORT_ANSWER.value,
            item[0][0],
            item[0][1],
            item[0][3],
            item[1][0].source_item_no or 0,
        ),
    )

    profile_count = len(ordered_profiles)
    allocations = {profile: 0 for profile, _ in ordered_profiles}
    if slot_count >= profile_count:
        for profile, _ in ordered_profiles:
            allocations[profile] = 1
        remaining_slots = slot_count - profile_count
        remaining_capacity = {
            profile: max(0, len(items) - 1) for profile, items in ordered_profiles
        }
    else:
        remaining_slots = slot_count
        remaining_capacity = {profile: len(items) for profile, items in ordered_profiles}

    total_capacity = sum(remaining_capacity.values())
    if remaining_slots > total_capacity:
        raise CandidatePoolBuildError(
            f"Need {slot_count} slot positions but only {profile_count + total_capacity} are available"
        )

    if remaining_slots > 0 and total_capacity > 0:
        quotas: dict[tuple[str, str, str, int], float] = {}
        remainders: list[tuple[float, tuple[str, str, str, int]]] = []
        for profile, _ in ordered_profiles:
            capacity = remaining_capacity[profile]
            quota = remaining_slots * capacity / total_capacity if total_capacity else 0.0
            quotas[profile] = quota
            floor = min(capacity, int(quota))
            allocations[profile] += floor
            remaining_capacity[profile] -= floor
            remainders.append((quota - floor, profile))

        assigned = sum(allocations.values())
        still_needed = slot_count - assigned
        for _, profile in sorted(remainders, key=lambda item: (-item[0], item[1])):
            if still_needed <= 0:
                break
            if remaining_capacity[profile] <= 0:
                continue
            allocations[profile] += 1
            remaining_capacity[profile] -= 1
            still_needed -= 1
        if still_needed > 0:
            for profile, _ in ordered_profiles:
                while still_needed > 0 and remaining_capacity[profile] > 0:
                    allocations[profile] += 1
                    remaining_capacity[profile] -= 1
                    still_needed -= 1

    slots: list[MiniAlphaSlotSpec] = []
    slot_no = 1
    for profile, items in ordered_profiles:
        domain, difficulty, format_value, score = profile
        representative = sorted(
            items,
            key=lambda item: (
                item.source_item_no or 0,
                item.family_id,
                item.source_atom_id,
                item.candidate_id,
            ),
        )[0]
        for _ in range(allocations[profile]):
            slots.append(
                MiniAlphaSlotSpec(
                    slot_no=slot_no,
                    sampled_from_item_no=representative.source_item_no or slot_no,
                    domain=domain,
                    format=ItemFormat(format_value),
                    score=score,
                    difficulty=difficulty,
                    objective=representative.objective,
                    skill_tags=representative.skill_tags,
                )
            )
            slot_no += 1
    if len(slots) != slot_count:
        raise CandidatePoolBuildError(
            f"Internal slot planning mismatch: expected {slot_count}, built {len(slots)}"
        )
    return slots


def build_slot_plan(
    candidates: list[CandidatePoolCandidateBundle], slot_count: int
) -> list[MiniAlphaSlotSpec]:
    """Build deterministic slot specs from generated candidate bundle profiles."""
    return _slot_plan(candidates, slot_count)


class CandidatePoolBuilder:
    """Generate candidate bundles from real-item families and emit a mini-alpha manifest."""

    def __init__(
        self,
        *,
        repo_root: Path | None = None,
        spec_id: str = "csat_math_2028",
        xelatex_path: str | None = None,
        provider_config: RealItemProviderConfig | None = None,
        provider: BaseProvider | None = None,
    ) -> None:
        settings = get_settings()
        self.repo_root = repo_root.resolve() if repo_root is not None else settings.repo_root
        self.spec_id = spec_id
        self.xelatex_path = xelatex_path or (
            str(settings.xelatex_path) if settings.xelatex_path else None
        )
        self.provider_config = provider_config or RealItemProviderConfig()
        self.provider = provider

    def resolve_atoms(
        self,
        *,
        atom_ids: list[str] | None = None,
        curated_batch_refs: list[str] | None = None,
    ) -> tuple[list[InsightAtom], list[str]]:
        """Resolve explicit atom ids and curated batch refs into a deduplicated atom list."""
        all_atoms = _load_atoms(self.repo_root, self.spec_id)
        atoms_by_id = {atom.atom_id: atom for atom in all_atoms}
        if not atom_ids and not curated_batch_refs:
            return all_atoms, []
        resolved: list[InsightAtom] = []
        skipped_atom_ids: list[str] = []

        for atom_id in atom_ids or []:
            atom = atoms_by_id.get(atom_id)
            if atom is None:
                skipped_atom_ids.append(atom_id)
                continue
            resolved.append(atom)

        if curated_batch_refs:
            pipeline = DistillPipeline(spec_id=self.spec_id, repo_root=self.repo_root)
            for batch_ref in curated_batch_refs:
                ref_path = _resolve_batch_ref_path(self.repo_root, batch_ref)
                if ref_path is not None:
                    matched = _atoms_for_loaded_batches(
                        atoms=all_atoms,
                        batches=pipeline.load_curated_batches(ref_path),
                    )
                else:
                    matched = _atoms_for_batch_ref(atoms=all_atoms, batch_ref=batch_ref)
                if not matched:
                    skipped_atom_ids.append(batch_ref)
                    continue
                resolved.extend(matched)

        unique_atoms: list[InsightAtom] = []
        seen_ids: set[str] = set()
        for atom in resolved:
            if atom.atom_id in seen_ids:
                continue
            seen_ids.add(atom.atom_id)
            unique_atoms.append(atom)
        return unique_atoms, skipped_atom_ids

    def build(
        self,
        *,
        output_dir: Path,
        title: str,
        slot_count: int = 10,
        atom_ids: list[str] | None = None,
        curated_batch_refs: list[str] | None = None,
        run_id: str = "generated_candidate_pool",
    ) -> CandidatePoolBuildResult:
        """Build a generated pool and emit a MiniAlpha-compatible manifest."""
        resolved_atoms, skipped = self.resolve_atoms(
            atom_ids=atom_ids,
            curated_batch_refs=curated_batch_refs,
        )
        if not resolved_atoms:
            raise CandidatePoolBuildError("No atoms resolved for candidate pool generation")

        output_dir = output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        runtime_dir = output_dir / "runtime"
        store = ArtifactStore(root_dir=runtime_dir / "artifacts", db_path=runtime_dir / "app.db")
        provider = self.provider or self.provider_config.build_provider()
        gauntlet = RealItemGauntlet(
            artifact_store=store,
            prompt_dir=self.repo_root / "src" / "prompts",
            provider=provider,
            provider_settings=self.provider_config.public_settings(),
            xelatex_path=self.xelatex_path,
            max_stage_attempts=self.provider_config.stage_max_attempts,
        )

        candidate_bundles: list[CandidatePoolCandidateBundle] = []
        skipped_atom_ids = list(skipped)
        pending_prompt_paths: list[str] = []

        for index, atom in enumerate(resolved_atoms, start=1):
            candidate_id = f"cand-{index:03d}-{atom.atom_id}"
            run_id_for_candidate = f"{run_id}__{candidate_id}"
            candidate_dir = output_dir / "candidates" / candidate_id
            bundle_dir = candidate_dir / "bundle"
            try:
                gauntlet_result = gauntlet.run(
                    run_id=run_id_for_candidate,
                    atom=atom,
                    mode=self.provider_config.mode,
                    output_dir=bundle_dir,
                    seed=index,
                )
            except RealItemFamilySelectionError:
                skipped_atom_ids.append(atom.atom_id)
                continue

            if gauntlet_result.status == RunStatus.WAITING_MANUAL:
                pending_prompt_paths.extend(gauntlet_result.pending_prompt_paths)
                continue

            state = gauntlet.load_state(run_id_for_candidate)
            if state is None or state.family_id is None:
                raise CandidatePoolBuildError(
                    f"Gauntlet state missing for generated candidate {candidate_id}"
                )
            if "validate" not in state.stage_outputs or state.validator_suite_artifact_id is None:
                raise CandidatePoolBuildError(
                    f"Validation artifacts missing for generated candidate {candidate_id}"
                )

            validated_item = store.load_model(state.stage_outputs["validate"], ValidatedItem)
            validator_report = store.load_model(
                state.validator_suite_artifact_id,
                ValidatorSuiteReport,
            )
            validation_artifact = (
                store.load_model(state.validation_artifact_id, RealItemValidationArtifact)
                if state.validation_artifact_id
                else None
            )

            validated_item_path = _write_json(
                candidate_dir / "validated_item.json",
                validated_item.model_dump(mode="json"),
            )
            validator_report_path = _write_json(
                candidate_dir / "validator_report.json",
                validator_report.model_dump(mode="json"),
            )
            gauntlet_validation_path = None
            if validation_artifact is not None:
                gauntlet_validation_path = str(
                    _write_json(
                        candidate_dir / "gauntlet_validation.json",
                        validation_artifact.model_dump(mode="json"),
                    )
                )

            blueprint = validated_item.solved.draft.blueprint
            candidate_bundle = CandidatePoolCandidateBundle(
                candidate_id=candidate_id,
                run_id=run_id_for_candidate,
                gauntlet_status=gauntlet_result.status.value,
                source_atom_id=atom.atom_id,
                family_id=state.family_id,
                source_item_id=atom.source_item_ids[0] if atom.source_item_ids else None,
                source_item_no=blueprint.item_no,
                domain=blueprint.domain,
                difficulty=blueprint.difficulty.value,
                format=blueprint.format,
                score=blueprint.score,
                objective=blueprint.objective,
                skill_tags=blueprint.skill_tags,
                approval_status=validated_item.approval_status,
                validation_status=validator_report.final_report.status,
                atom_signatures=_atom_signatures(atom),
                distractor_signatures=_distractor_signatures(validated_item),
                candidate_dir=str(candidate_dir),
                validated_item_path=str(validated_item_path),
                validator_report_path=str(validator_report_path),
                gauntlet_validation_path=gauntlet_validation_path,
                bundle_dir=str(bundle_dir) if bundle_dir.exists() else None,
                item_json_path=gauntlet_result.item_json_path,
                solution_json_path=gauntlet_result.solution_json_path,
                review_sheet_path=gauntlet_result.review_sheet_path,
                item_pdf_path=gauntlet_result.item_pdf_path,
                lineage_json_path=gauntlet_result.lineage_json_path,
            )
            _write_json(
                candidate_dir / "candidate_bundle.json",
                candidate_bundle.model_dump(mode="json"),
            )
            candidate_bundles.append(candidate_bundle)

        result_kwargs = {
            "spec_id": self.spec_id,
            "title": title,
            "output_dir": str(output_dir),
            "provider_name": self.provider_config.provider,
            "provider_settings": self.provider_config.public_settings(),
            "resolved_atom_ids": [atom.atom_id for atom in resolved_atoms],
            "curated_batch_refs": curated_batch_refs or [],
            "skipped_atom_ids": _unique_preserve_order(skipped_atom_ids),
            "pending_prompt_paths": _unique_preserve_order(pending_prompt_paths),
            "candidate_count": len(candidate_bundles),
            "eligible_candidate_count": sum(
                1 for candidate in candidate_bundles if _candidate_is_eligible(candidate)
            ),
            "slot_count": slot_count,
            "candidates": candidate_bundles,
        }
        if pending_prompt_paths:
            return CandidatePoolBuildResult(
                status=RunStatus.WAITING_MANUAL,
                **result_kwargs,
            )

        if not candidate_bundles:
            raise CandidatePoolBuildError("No candidate bundles were generated")

        slots = _slot_plan(candidate_bundles, slot_count)
        slot_plan_path = _write_json(
            output_dir / "slot_plan.json",
            [slot.model_dump(mode="json") for slot in slots],
        )

        mini_alpha_manifest = MiniAlphaManifestInput(
            spec_id=self.spec_id,
            title=title,
            slots=slots,
            candidates=[
                MiniAlphaCandidateInput(
                    candidate_id=candidate.candidate_id,
                    validated_item_path=_relative_to(Path(candidate.validated_item_path), output_dir),
                    validator_report_path=_relative_to(
                        Path(candidate.validator_report_path),
                        output_dir,
                    ),
                    source_run_id=candidate.run_id,
                    source_atom_id=candidate.source_atom_id,
                    family_id=candidate.family_id,
                    source_item_id=candidate.source_item_id,
                    source_item_no=candidate.source_item_no,
                    atom_signatures=candidate.atom_signatures,
                    distractor_signatures=candidate.distractor_signatures,
                    review_summary=candidate.review_summary,
                )
                for candidate in candidate_bundles
            ],
        )
        mini_alpha_manifest_path = _write_json(
            output_dir / "mini_alpha_candidate_manifest.json",
            mini_alpha_manifest.model_dump(mode="json"),
        )

        result = CandidatePoolBuildResult(
            status=RunStatus.COMPLETED,
            slot_plan_path=str(slot_plan_path),
            candidate_pool_manifest_path=str(output_dir / "candidate_pool_manifest.json"),
            mini_alpha_manifest_path=str(mini_alpha_manifest_path),
            **result_kwargs,
        )
        if result.candidate_pool_manifest_path is None:
            raise CandidatePoolBuildError("candidate_pool_manifest_path missing for completed pool")
        _write_json(Path(result.candidate_pool_manifest_path), result.model_dump(mode="json"))
        _write_json(
            output_dir / "resolved_atoms.json",
            {
                "resolved_atom_ids": result.resolved_atom_ids,
                "curated_batch_refs": result.curated_batch_refs,
                "skipped_atom_ids": result.skipped_atom_ids,
                "profile_counts": dict(
                    sorted(
                        Counter(
                            f"{candidate.domain}|{candidate.difficulty}|{candidate.format.value}|{candidate.score}"
                            for candidate in candidate_bundles
                        ).items()
                    )
                ),
            },
        )
        return result
