"""Portability tests for artifact indexing and portable fixture metadata."""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

from pydantic import BaseModel

from src.core.schemas import PipelineStage
from src.core.storage import ArtifactStore
from src.distill.pipeline import DistillPipeline


REPO_ROOT = Path(__file__).resolve().parents[1]
REINDEX_SCRIPT = REPO_ROOT / "scripts" / "reindex_artifacts.py"
SOURCE_FIXTURE = REPO_ROOT / "data" / "source_fixtures" / "csat_math_2028" / "sample_items.json"


class SampleArtifact(BaseModel):
    """Small test model for storage round-trips."""

    value: str
    count: int


def _read_indexed_path(db_path: Path, artifact_id: str) -> str:
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT path FROM artifacts WHERE artifact_id = ?",
            (artifact_id,),
        ).fetchone()
    assert row is not None
    return str(row[0])


def test_artifact_store_indexes_relative_paths_and_loads_from_current_root(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "var" / "app.db"
    original_root = tmp_path / "artifacts-a"
    store = ArtifactStore(root_dir=original_root, db_path=db_path)
    envelope = store.save_model(
        SampleArtifact(value="portable", count=7),
        stage=PipelineStage.DESIGN,
        run_id="portable-run",
        spec_id="portable-spec",
    )

    indexed_path = _read_indexed_path(db_path, envelope.artifact_id)
    assert not Path(indexed_path).is_absolute()

    relocated_root = tmp_path / "artifacts-b"
    shutil.copytree(original_root, relocated_root)
    shutil.rmtree(original_root)

    relocated_store = ArtifactStore(root_dir=relocated_root, db_path=db_path)
    loaded = relocated_store.load_model(envelope.artifact_id, SampleArtifact)

    assert loaded == SampleArtifact(value="portable", count=7)


def test_artifact_store_loads_legacy_absolute_paths(tmp_path: Path) -> None:
    db_path = tmp_path / "var" / "app.db"
    artifact_root = tmp_path / "artifacts"
    store = ArtifactStore(root_dir=artifact_root, db_path=db_path)
    envelope = store.save_model(
        SampleArtifact(value="legacy", count=3),
        stage=PipelineStage.GENERATION,
        run_id="legacy-run",
        spec_id="portable-spec",
    )

    absolute_path = store.resolve_indexed_path(_read_indexed_path(db_path, envelope.artifact_id))
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE artifacts SET path = ? WHERE artifact_id = ?",
            (str(absolute_path), envelope.artifact_id),
        )
        connection.commit()

    loaded = store.load_model(envelope.artifact_id, SampleArtifact)
    assert loaded == SampleArtifact(value="legacy", count=3)


def test_reindex_artifacts_script_rebuilds_sqlite_index(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    db_path = tmp_path / "var" / "app.db"
    store = ArtifactStore(root_dir=artifact_root, db_path=db_path)
    first = store.save_model(
        SampleArtifact(value="one", count=1),
        stage=PipelineStage.ASSEMBLY,
        run_id="reindex-run",
        spec_id="portable-spec",
    )
    second = store.save_model(
        SampleArtifact(value="two", count=2),
        stage=PipelineStage.RENDER,
        run_id="reindex-run",
        spec_id="portable-spec",
    )
    (artifact_root / "reindex-run" / "orchestrator_state.json").write_text(
        json.dumps({"status": "completed"}, indent=2),
        encoding="utf-8",
    )
    db_path.unlink()

    result = subprocess.run(
        [
            sys.executable,
            str(REINDEX_SCRIPT),
            "--artifact-root",
            str(artifact_root),
            "--db-path",
            str(db_path),
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    records = ArtifactStore(root_dir=artifact_root, db_path=db_path).list_artifacts(limit=10)

    assert payload["scanned_files"] == 3
    assert payload["indexed_files"] == 2
    assert payload["skipped_files"] == 1
    assert {record.artifact_id for record in records} == {first.artifact_id, second.artifact_id}
    assert all(not Path(record.path).is_absolute() for record in records)


def test_distill_pipeline_serializes_repo_relative_paths(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    source_path = repo_root / "data" / "source_fixtures" / "csat_math_2028" / "sample_items.json"
    output_dir = repo_root / "data" / "distilled" / "csat_math_2028"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SOURCE_FIXTURE, source_path)

    pipeline = DistillPipeline(spec_id="csat_math_2028", repo_root=repo_root)
    manifest = pipeline.run(source_path=source_path, output_dir=output_dir)
    atoms_payload = json.loads((output_dir / "atoms.json").read_text(encoding="utf-8"))

    assert manifest["source_path"] == "data/source_fixtures/csat_math_2028/sample_items.json"
    assert manifest["output_dir"] == "data/distilled/csat_math_2028"
    assert atoms_payload["source_path"] == "data/source_fixtures/csat_math_2028/sample_items.json"
