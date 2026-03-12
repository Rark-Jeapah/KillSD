"""Exam specification loading utilities."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.core.schemas import ExamSpec


class ExamSpecError(Exception):
    """Raised when an exam specification cannot be loaded or validated."""


def _parse_yaml_like_document(raw_text: str) -> dict[str, Any]:
    """Parse a YAML document, with JSON fallback for dependency-light MVP use."""
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(raw_text)
    except ModuleNotFoundError:
        data = json.loads(raw_text)
    except Exception as exc:  # pragma: no cover - parser internals are not the API
        raise ExamSpecError("Failed to parse exam spec document") from exc

    if not isinstance(data, dict):
        raise ExamSpecError("Exam spec must deserialize to an object")
    return data


def load_exam_spec(path: Path) -> ExamSpec:
    """Load an exam spec from disk and validate it against the schema."""
    if not path.exists():
        raise ExamSpecError(f"Spec file does not exist: {path}")
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ExamSpecError(f"Failed to read spec file: {path}") from exc

    data = _parse_yaml_like_document(raw_text)
    try:
        return ExamSpec.model_validate(data)
    except Exception as exc:
        raise ExamSpecError(f"Spec validation failed for {path}") from exc


def resolve_spec_path(spec_id: str, specs_dir: Path) -> Path:
    """Resolve a convention-based spec path under the exam specs directory."""
    return specs_dir / f"{spec_id}.yaml"
