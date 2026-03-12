"""Typed render contexts and renderer configuration."""

from __future__ import annotations

from pydantic import Field

from src.core.schemas import StrictModel


class RendererConfig(StrictModel):
    """Runtime options for LaTeX rendering."""

    xelatex_path: str | None = None


class StudentRenderItem(StrictModel):
    """Student-facing exam item payload."""

    item_no: int
    score: int
    format: str
    stem: str
    choices: list[str] = Field(default_factory=list)
    diagram: str | None = None


class StudentExamRenderContext(StrictModel):
    """Student-facing exam PDF context."""

    title: str
    duration_minutes: str
    total_score: str
    items: list[StudentRenderItem]


class InternalAnswerKeyEntry(StrictModel):
    """Internal answer-key row."""

    item_no: int
    answer: str
    score: int
    correct_choice_index: int | None = None
    correct_choice_value: str | None = None


class InternalAnswerKeyRenderContext(StrictModel):
    """Internal answer-key PDF context."""

    title: str
    generated_at: str
    answers: list[InternalAnswerKeyEntry]


class InternalValidationReportEntry(StrictModel):
    """Internal validation-report row."""

    item_no: int
    status: str
    reason_codes: str
    recommendation: str
    summary: str
    difficulty_band: str
    step_count: int
    concept_count: int
    branching_factor: float
    solver_disagreement_score: float


class InternalValidationReportContext(StrictModel):
    """Internal validation-report PDF context."""

    title: str
    generated_at: str
    reports: list[InternalValidationReportEntry]
