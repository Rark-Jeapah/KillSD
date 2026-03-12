"""Artifact envelope helpers for reproducible JSON persistence."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeVar
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from src.core.schemas import PipelineStage

T = TypeVar("T", bound=BaseModel)


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class ArtifactError(Exception):
    """Base exception for artifact serialization failures."""


class ArtifactEnvelope(BaseModel):
    """Portable JSON wrapper for any pipeline artifact."""

    model_config = ConfigDict(extra="forbid")

    artifact_id: str = Field(default_factory=lambda: f"art-{uuid4().hex[:12]}")
    artifact_type: str
    schema_version: str = "1.0"
    stage: PipelineStage
    run_id: str
    spec_id: str
    created_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)
    payload: dict[str, Any]

    def suggested_path(self, root_dir: Path) -> Path:
        """Build a canonical filesystem location for this artifact."""
        file_name = f"{self.artifact_type}__{self.artifact_id}.json"
        return root_dir / self.run_id / self.stage.value / file_name


def build_artifact_envelope(
    model: BaseModel,
    *,
    stage: PipelineStage,
    run_id: str,
    spec_id: str,
    artifact_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ArtifactEnvelope:
    """Wrap a Pydantic model in a JSON-serializable artifact envelope."""
    return ArtifactEnvelope(
        artifact_id=artifact_id or f"art-{uuid4().hex[:12]}",
        artifact_type=model.__class__.__name__,
        stage=stage,
        run_id=run_id,
        spec_id=spec_id,
        metadata=metadata or {},
        payload=model.model_dump(mode="json"),
    )


def restore_model(envelope: ArtifactEnvelope, model_type: type[T]) -> T:
    """Rehydrate a typed Pydantic model from an artifact envelope."""
    try:
        return model_type.model_validate(envelope.payload)
    except Exception as exc:  # pragma: no cover - exact Pydantic error is enough
        raise ArtifactError(
            f"Failed to restore {model_type.__name__} from artifact {envelope.artifact_id}"
        ) from exc
