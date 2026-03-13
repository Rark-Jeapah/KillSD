"""Helpers for curated batch authoring, validation, and coverage reporting."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from pydantic import ValidationError

from src.core.schemas import ExamSpec, ItemFormat
from src.distill.atom_extractor import InsightAtom, extract_item_atoms, merge_atoms
from src.distill.curated_batch import (
    CURATED_BATCH_MANIFEST_VERSION,
    CuratedBatchManifest,
    compute_items_content_hash,
    is_curated_batch_manifest_payload,
    stable_hash_from_value,
)
from src.distill.item_card_schema import (
    ManualSourceItem,
    build_item_card,
    unique_preserve_order,
)
from src.distill.solution_graph import build_solution_graph
from src.orchestrator.real_item_families import build_real_item_family_registry
from src.plugins import get_plugin


_NORMALIZE_PATTERN = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class TemplateDefinition:
    """Curated batch starter template."""

    name: str
    description: str
    items: list[dict[str, Any]]
    source_path: Path


@dataclass(frozen=True)
class ItemIssue:
    """Validation findings for one raw item entry."""

    index: int
    source_item_id: str | None
    errors: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class ItemOccurrence:
    """One schema-valid curated item and its batch provenance."""

    item: ManualSourceItem
    item_hash: str
    batch_id: str
    batch_version: str
    batch_created_at: datetime | None
    manifest_path: Path
    items_path: Path
    index: int


@dataclass(frozen=True)
class BatchScanResult:
    """Validation state for one curated batch manifest."""

    batch_id: str
    batch_version: str
    manifest_path: Path
    items_path: Path | None
    manifest_payload: dict[str, Any] | None
    manifest: CuratedBatchManifest | None
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    item_issues: tuple[ItemIssue, ...]
    raw_item_count: int
    schema_valid_item_count: int
    valid_item_count: int
    computed_content_hash: str | None
    semantic_valid_occurrences: tuple[ItemOccurrence, ...]
    all_schema_valid_occurrences: tuple[ItemOccurrence, ...]

    @property
    def is_valid(self) -> bool:
        return not self.errors and all(not issue.errors for issue in self.item_issues)


@dataclass(frozen=True)
class SpecTopicArea:
    """Skill-tag-derived topic area from the canonical exam spec."""

    subject_area: str
    skill_tag: str
    item_nos: tuple[int, ...]
    objectives: tuple[str, ...]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_text(value: str) -> str:
    return _NORMALIZE_PATTERN.sub("_", value.strip().lower()).strip("_")


def _tokenize(value: str) -> set[str]:
    normalized = _normalize_text(value)
    if not normalized:
        return set()
    return {token for token in normalized.split("_") if token}


def _format_validation_error(exc: ValidationError) -> list[str]:
    messages: list[str] = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error.get("loc", ()))
        if location:
            messages.append(f"{location}: {error['msg']}")
        else:
            messages.append(str(error["msg"]))
    return messages


class CurationWorkbench:
    """Practical authoring helpers for curated source batches."""

    def __init__(self, *, spec_id: str = "csat_math_2028", repo_root: Path | None = None) -> None:
        self.spec_id = spec_id
        self.repo_root = repo_root.resolve() if repo_root is not None else None
        self.spec = get_plugin(spec_id).load_exam_spec()
        self.registry = build_real_item_family_registry()
        self._spec_topic_areas = self._build_spec_topic_areas(self.spec)

    def list_templates(self) -> list[dict[str, Any]]:
        """Return starter templates available under data/curated_batches/templates."""
        templates: list[dict[str, Any]] = []
        for path in sorted(self.template_dir.glob("*.json")):
            definition = self._load_template_definition(path)
            templates.append(
                {
                    "name": definition.name,
                    "description": definition.description,
                    "item_count": len(definition.items),
                    "template_path": self.portable_path(path),
                }
            )
        return templates

    @property
    def template_dir(self) -> Path:
        if self.repo_root is None:
            raise ValueError("repo_root is required to discover curated batch templates")
        return self.repo_root / "data" / "curated_batches" / "templates"

    def initialize_batch(
        self,
        *,
        batch_id: str,
        batch_version: str,
        output_dir: Path,
        template_name: str = "empty",
        exam_name: str = "CSAT Mathematics",
        exam_year: int | None = None,
        source_name: str = "manual_curation",
        source_kind: str = "exam_analysis",
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Create a new curated batch manifest and starter items payload."""
        template = self.load_template(template_name)
        validated_items = [ManualSourceItem.model_validate(item) for item in template.items]

        output_dir.mkdir(parents=True, exist_ok=True)
        items_path = output_dir / f"{batch_id}.items.json"
        manifest_path = output_dir / f"{batch_id}.manifest.json"
        existing_paths = [path for path in (items_path, manifest_path) if path.exists()]
        if existing_paths and not overwrite:
            joined = ", ".join(self.portable_path(path) for path in existing_paths)
            raise ValueError(f"Refusing to overwrite existing files: {joined}")

        items_payload = {"items": template.items}
        items_path.write_text(
            json.dumps(items_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        manifest = {
            "manifest_version": CURATED_BATCH_MANIFEST_VERSION,
            "spec_id": self.spec_id,
            "batch_id": batch_id,
            "batch_version": batch_version,
            "created_at": _utc_now_iso(),
            "items_path": items_path.name,
            "item_count": len(validated_items),
            "content_hash": compute_items_content_hash(validated_items),
            "provenance": {
                "exam_name": exam_name,
                "exam_year": self.spec.exam_year if exam_year is None else exam_year,
                "source_name": source_name,
                "source_kind": source_kind,
            },
            "metadata": {
                "authoring_status": "draft",
                "initialized_from_template": template.name,
            },
        }
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        return {
            "spec_id": self.spec_id,
            "batch_id": batch_id,
            "batch_version": batch_version,
            "template_name": template.name,
            "manifest_path": self.portable_path(manifest_path),
            "items_path": self.portable_path(items_path),
            "item_count": len(validated_items),
            "content_hash": manifest["content_hash"],
        }

    def validate_batches(self, batch_path: Path) -> dict[str, Any]:
        """Validate curated manifests plus authoring semantics in one pass."""
        resolved_batch_path = self._resolve_input_path(batch_path)
        manifest_paths = self._discover_manifest_paths(resolved_batch_path)
        scans = [self._scan_batch(manifest_path) for manifest_path in manifest_paths]

        error_count = 0
        warning_count = 0
        batch_entries: list[dict[str, Any]] = []
        all_semantic_valid_occurrences: list[ItemOccurrence] = []
        all_schema_valid_occurrences: list[ItemOccurrence] = []
        for scan in scans:
            error_count += len(scan.errors) + sum(len(issue.errors) for issue in scan.item_issues)
            warning_count += len(scan.warnings) + sum(len(issue.warnings) for issue in scan.item_issues)
            all_semantic_valid_occurrences.extend(scan.semantic_valid_occurrences)
            all_schema_valid_occurrences.extend(scan.all_schema_valid_occurrences)

            batch_entries.append(
                {
                    "batch_id": scan.batch_id,
                    "batch_version": scan.batch_version,
                    "manifest_version": (
                        scan.manifest.manifest_version if scan.manifest is not None else None
                    ),
                    "manifest_path": self.portable_path(scan.manifest_path),
                    "items_path": (
                        self.portable_path(scan.items_path) if scan.items_path is not None else None
                    ),
                    "declared_item_count": (
                        scan.manifest.item_count if scan.manifest is not None else None
                    ),
                    "raw_item_count": scan.raw_item_count,
                    "schema_valid_item_count": scan.schema_valid_item_count,
                    "valid_item_count": scan.valid_item_count,
                    "declared_content_hash": (
                        scan.manifest.content_hash if scan.manifest is not None else None
                    ),
                    "computed_content_hash": scan.computed_content_hash,
                    "errors": list(scan.errors),
                    "warnings": list(scan.warnings),
                    "item_issues": [
                        {
                            "index": issue.index,
                            "source_item_id": issue.source_item_id,
                            "errors": list(issue.errors),
                            "warnings": list(issue.warnings),
                        }
                        for issue in scan.item_issues
                        if issue.errors or issue.warnings
                    ],
                }
            )

        duplicates = self._build_duplicate_report(scans=scans, occurrences=all_schema_valid_occurrences)
        error_count += duplicates["error_count"]
        warning_count += duplicates["warning_count"]

        return {
            "spec_id": self.spec_id,
            "batch_root": self.portable_path(resolved_batch_path),
            "batch_count": len(scans),
            "counts": {
                "raw_items": sum(scan.raw_item_count for scan in scans),
                "schema_valid_items": sum(scan.schema_valid_item_count for scan in scans),
                "valid_items": sum(scan.valid_item_count for scan in scans),
            },
            "error_count": error_count,
            "warning_count": warning_count,
            "valid": error_count == 0,
            "batches": batch_entries,
            "duplicates": duplicates["report"],
        }

    def coverage_gap_report(self, batch_path: Path) -> dict[str, Any]:
        """Report curated coverage, family support, and remaining spec gaps."""
        resolved_batch_path = self._resolve_input_path(batch_path)
        validation = self.validate_batches(resolved_batch_path)
        manifest_paths = self._discover_manifest_paths(resolved_batch_path)
        scans = [self._scan_batch(manifest_path) for manifest_path in manifest_paths]
        retained_occurrences = self._retain_latest_occurrences(
            [
                occurrence
                for scan in scans
                for occurrence in scan.semantic_valid_occurrences
            ]
        )

        item_cards = [build_item_card(record.item, spec_id=self.spec_id) for record in retained_occurrences]
        coverage_counts = self._coverage_counts(item_cards)
        merged_atoms = self._build_atoms_from_occurrences(retained_occurrences)
        family_coverage, unsupported_atoms = self._family_coverage(merged_atoms)
        topic_area_report = self._spec_topic_area_report(retained_occurrences)

        return {
            "spec_id": self.spec_id,
            "batch_root": self.portable_path(resolved_batch_path),
            "validation": {
                "valid": validation["valid"],
                "error_count": validation["error_count"],
                "warning_count": validation["warning_count"],
            },
            "counts": {
                "retained_items": len(retained_occurrences),
                "curated_atoms": len(merged_atoms),
                **coverage_counts,
            },
            "family_coverage": family_coverage,
            "missing_topic_areas": topic_area_report["missing"],
            "spec_topic_area_coverage": topic_area_report["summary"],
            "unsupported_atoms": unsupported_atoms,
            "duplicates": validation["duplicates"],
        }

    def load_template(self, template_name: str) -> TemplateDefinition:
        """Load one starter template by name."""
        path = self.template_dir / f"{template_name}.json"
        if not path.exists():
            available = ", ".join(template["name"] for template in self.list_templates())
            raise ValueError(f"Unknown template '{template_name}'. Available templates: {available}")
        return self._load_template_definition(path)

    def portable_path(self, path: Path) -> str:
        resolved = path.resolve()
        if self.repo_root is not None:
            try:
                return resolved.relative_to(self.repo_root).as_posix()
            except ValueError:
                pass
        return str(resolved)

    def _load_template_definition(self, path: Path) -> TemplateDefinition:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError(f"Failed to read template: {path}") from exc
        if not isinstance(payload, dict) or "items" not in payload:
            raise ValueError(f"Template must be a JSON object with an items array: {path}")
        raw_items = payload["items"]
        if not isinstance(raw_items, list):
            raise ValueError(f"Template items must be a list: {path}")
        return TemplateDefinition(
            name=str(payload.get("template_name") or path.stem),
            description=str(payload.get("description") or ""),
            items=raw_items,
            source_path=path,
        )

    def _resolve_input_path(self, path: Path) -> Path:
        if path.is_absolute():
            return path
        if self.repo_root is None:
            return path.resolve()
        return (self.repo_root / path).resolve()

    def _discover_manifest_paths(self, batch_path: Path) -> list[Path]:
        if not batch_path.exists():
            raise ValueError(f"Curated batch path does not exist: {batch_path}")
        if batch_path.is_file():
            return [batch_path]

        manifest_paths = sorted(batch_path.rglob("*.manifest.json"))
        if manifest_paths:
            return manifest_paths

        discovered: list[Path] = []
        for candidate in sorted(batch_path.rglob("*.json")):
            try:
                payload = json.loads(candidate.read_text(encoding="utf-8"))
            except Exception:
                continue
            if is_curated_batch_manifest_payload(payload):
                discovered.append(candidate)
        if not discovered:
            raise ValueError(f"No curated batch manifests found under {batch_path}")
        return discovered

    def _scan_batch(self, manifest_path: Path) -> BatchScanResult:
        errors: list[str] = []
        warnings: list[str] = []
        item_issues: list[ItemIssue] = []
        manifest_payload: dict[str, Any] | None = None
        manifest: CuratedBatchManifest | None = None
        items_path: Path | None = None
        raw_item_count = 0
        schema_valid_occurrences: list[ItemOccurrence] = []
        semantic_valid_occurrences: list[ItemOccurrence] = []

        try:
            raw_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"failed to read manifest JSON: {exc}")
            return BatchScanResult(
                batch_id=manifest_path.stem,
                batch_version="unknown",
                manifest_path=manifest_path,
                items_path=None,
                manifest_payload=None,
                manifest=None,
                errors=tuple(errors),
                warnings=tuple(warnings),
                item_issues=tuple(item_issues),
                raw_item_count=0,
                schema_valid_item_count=0,
                valid_item_count=0,
                computed_content_hash=None,
                semantic_valid_occurrences=tuple(),
                all_schema_valid_occurrences=tuple(),
            )

        if isinstance(raw_payload, dict):
            manifest_payload = raw_payload
        else:
            errors.append("manifest must deserialize to a JSON object")

        batch_id = str(manifest_payload.get("batch_id", manifest_path.stem)) if manifest_payload else manifest_path.stem
        batch_version = str(manifest_payload.get("batch_version", "unknown")) if manifest_payload else "unknown"

        if manifest_payload is not None:
            try:
                manifest = CuratedBatchManifest.model_validate(manifest_payload)
            except ValidationError as exc:
                errors.extend(_format_validation_error(exc))

        if manifest is not None and manifest.manifest_version != CURATED_BATCH_MANIFEST_VERSION:
            errors.append(
                "unsupported manifest_version "
                f"{manifest.manifest_version}; expected {CURATED_BATCH_MANIFEST_VERSION}"
            )
        if manifest is not None and manifest.spec_id != self.spec_id:
            errors.append(f"spec_id mismatch: manifest={manifest.spec_id}, expected={self.spec_id}")

        raw_items_path = None
        if manifest is not None:
            raw_items_path = manifest.items_path
        elif manifest_payload is not None and isinstance(manifest_payload.get("items_path"), str):
            raw_items_path = str(manifest_payload["items_path"])

        if raw_items_path:
            items_path = Path(raw_items_path)
            if not items_path.is_absolute():
                items_path = manifest_path.parent / items_path
        else:
            errors.append("items_path is missing from the manifest")

        raw_entries: list[tuple[int, dict[str, Any] | None, str | None]] = []
        if items_path is not None:
            load_errors, raw_entries = self._load_raw_entries(items_path)
            errors.extend(load_errors)
            raw_item_count = len(raw_entries)

        for index, raw_item, decode_error in raw_entries:
            if decode_error is not None:
                item_issues.append(
                    ItemIssue(
                        index=index,
                        source_item_id=None,
                        errors=(decode_error,),
                        warnings=(),
                    )
                )
                continue
            if raw_item is None:
                item_issues.append(
                    ItemIssue(
                        index=index,
                        source_item_id=None,
                        errors=("item payload must be a JSON object",),
                        warnings=(),
                    )
                )
                continue

            source_item_id = raw_item.get("source_item_id")
            try:
                item = ManualSourceItem.model_validate(raw_item)
            except ValidationError as exc:
                item_issues.append(
                    ItemIssue(
                        index=index,
                        source_item_id=str(source_item_id) if source_item_id is not None else None,
                        errors=tuple(_format_validation_error(exc)),
                        warnings=(),
                    )
                )
                continue

            occurrence = ItemOccurrence(
                item=item,
                item_hash=stable_hash_from_value(item.model_dump(mode="json")),
                batch_id=batch_id,
                batch_version=batch_version,
                batch_created_at=manifest.created_at if manifest is not None else None,
                manifest_path=manifest_path,
                items_path=items_path if items_path is not None else manifest_path,
                index=index,
            )
            schema_valid_occurrences.append(occurrence)

            item_errors, item_warnings = self._validate_item_semantics(item)
            item_issues.append(
                ItemIssue(
                    index=index,
                    source_item_id=item.source_item_id,
                    errors=tuple(item_errors),
                    warnings=tuple(item_warnings),
                )
            )
            if not item_errors:
                semantic_valid_occurrences.append(occurrence)

        computed_content_hash = None
        if raw_item_count == len(schema_valid_occurrences):
            computed_content_hash = compute_items_content_hash(
                [occurrence.item for occurrence in schema_valid_occurrences]
            )

        if manifest is not None:
            if manifest.item_count != raw_item_count:
                errors.append(
                    f"item_count mismatch: declared={manifest.item_count}, raw={raw_item_count}"
                )
            if computed_content_hash is None:
                errors.append("content_hash could not be computed because some items are malformed")
            elif manifest.content_hash != computed_content_hash:
                errors.append(
                    f"content_hash mismatch: declared={manifest.content_hash}, computed={computed_content_hash}"
                )
            if manifest.item_count == 0:
                warnings.append("batch is currently empty; distillation will skip it")

        return BatchScanResult(
            batch_id=batch_id,
            batch_version=batch_version,
            manifest_path=manifest_path,
            items_path=items_path,
            manifest_payload=manifest_payload,
            manifest=manifest,
            errors=tuple(unique_preserve_order(errors)),
            warnings=tuple(unique_preserve_order(warnings)),
            item_issues=tuple(item_issues),
            raw_item_count=raw_item_count,
            schema_valid_item_count=len(schema_valid_occurrences),
            valid_item_count=len(semantic_valid_occurrences),
            computed_content_hash=computed_content_hash,
            semantic_valid_occurrences=tuple(semantic_valid_occurrences),
            all_schema_valid_occurrences=tuple(schema_valid_occurrences),
        )

    def _load_raw_entries(self, items_path: Path) -> tuple[list[str], list[tuple[int, dict[str, Any] | None, str | None]]]:
        if not items_path.exists():
            return [f"items_path does not exist: {self.portable_path(items_path)}"], []

        suffix = items_path.suffix.lower()
        entries: list[tuple[int, dict[str, Any] | None, str | None]] = []
        errors: list[str] = []
        if suffix == ".json":
            try:
                payload = json.loads(items_path.read_text(encoding="utf-8"))
            except Exception as exc:
                return [f"failed to read items JSON: {exc}"], []
            raw_items = payload["items"] if isinstance(payload, dict) and "items" in payload else payload
            if not isinstance(raw_items, list):
                return ["JSON items payload must contain a list or an object with an items array"], []
            for index, raw_item in enumerate(raw_items, start=1):
                entries.append((index, raw_item if isinstance(raw_item, dict) else None, None))
            return errors, entries

        if suffix == ".jsonl":
            try:
                with items_path.open("r", encoding="utf-8") as handle:
                    item_index = 0
                    for line_number, line in enumerate(handle, start=1):
                        stripped = line.strip()
                        if not stripped:
                            continue
                        item_index += 1
                        try:
                            payload = json.loads(stripped)
                        except Exception as exc:
                            entries.append(
                                (item_index, None, f"line {line_number}: invalid JSON item ({exc})")
                            )
                            continue
                        entries.append((item_index, payload if isinstance(payload, dict) else None, None))
            except Exception as exc:
                return [f"failed to read items JSONL: {exc}"], []
            return errors, entries

        return [f"unsupported curated items format: {items_path.suffix}"], []

    def _validate_item_semantics(self, item: ManualSourceItem) -> tuple[list[str], list[str]]:
        errors: list[str] = []
        warnings: list[str] = []

        if item.subject_area not in self.spec.subject_areas:
            errors.append(
                f"subject_area '{item.subject_area}' is not in spec subject_areas {self.spec.subject_areas}"
            )

        step_ids = [step.step_id for step in item.solution_steps]
        duplicate_step_ids = [
            step_id for step_id, count in Counter(step_ids).items() if count > 1
        ]
        for step_id in sorted(duplicate_step_ids):
            errors.append(f"duplicate solution step_id '{step_id}'")

        known_step_ids = set(step_ids)
        for step in item.solution_steps:
            for dependency in step.dependencies:
                if dependency not in known_step_ids:
                    errors.append(
                        f"solution step '{step.step_id}' references unknown dependency '{dependency}'"
                    )

        if item.item_format == ItemFormat.MULTIPLE_CHOICE:
            if not item.allowed_answer_forms:
                errors.append("multiple_choice items must declare allowed_answer_forms including choice_index")
            elif "choice_index" not in item.allowed_answer_forms:
                errors.append("multiple_choice items must include choice_index in allowed_answer_forms")
            try:
                answer_index = int(item.answer)
            except ValueError:
                errors.append("multiple_choice answer must be a choice index string between 1 and 5")
            else:
                if not 1 <= answer_index <= len(item.choices):
                    errors.append("multiple_choice answer index must refer to one of the five choices")
        else:
            if not item.allowed_answer_forms:
                errors.append("short_answer items must declare at least one allowed_answer_form")
            if "choice_index" in item.allowed_answer_forms:
                errors.append("short_answer items must not include choice_index in allowed_answer_forms")

        if len(item.allowed_answer_forms) != len(unique_preserve_order(item.allowed_answer_forms)):
            warnings.append("allowed_answer_forms contains duplicate values")
        if len(item.subtopics) != len(unique_preserve_order(item.subtopics)):
            warnings.append("subtopics contains duplicate values")

        try:
            build_solution_graph(item)
        except Exception as exc:
            errors.append(f"solution graph build failed: {exc}")

        if not self._matched_topic_areas(item):
            warnings.append("item does not map to any current 2028 spec skill_tag topic area")

        return unique_preserve_order(errors), unique_preserve_order(warnings)

    def _build_duplicate_report(
        self,
        *,
        scans: list[BatchScanResult],
        occurrences: list[ItemOccurrence],
    ) -> dict[str, Any]:
        batch_identity_duplicates: list[dict[str, Any]] = []
        batch_identity_conflicts: list[dict[str, Any]] = []
        source_item_duplicates: list[dict[str, Any]] = []
        source_item_conflicts: list[dict[str, Any]] = []
        error_count = 0
        warning_count = 0

        batches_by_identity: dict[tuple[str, str], list[BatchScanResult]] = defaultdict(list)
        for scan in scans:
            if scan.batch_id and scan.batch_version:
                batches_by_identity[(scan.batch_id, scan.batch_version)].append(scan)

        for (batch_id, batch_version), group in sorted(batches_by_identity.items()):
            if len(group) < 2:
                continue
            hashes = {
                scan.manifest.content_hash
                for scan in group
                if scan.manifest is not None
            }
            payload = {
                "batch_id": batch_id,
                "batch_version": batch_version,
                "occurrences": [
                    {
                        "manifest_path": self.portable_path(scan.manifest_path),
                        "items_path": (
                            self.portable_path(scan.items_path)
                            if scan.items_path is not None
                            else None
                        ),
                        "content_hash": (
                            scan.manifest.content_hash if scan.manifest is not None else None
                        ),
                    }
                    for scan in group
                ],
            }
            if len(hashes) > 1:
                batch_identity_conflicts.append(payload)
                error_count += 1
            else:
                batch_identity_duplicates.append(payload)
                warning_count += 1

        by_source_item_id: dict[str, list[ItemOccurrence]] = defaultdict(list)
        for occurrence in occurrences:
            by_source_item_id[occurrence.item.source_item_id].append(occurrence)

        for source_item_id, group in sorted(by_source_item_id.items()):
            if len(group) < 2:
                continue
            by_hash: dict[str, list[ItemOccurrence]] = defaultdict(list)
            for occurrence in group:
                by_hash[occurrence.item_hash].append(occurrence)

            payload = {
                "source_item_id": source_item_id,
                "versions": [
                    {
                        "item_hash": item_hash,
                        "occurrences": [
                            {
                                "batch_id": occurrence.batch_id,
                                "batch_version": occurrence.batch_version,
                                "manifest_path": self.portable_path(occurrence.manifest_path),
                                "items_path": self.portable_path(occurrence.items_path),
                                "index": occurrence.index,
                            }
                            for occurrence in sorted(
                                grouped_occurrences,
                                key=lambda record: (
                                    record.batch_version,
                                    record.batch_id,
                                    record.index,
                                ),
                            )
                        ],
                    }
                    for item_hash, grouped_occurrences in sorted(by_hash.items())
                ],
            }
            if len(by_hash) > 1:
                source_item_conflicts.append(payload)
                error_count += 1
            else:
                source_item_duplicates.append(payload)
                warning_count += 1

        return {
            "error_count": error_count,
            "warning_count": warning_count,
            "report": {
                "batch_identity_duplicates": batch_identity_duplicates,
                "batch_identity_conflicts": batch_identity_conflicts,
                "source_item_duplicates": source_item_duplicates,
                "source_item_conflicts": source_item_conflicts,
            },
        }

    def _retain_latest_occurrences(self, occurrences: list[ItemOccurrence]) -> list[ItemOccurrence]:
        grouped: dict[str, list[ItemOccurrence]] = defaultdict(list)
        for occurrence in occurrences:
            grouped[occurrence.item.source_item_id].append(occurrence)

        retained: list[ItemOccurrence] = []
        for source_item_id in sorted(grouped):
            by_hash: dict[str, list[ItemOccurrence]] = defaultdict(list)
            for occurrence in grouped[source_item_id]:
                by_hash[occurrence.item_hash].append(occurrence)
            versions = [
                max(group, key=self._occurrence_rank)
                for group in by_hash.values()
            ]
            retained.append(max(versions, key=self._occurrence_rank))
        return retained

    @staticmethod
    def _occurrence_rank(record: ItemOccurrence) -> tuple[float, str, str, str]:
        timestamp = (
            record.batch_created_at.timestamp()
            if record.batch_created_at is not None
            else float("-inf")
        )
        return (timestamp, record.batch_version, record.batch_id, record.item_hash)

    def _coverage_counts(self, item_cards: list[Any]) -> dict[str, Any]:
        by_domain = Counter(card.subject_area for card in item_cards)
        by_topic = Counter(card.topic for card in item_cards)
        by_answer_form: Counter[str] = Counter()
        for card in item_cards:
            answer_forms = unique_preserve_order(card.allowed_answer_forms) or [card.item_format.value]
            for answer_form in answer_forms:
                by_answer_form[answer_form] += 1

        return {
            "by_domain": dict(sorted(by_domain.items())),
            "by_topic": dict(sorted(by_topic.items())),
            "by_answer_form": dict(sorted(by_answer_form.items())),
        }

    def _build_atoms_from_occurrences(self, occurrences: list[ItemOccurrence]) -> list[InsightAtom]:
        atoms: list[InsightAtom] = []
        for occurrence in occurrences:
            item_card = build_item_card(occurrence.item, spec_id=self.spec_id)
            graph = build_solution_graph(occurrence.item)
            atoms.extend(extract_item_atoms(item_card, graph))
        return merge_atoms(atoms)

    def _family_coverage(self, atoms: list[InsightAtom]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        coverage = self.registry.coverage_report(atoms)
        unsupported_atoms = coverage["unmatched_atoms"] + coverage["ambiguous_atoms"]
        return coverage, unsupported_atoms

    def _spec_topic_area_report(self, occurrences: list[ItemOccurrence]) -> dict[str, Any]:
        covered_keys: set[tuple[str, str]] = set()
        for occurrence in occurrences:
            for area in self._matched_topic_areas(occurrence.item):
                covered_keys.add((area.subject_area, area.skill_tag))

        missing: list[dict[str, Any]] = []
        by_domain: dict[str, dict[str, Any]] = {}
        for area in self._spec_topic_areas:
            domain_entry = by_domain.setdefault(
                area.subject_area,
                {
                    "total": 0,
                    "covered": 0,
                    "missing": 0,
                    "covered_skill_tags": [],
                    "missing_skill_tags": [],
                },
            )
            domain_entry["total"] += 1

            area_key = (area.subject_area, area.skill_tag)
            if area_key in covered_keys:
                domain_entry["covered"] += 1
                domain_entry["covered_skill_tags"].append(area.skill_tag)
                continue

            domain_entry["missing"] += 1
            domain_entry["missing_skill_tags"].append(area.skill_tag)
            missing.append(
                {
                    "subject_area": area.subject_area,
                    "skill_tag": area.skill_tag,
                    "item_nos": list(area.item_nos),
                    "objectives": list(area.objectives),
                }
            )

        for entry in by_domain.values():
            entry["covered_skill_tags"] = sorted(entry["covered_skill_tags"])
            entry["missing_skill_tags"] = sorted(entry["missing_skill_tags"])

        return {
            "summary": {
                "total": len(self._spec_topic_areas),
                "covered": len(covered_keys),
                "missing": len(missing),
                "by_domain": dict(sorted(by_domain.items())),
            },
            "missing": missing,
        }

    def _matched_topic_areas(self, item: ManualSourceItem) -> list[SpecTopicArea]:
        normalized_values = {
            _normalize_text(value)
            for value in self._item_match_strings(item)
            if _normalize_text(value)
        }
        normalized_tokens: set[str] = set()
        for value in self._item_match_strings(item):
            normalized_tokens.update(_tokenize(value))

        matches: list[SpecTopicArea] = []
        for area in self._spec_topic_areas:
            skill_normalized = _normalize_text(area.skill_tag)
            if skill_normalized in normalized_values:
                matches.append(area)
                continue
            skill_tokens = _tokenize(area.skill_tag)
            if skill_tokens and skill_tokens.issubset(normalized_tokens):
                matches.append(area)
        return matches

    @staticmethod
    def _item_match_strings(item: ManualSourceItem) -> Iterable[str]:
        for value in [item.topic, item.source_label, *item.subtopics, *item.trigger_patterns, *item.diagram_tags]:
            if value:
                yield value
        for step in item.solution_steps:
            if step.label:
                yield step.label
            if step.technique:
                yield step.technique

    @staticmethod
    def _build_spec_topic_areas(spec: ExamSpec) -> list[SpecTopicArea]:
        grouped: dict[tuple[str, str], dict[str, Any]] = {}
        for blueprint in spec.default_item_blueprints:
            for skill_tag in blueprint.skill_tags:
                key = (blueprint.domain, skill_tag)
                bucket = grouped.setdefault(
                    key,
                    {
                        "item_nos": [],
                        "objectives": [],
                    },
                )
                bucket["item_nos"].append(blueprint.item_no)
                if blueprint.objective not in bucket["objectives"]:
                    bucket["objectives"].append(blueprint.objective)

        return [
            SpecTopicArea(
                subject_area=subject_area,
                skill_tag=skill_tag,
                item_nos=tuple(sorted(bucket["item_nos"])),
                objectives=tuple(bucket["objectives"]),
            )
            for (subject_area, skill_tag), bucket in sorted(grouped.items())
        ]
