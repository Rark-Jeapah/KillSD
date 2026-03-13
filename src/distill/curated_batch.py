"""Curated batch manifest schemas and loaders for distillation v2."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from pydantic import Field, model_validator

from src.core.schemas import StrictModel
from src.distill.item_card_schema import ManualSourceItem


CURATED_BATCH_MANIFEST_VERSION = "2.0"


class CuratedBatchProvenance(StrictModel):
    """Offline provenance metadata for one curated source batch."""

    exam_name: str
    exam_year: int | None = None
    source_name: str
    source_kind: str = "exam_analysis"


class CuratedBatchManifest(StrictModel):
    """Manifest describing one curated batch of manually authored source items."""

    manifest_version: str = CURATED_BATCH_MANIFEST_VERSION
    spec_id: str
    batch_id: str
    batch_version: str
    created_at: datetime | None = None
    items_path: str
    item_count: int
    content_hash: str
    provenance: CuratedBatchProvenance
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_manifest(self) -> "CuratedBatchManifest":
        """Ensure required audit fields are present."""
        if self.item_count < 1:
            raise ValueError("item_count must be positive")
        if not self.items_path.strip():
            raise ValueError("items_path must not be empty")
        if not self.content_hash.strip():
            raise ValueError("content_hash must not be empty")
        return self


@dataclass(frozen=True)
class LoadedCuratedBatch:
    """Resolved curated batch manifest with validated source items."""

    manifest: CuratedBatchManifest
    manifest_path: Path
    items_path: Path
    items: list[ManualSourceItem]
    computed_item_count: int
    computed_content_hash: str


def is_curated_batch_manifest_payload(payload: Any) -> bool:
    """Return whether a JSON payload looks like a curated batch manifest."""
    if not isinstance(payload, dict):
        return False
    required_keys = {
        "batch_id",
        "batch_version",
        "content_hash",
        "item_count",
        "items_path",
        "manifest_version",
        "provenance",
        "spec_id",
    }
    return required_keys.issubset(payload.keys())


def stable_hash_from_value(value: Any) -> str:
    """Return a canonical sha256 hash for JSON-compatible data."""
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"sha256:{sha256(canonical.encode('utf-8')).hexdigest()}"


def compute_items_content_hash(items: list[ManualSourceItem]) -> str:
    """Compute the audit hash used by curated batch manifests."""
    return stable_hash_from_value([item.model_dump(mode="json") for item in items])


def load_curated_items(items_path: Path) -> list[ManualSourceItem]:
    """Load curated source items from JSON or JSONL."""
    if not items_path.exists():
        raise ValueError(f"Items path does not exist: {items_path}")

    suffix = items_path.suffix.lower()
    if suffix == ".json":
        try:
            payload = json.loads(items_path.read_text(encoding="utf-8"))
        except Exception as exc:  # pragma: no cover - defensive I/O guard
            raise ValueError(f"Failed to read JSON items: {items_path}") from exc
        raw_items = payload["items"] if isinstance(payload, dict) and "items" in payload else payload
        if not isinstance(raw_items, list):
            raise ValueError("JSON items payload must contain a list or an object with `items`")
        return [ManualSourceItem.model_validate(item) for item in raw_items]

    if suffix == ".jsonl":
        items: list[ManualSourceItem] = []
        try:
            with items_path.open("r", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    stripped = line.strip()
                    if not stripped:
                        continue
                    payload = json.loads(stripped)
                    items.append(ManualSourceItem.model_validate(payload))
        except Exception as exc:  # pragma: no cover - defensive I/O guard
            raise ValueError(f"Failed to read JSONL items: {items_path}") from exc
        if not items:
            raise ValueError(f"JSONL items payload is empty: {items_path}")
        return items

    raise ValueError(f"Unsupported curated items format: {items_path.suffix}")


def load_curated_batch(manifest_path: Path) -> LoadedCuratedBatch:
    """Load one curated batch manifest and its referenced item payload."""
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - defensive I/O guard
        raise ValueError(f"Failed to read curated batch manifest: {manifest_path}") from exc

    manifest = CuratedBatchManifest.model_validate(payload)
    items_path = Path(manifest.items_path)
    if not items_path.is_absolute():
        items_path = manifest_path.parent / items_path
    items = load_curated_items(items_path)
    return LoadedCuratedBatch(
        manifest=manifest,
        manifest_path=manifest_path,
        items_path=items_path,
        items=items,
        computed_item_count=len(items),
        computed_content_hash=compute_items_content_hash(items),
    )
