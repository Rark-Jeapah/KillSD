"""Schemas for manual source ingestion and structured item cards."""

from __future__ import annotations

from hashlib import sha1
from typing import Any

from pydantic import Field, model_validator

from src.core.schemas import DifficultyBand, ItemFormat, StrictModel


def _stable_id(prefix: str, seed: str) -> str:
    """Return a stable short identifier derived from text."""
    digest = sha1(seed.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


class ManualSourceStep(StrictModel):
    """Manual solution step authored during offline distillation."""

    step_id: str
    label: str
    kind: str
    content: str
    technique: str
    dependencies: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    difficulty_delta: int = 0


class ManualSourceDistractor(StrictModel):
    """Structured wrong-answer pattern from a source item."""

    error_type: str
    trigger: str
    wrong_move: str
    plausible_choice_shape: str
    reject_if_too_obvious: bool = True
    linked_step_id: str | None = None


class ManualSourceItem(StrictModel):
    """Manual JSON/CSV source input used by the distillation pipeline."""

    source_item_id: str
    source_kind: str
    source_label: str
    source_year: int | None = None
    source_path: str | None = None
    subject_area: str
    topic: str
    subtopics: list[str] = Field(default_factory=list)
    item_format: ItemFormat
    score: int
    difficulty: DifficultyBand
    stem: str
    choices: list[str] = Field(default_factory=list)
    answer: str
    solution_steps: list[ManualSourceStep]
    distractors: list[ManualSourceDistractor] = Field(default_factory=list)
    diagram_tags: list[str] = Field(default_factory=list)
    style_notes: list[str] = Field(default_factory=list)
    allowed_answer_forms: list[str] = Field(default_factory=list)
    trigger_patterns: list[str] = Field(default_factory=list)
    source_metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_source_item(self) -> "ManualSourceItem":
        """Validate choice layout, scoring range, and solution-step references."""
        if self.score not in {2, 3, 4}:
            raise ValueError("score must be one of 2, 3, or 4")
        if self.item_format == ItemFormat.MULTIPLE_CHOICE and len(self.choices) != 5:
            raise ValueError("multiple_choice source items must provide 5 choices")
        if self.item_format == ItemFormat.SHORT_ANSWER and self.choices:
            raise ValueError("short_answer source items must not provide choices")
        if not self.solution_steps:
            raise ValueError("solution_steps must not be empty")

        step_ids = {step.step_id for step in self.solution_steps}
        for distractor in self.distractors:
            if distractor.linked_step_id and distractor.linked_step_id not in step_ids:
                raise ValueError("linked_step_id must refer to a solution step")
        return self


class ItemCard(StrictModel):
    """Structured distillation card derived from a source item."""

    card_id: str
    record_version: str | None = None
    spec_id: str
    source_item_id: str
    source_kind: str
    source_label: str
    source_year: int | None = None
    source_path: str | None = None
    subject_area: str
    topic: str
    subtopics: list[str] = Field(default_factory=list)
    item_format: ItemFormat
    score: int
    difficulty: DifficultyBand
    stem: str
    choices: list[str] = Field(default_factory=list)
    answer: str
    trigger_patterns: list[str] = Field(default_factory=list)
    canonical_moves: list[str] = Field(default_factory=list)
    common_failures: list[str] = Field(default_factory=list)
    allowed_answer_forms: list[str] = Field(default_factory=list)
    diagram_tags: list[str] = Field(default_factory=list)
    style_notes: list[str] = Field(default_factory=list)
    source_metadata: dict[str, Any] = Field(default_factory=dict)
    source_batch_ids: list[str] = Field(default_factory=list)
    source_batch_versions: list[str] = Field(default_factory=list)
    source_batch_hashes: list[str] = Field(default_factory=list)


def unique_preserve_order(values: list[str]) -> list[str]:
    """Deduplicate strings while preserving input order."""
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def build_item_card(source_item: ManualSourceItem, *, spec_id: str) -> ItemCard:
    """Convert a manual source item into a structured item card."""
    canonical_moves = unique_preserve_order(
        [step.technique for step in source_item.solution_steps]
        + [step.label for step in source_item.solution_steps]
    )
    common_failures = unique_preserve_order(
        [
            f"{distractor.error_type}: {distractor.wrong_move}"
            for distractor in source_item.distractors
        ]
    )
    card_seed = f"{spec_id}:{source_item.source_item_id}:{source_item.topic}:{source_item.stem}"
    return ItemCard(
        card_id=_stable_id("card", card_seed),
        spec_id=spec_id,
        source_item_id=source_item.source_item_id,
        source_kind=source_item.source_kind,
        source_label=source_item.source_label,
        source_year=source_item.source_year,
        source_path=source_item.source_path,
        subject_area=source_item.subject_area,
        topic=source_item.topic,
        subtopics=source_item.subtopics,
        item_format=source_item.item_format,
        score=source_item.score,
        difficulty=source_item.difficulty,
        stem=source_item.stem,
        choices=source_item.choices,
        answer=source_item.answer,
        trigger_patterns=unique_preserve_order(source_item.trigger_patterns),
        canonical_moves=canonical_moves,
        common_failures=common_failures,
        allowed_answer_forms=unique_preserve_order(source_item.allowed_answer_forms),
        diagram_tags=unique_preserve_order(source_item.diagram_tags),
        style_notes=unique_preserve_order(source_item.style_notes),
        source_metadata=source_item.source_metadata,
    )
