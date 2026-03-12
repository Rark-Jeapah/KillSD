"""Filesystem + SQLite artifact storage for the MVP."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict

from src.core.artifacts import ArtifactEnvelope, build_artifact_envelope, restore_model
from src.core.schemas import PipelineStage

T = TypeVar("T", bound=BaseModel)


class StorageError(Exception):
    """Base exception raised by the artifact store."""


class ArtifactNotFoundError(StorageError):
    """Raised when a requested artifact record does not exist."""


class ArtifactIndexRecord(BaseModel):
    """SQLite metadata row for an artifact."""

    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    artifact_type: str
    stage: str
    run_id: str
    spec_id: str
    path: str
    created_at: str
    metadata_json: str


class ArtifactStore:
    """Persist JSON artifacts to disk with a SQLite index."""

    def __init__(self, root_dir: Path, db_path: Path) -> None:
        self.root_dir = root_dir
        self.db_path = db_path

    def initialize(self) -> None:
        """Create directories and the SQLite schema if needed."""
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    artifact_type TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    spec_id TEXT NOT NULL,
                    path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                )
                """
            )
            connection.commit()

    def save_model(
        self,
        model: BaseModel,
        *,
        stage: PipelineStage,
        run_id: str,
        spec_id: str,
        artifact_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactEnvelope:
        """Serialize a model, write JSON to disk, and index it in SQLite."""
        self.initialize()
        envelope = build_artifact_envelope(
            model,
            stage=stage,
            run_id=run_id,
            spec_id=spec_id,
            artifact_id=artifact_id,
            metadata=metadata,
        )
        artifact_path = envelope.suggested_path(self.root_dir)
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(envelope.model_dump_json(indent=2), encoding="utf-8")

        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO artifacts (
                    artifact_id,
                    artifact_type,
                    stage,
                    run_id,
                    spec_id,
                    path,
                    created_at,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    envelope.artifact_id,
                    envelope.artifact_type,
                    envelope.stage.value,
                    envelope.run_id,
                    envelope.spec_id,
                    str(artifact_path),
                    envelope.created_at.isoformat(),
                    json.dumps(envelope.metadata, ensure_ascii=True, sort_keys=True),
                ),
            )
            connection.commit()

        return envelope

    def load_artifact(self, artifact_id: str) -> ArtifactEnvelope:
        """Load an artifact envelope from the indexed filesystem path."""
        record = self._fetch_record(artifact_id)
        path = Path(record.path)
        if not path.exists():
            raise ArtifactNotFoundError(f"Artifact file is missing for {artifact_id}: {path}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return ArtifactEnvelope.model_validate(data)
        except Exception as exc:  # pragma: no cover - JSON parser details are incidental
            raise StorageError(f"Failed to parse artifact file: {path}") from exc

    def load_model(self, artifact_id: str, model_type: type[T]) -> T:
        """Load and validate a typed model from storage."""
        envelope = self.load_artifact(artifact_id)
        return restore_model(envelope, model_type)

    def list_artifacts(
        self,
        *,
        run_id: str | None = None,
        stage: PipelineStage | None = None,
        limit: int = 100,
    ) -> list[ArtifactIndexRecord]:
        """List artifact metadata records with optional filtering."""
        self.initialize()
        clauses: list[str] = []
        params: list[Any] = []
        if run_id:
            clauses.append("run_id = ?")
            params.append(run_id)
        if stage:
            clauses.append("stage = ?")
            params.append(stage.value)

        sql = "SELECT artifact_id, artifact_type, stage, run_id, spec_id, path, created_at, metadata_json FROM artifacts"
        if clauses:
            sql = f"{sql} WHERE {' AND '.join(clauses)}"
        sql = f"{sql} ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with sqlite3.connect(self.db_path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(sql, params).fetchall()
        return [ArtifactIndexRecord.model_validate(dict(row)) for row in rows]

    def _fetch_record(self, artifact_id: str) -> ArtifactIndexRecord:
        """Return a single index record or raise a domain-specific error."""
        self.initialize()
        with sqlite3.connect(self.db_path) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """
                SELECT artifact_id, artifact_type, stage, run_id, spec_id, path, created_at, metadata_json
                FROM artifacts
                WHERE artifact_id = ?
                """,
                (artifact_id,),
            ).fetchone()

        if row is None:
            raise ArtifactNotFoundError(f"Unknown artifact_id: {artifact_id}")
        return ArtifactIndexRecord.model_validate(dict(row))
