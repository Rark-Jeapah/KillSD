"""Subject plugin registry."""

from __future__ import annotations

from typing import Protocol

from src.core.schemas import ExamBlueprint, ExamSpec


class SubjectPlugin(Protocol):
    """Protocol implemented by subject-specific exam plugins."""

    plugin_id: str
    spec_id: str

    def load_exam_spec(self) -> ExamSpec:
        """Load and validate the exam specification."""

    def build_default_blueprint(self) -> ExamBlueprint:
        """Build the default blueprint for the subject/exam."""


def get_plugin(spec_id: str) -> SubjectPlugin:
    """Resolve a plugin by exam specification id."""
    if spec_id == "csat_math_2028":
        from src.plugins.csat_math_2028 import CSATMath2028Plugin

        return CSATMath2028Plugin()

    raise ValueError(f"Unsupported spec_id: {spec_id}")
