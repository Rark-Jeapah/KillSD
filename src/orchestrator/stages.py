"""Stage definitions and local stage helpers for generation orchestration."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from src.assembly.orderer import order_validated_items
from src.core.schemas import (
    CritiqueReport,
    ExamMode,
    ExamSpec,
    PipelineStage,
    PromptPacket,
    RenderBundle,
    SolvedItem,
    ValidatedItem,
    utc_now,
    ExamBlueprint,
    ItemBlueprint,
    DraftItem,
)
from src.validators.report import (
    ValidationContext,
    ValidatorSuiteReport,
    load_distilled_resources,
    load_similarity_thresholds,
    run_validator_suite,
)


PROMPT_VERSION_PATTERN = re.compile(r"version:\s*([^\s]+)", flags=re.IGNORECASE)


@dataclass(frozen=True)
class PromptTemplate:
    """Loaded prompt template plus provenance metadata."""

    path: Path
    version: str
    hash_value: str
    content: str


@dataclass(frozen=True)
class StageDefinition:
    """Declarative stage definition used by the state machine."""

    name: str
    pipeline_stage: PipelineStage
    output_model: type[BaseModel]
    prompt_file: str | None
    item_scoped: bool
    remote: bool


STAGE_DEFINITIONS: tuple[StageDefinition, ...] = (
    StageDefinition(
        name="exam_blueprint",
        pipeline_stage=PipelineStage.DESIGN,
        output_model=ExamBlueprint,
        prompt_file="exam_blueprint.md",
        item_scoped=False,
        remote=True,
    ),
    StageDefinition(
        name="item_blueprint",
        pipeline_stage=PipelineStage.DESIGN,
        output_model=ItemBlueprint,
        prompt_file="item_blueprint.md",
        item_scoped=True,
        remote=True,
    ),
    StageDefinition(
        name="draft_item",
        pipeline_stage=PipelineStage.GENERATION,
        output_model=DraftItem,
        prompt_file="draft_item.md",
        item_scoped=True,
        remote=True,
    ),
    StageDefinition(
        name="solve",
        pipeline_stage=PipelineStage.SOLVING,
        output_model=SolvedItem,
        prompt_file="solver.md",
        item_scoped=True,
        remote=True,
    ),
    StageDefinition(
        name="critique",
        pipeline_stage=PipelineStage.VALIDATION,
        output_model=CritiqueReport,
        prompt_file="critic.md",
        item_scoped=True,
        remote=True,
    ),
    StageDefinition(
        name="revise",
        pipeline_stage=PipelineStage.REVISION,
        output_model=SolvedItem,
        prompt_file="reviser.md",
        item_scoped=True,
        remote=True,
    ),
    StageDefinition(
        name="validate",
        pipeline_stage=PipelineStage.VALIDATION,
        output_model=ValidatedItem,
        prompt_file=None,
        item_scoped=True,
        remote=False,
    ),
    StageDefinition(
        name="assemble",
        pipeline_stage=PipelineStage.ASSEMBLY,
        output_model=RenderBundle,
        prompt_file=None,
        item_scoped=False,
        remote=False,
    ),
)

STAGE_BY_NAME = {stage.name: stage for stage in STAGE_DEFINITIONS}


def stage_key(stage_name: str, item_no: int | None = None) -> str:
    """Return a stable state key for a stage attempt."""
    return f"{stage_name}:{item_no}" if item_no is not None else stage_name


def get_stage_definition(stage_name: str) -> StageDefinition:
    """Resolve a stage definition by name."""
    try:
        return STAGE_BY_NAME[stage_name]
    except KeyError as exc:
        raise ValueError(f"Unknown stage: {stage_name}") from exc


def load_prompt_template(prompt_dir: Path, prompt_file: str) -> PromptTemplate:
    """Load a prompt file and compute version/hash metadata."""
    path = prompt_dir / prompt_file
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    content = path.read_text(encoding="utf-8")
    first_line = content.splitlines()[0] if content.splitlines() else ""
    version_match = PROMPT_VERSION_PATTERN.search(first_line)
    version = version_match.group(1) if version_match else "unversioned"
    hash_value = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return PromptTemplate(path=path, version=version, hash_value=hash_value, content=content)


def build_prompt_packet(
    *,
    mode: ExamMode,
    stage_name: str,
    spec_id: str,
    run_id: str,
    blueprint_id: str | None,
    item_no: int | None,
    input_artifact_ids: list[str],
    context: dict[str, Any],
    seed: int,
    attempt: int,
    provider_name: str | None,
    prompt_template: PromptTemplate,
    output_model: type[BaseModel],
    pipeline_stage: PipelineStage,
) -> PromptPacket:
    """Build a strict PromptPacket for a remote stage."""
    return PromptPacket(
        mode=mode,
        stage=pipeline_stage,
        stage_name=stage_name,
        spec_id=spec_id,
        run_id=run_id,
        blueprint_id=blueprint_id,
        item_no=item_no,
        instructions=[prompt_template.content],
        input_artifact_ids=input_artifact_ids,
        lineage_parent_ids=input_artifact_ids,
        context=context,
        expected_output_model=output_model.__name__,
        response_json_schema=output_model.model_json_schema(),
        prompt_template_path=str(prompt_template.path),
        prompt_version=prompt_template.version,
        prompt_hash=prompt_template.hash_value,
        seed=seed,
        attempt=attempt,
        provider_name=provider_name,
    )


def validate_item_locally(
    *,
    solved_item: SolvedItem,
    critique_report: CritiqueReport,
    spec: ExamSpec,
    repo_root: Path,
) -> tuple[ValidatorSuiteReport, ValidatedItem]:
    """Run the full validator suite using distilled runtime-safe resources."""
    resources = load_distilled_resources(repo_root=repo_root, spec_id=spec.spec_id)
    thresholds = load_similarity_thresholds(repo_root / "config" / "similarity_thresholds.json")
    context = ValidationContext(
        spec=spec,
        solved_item=solved_item,
        critique_report=critique_report,
        resources=resources,
        similarity_thresholds=thresholds,
    )
    return run_validator_suite(context=context)


def assemble_render_bundle(
    *,
    spec: ExamSpec,
    exam_blueprint: ExamBlueprint,
    validated_items: list[ValidatedItem],
) -> RenderBundle:
    """Assemble the final render bundle after all items validate."""
    ordered_items, metrics = order_validated_items(exam_blueprint, validated_items)
    answer_key = {
        item.solved.draft.blueprint.item_no: item.solved.final_answer for item in ordered_items
    }
    return RenderBundle(
        spec_id=spec.spec_id,
        blueprint_id=exam_blueprint.blueprint_id,
        generated_at=utc_now(),
        items=ordered_items,
        student_metadata={
            "title": spec.title,
            "duration_minutes": str(spec.duration_minutes),
            "total_score": str(spec.total_score),
        },
        internal_metadata={
            "topic_coverage": ",".join(
                f"{domain}:{count}" for domain, count in sorted(metrics.topic_coverage.items())
            ),
            "difficulty_curve": ",".join(metrics.difficulty_curve),
            "score_distribution": ",".join(
                f"{score}:{count}" for score, count in sorted(metrics.score_distribution.items())
            ),
        },
        output_targets=["exam_pdf", "answer_key_pdf", "validation_report_pdf"],
        answer_key=answer_key,
        asset_refs=[],
    )
