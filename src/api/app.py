"""FastAPI application skeleton for the CSAT mathematics MVP."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from src.config.settings import get_settings
from src.core.schemas import ManualExchangePacket, PipelineStage, PromptPacket
from src.core.storage import ArtifactStore, StorageError
from src.plugins import get_plugin


class PersistRequest(BaseModel):
    """Common request shape for persisted API submissions."""

    run_id: str = Field(..., min_length=1)


app = FastAPI(title="CSAT Math MVP API", version="0.1.0")


def _store() -> ArtifactStore:
    """Create a storage facade from current settings."""
    settings = get_settings()
    return ArtifactStore(root_dir=settings.artifact_root, db_path=settings.database_path)


@app.get("/health")
def health() -> dict[str, str]:
    """Simple process health endpoint."""
    settings = get_settings()
    return {
        "status": "ok",
        "app_name": settings.app_name,
        "default_spec_id": settings.default_spec_id,
    }


@app.get("/specs/{spec_id}")
def get_spec(spec_id: str) -> dict:
    """Return the validated exam specification."""
    try:
        spec = get_plugin(spec_id).load_exam_spec()
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return spec.model_dump(mode="json")


@app.post("/blueprints/{spec_id}")
def create_blueprint(spec_id: str, request: PersistRequest) -> dict[str, str]:
    """Build and persist the default blueprint as a design-stage artifact."""
    try:
        blueprint = get_plugin(spec_id).build_default_blueprint()
        envelope = _store().save_model(
            blueprint,
            stage=PipelineStage.DESIGN,
            run_id=request.run_id,
            spec_id=spec_id,
            metadata={"generator": blueprint.generator},
        )
        return {"artifact_id": envelope.artifact_id, "artifact_type": envelope.artifact_type}
    except (ValueError, StorageError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/artifacts/prompt-packets")
def persist_prompt_packet(packet: PromptPacket) -> dict[str, str]:
    """Persist a prompt packet using the shared execution contract."""
    try:
        envelope = _store().save_model(
            packet,
            stage=packet.stage,
            run_id=packet.run_id,
            spec_id=packet.spec_id,
            metadata={"mode": packet.mode.value},
        )
        return {"artifact_id": envelope.artifact_id, "artifact_type": envelope.artifact_type}
    except StorageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/artifacts/manual-exchanges")
def persist_manual_exchange(packet: ManualExchangePacket) -> dict[str, str]:
    """Persist a manual exchange packet with the same underlying prompt contract."""
    try:
        envelope = _store().save_model(
            packet,
            stage=packet.prompt_packet.stage,
            run_id=packet.prompt_packet.run_id,
            spec_id=packet.prompt_packet.spec_id,
            metadata={"status": packet.status.value},
        )
        return {"artifact_id": envelope.artifact_id, "artifact_type": envelope.artifact_type}
    except StorageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
