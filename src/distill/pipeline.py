"""Offline distillation pipeline for CSAT mathematics source items."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from src.distill.atom_extractor import InsightAtom, extract_item_atoms, merge_atoms
from src.distill.curated_batch import (
    CURATED_BATCH_MANIFEST_VERSION,
    LoadedCuratedBatch,
    is_curated_batch_manifest_payload,
    load_curated_batch,
    load_curated_items,
    stable_hash_from_value,
)
from src.distill.distractor_extractor import DistractorAtom, extract_distractors, merge_distractors
from src.distill.fingerprint import (
    ItemFingerprint,
    NearDuplicateCandidate,
    build_item_fingerprint,
    detect_near_duplicates,
)
from src.distill.item_card_schema import (
    ItemCard,
    ManualSourceDistractor,
    ManualSourceItem,
    ManualSourceStep,
    build_item_card,
    unique_preserve_order,
)
from src.distill.solution_graph import SolutionGraph, build_solution_graph


RECORD_PROVENANCE_FIELDS = {
    "record_version",
    "source_batch_ids",
    "source_batch_versions",
    "source_batch_hashes",
}


def utc_now_iso() -> str:
    """Return a UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class SourceItemRecord:
    """Validated source item plus optional curated-batch provenance."""

    item: ManualSourceItem
    item_hash: str
    source_paths: tuple[Path, ...]
    manifest_paths: tuple[Path, ...] = ()
    batch_ids: tuple[str, ...] = ()
    batch_versions: tuple[str, ...] = ()
    batch_hashes: tuple[str, ...] = ()
    batch_created_at: datetime | None = None


class DistillPipelineError(Exception):
    """Raised when the distillation pipeline cannot proceed."""


class DistillPipeline:
    """Manual-ingest distillation pipeline for offline datasets."""

    def __init__(self, *, spec_id: str = "csat_math_2028", repo_root: Path | None = None) -> None:
        self.spec_id = spec_id
        self.repo_root = repo_root.resolve() if repo_root is not None else None

    def load_source_items(self, source_path: Path) -> list[ManualSourceItem]:
        """Load manually curated source items from JSON, JSONL, CSV, or a directory."""
        if not source_path.exists():
            raise DistillPipelineError(f"Source path does not exist: {source_path}")
        if source_path.is_dir():
            items: list[ManualSourceItem] = []
            for child in sorted(source_path.iterdir()):
                if child.suffix.lower() not in {".json", ".jsonl", ".csv"}:
                    continue
                items.extend(self.load_source_items(child))
            if not items:
                raise DistillPipelineError(f"No JSON/JSONL/CSV files found under {source_path}")
            return items

        if source_path.suffix.lower() == ".json":
            return self._load_json_items(source_path)
        if source_path.suffix.lower() == ".jsonl":
            return self._load_jsonl_items(source_path)
        if source_path.suffix.lower() == ".csv":
            return self._load_csv_items(source_path)
        raise DistillPipelineError(f"Unsupported source format: {source_path.suffix}")

    def load_curated_batches(self, batch_path: Path) -> list[LoadedCuratedBatch]:
        """Load curated batch manifests from a manifest file or a directory tree."""
        if not batch_path.exists():
            raise DistillPipelineError(f"Curated batch path does not exist: {batch_path}")

        manifest_paths: list[Path]
        if batch_path.is_file():
            manifest_paths = [batch_path]
        else:
            manifest_paths = sorted(batch_path.rglob("*.manifest.json"))
            if not manifest_paths:
                manifest_paths = []
                for candidate in sorted(batch_path.rglob("*.json")):
                    try:
                        payload = json.loads(candidate.read_text(encoding="utf-8"))
                    except Exception:
                        continue
                    if is_curated_batch_manifest_payload(payload):
                        manifest_paths.append(candidate)
            if not manifest_paths:
                raise DistillPipelineError(
                    f"No curated batch manifests found under {batch_path}"
                )

        batches: list[LoadedCuratedBatch] = []
        for manifest_path in manifest_paths:
            try:
                batches.append(load_curated_batch(manifest_path))
            except ValueError as exc:
                raise DistillPipelineError(str(exc)) from exc
        return batches

    def validate_curated_batches(self, batch_path: Path) -> dict[str, Any]:
        """Validate curated batch manifests against their referenced item payloads."""
        batches = self.load_curated_batches(batch_path)
        return self._build_batch_validation_report(batches=batches, batch_path=batch_path)

    def run(self, *, source_path: Path, output_dir: Path) -> dict[str, Any]:
        """Execute the legacy single-source distillation flow and persist outputs."""
        items = self.load_source_items(source_path)
        source_records = [
            SourceItemRecord(
                item=item,
                item_hash=stable_hash_from_value(item.model_dump(mode="json")),
                source_paths=(source_path,),
            )
            for item in items
        ]
        return self._run_records(
            source_records=source_records,
            output_dir=output_dir,
            source_path=source_path,
            source_batches=[],
            batch_validation=None,
        )

    def run_batches(self, *, batch_path: Path, output_dir: Path) -> dict[str, Any]:
        """Execute distillation over one or more curated source batches."""
        batches = self.load_curated_batches(batch_path)
        batch_validation = self._build_batch_validation_report(
            batches=batches,
            batch_path=batch_path,
        )
        if not batch_validation["valid"]:
            problems = [
                f"{entry['batch_id']}: {', '.join(entry['errors'])}"
                for entry in batch_validation["batches"]
                if entry["errors"]
            ]
            joined = "; ".join(problems) if problems else "unknown validation error"
            raise DistillPipelineError(f"Curated batch validation failed: {joined}")

        source_records: list[SourceItemRecord] = []
        for batch in batches:
            for item in batch.items:
                source_records.append(
                    SourceItemRecord(
                        item=item,
                        item_hash=stable_hash_from_value(item.model_dump(mode="json")),
                        source_paths=(batch.items_path,),
                        manifest_paths=(batch.manifest_path,),
                        batch_ids=(batch.manifest.batch_id,),
                        batch_versions=(batch.manifest.batch_version,),
                        batch_hashes=(batch.manifest.content_hash,),
                        batch_created_at=batch.manifest.created_at,
                    )
                )

        return self._run_records(
            source_records=source_records,
            output_dir=output_dir,
            source_path=batch_path,
            source_batches=batches,
            batch_validation=batch_validation,
        )

    def coverage_stats_from_distilled_dir(self, distilled_dir: Path) -> dict[str, Any]:
        """Read coverage statistics from distilled outputs."""
        item_cards_path = distilled_dir / "item_cards.json"
        if not item_cards_path.exists():
            raise DistillPipelineError(f"Missing distilled item cards: {item_cards_path}")

        item_cards_payload = json.loads(item_cards_path.read_text(encoding="utf-8"))
        item_cards = [
            ItemCard.model_validate(item) for item in item_cards_payload.get("items", [])
        ]
        manifest_path = distilled_dir / "manifest.json"
        manifest_payload: dict[str, Any] = {}
        if manifest_path.exists():
            manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))

        coverage = self._coverage_stats(item_cards)
        return {
            "spec_id": item_cards_payload.get("spec_id", self.spec_id),
            "distilled_dir": self.portable_path(distilled_dir),
            "counts": {
                "item_cards": len(item_cards),
                "duplicate_candidates": manifest_payload.get("counts", {}).get(
                    "duplicate_candidates",
                    manifest_payload.get("dedup", {}).get("near_duplicate_candidates", 0),
                ),
            },
            "coverage": coverage,
            "source_batches": manifest_payload.get("source_batches", []),
        }

    def _load_json_items(self, source_path: Path) -> list[ManualSourceItem]:
        try:
            payload = json.loads(source_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise DistillPipelineError(f"Failed to read JSON source: {source_path}") from exc

        if is_curated_batch_manifest_payload(payload):
            raise DistillPipelineError(
                f"Curated batch manifest provided to legacy source loader: {source_path}. "
                "Use `distill validate-batches` or `distill run-batches`."
            )
        raw_items = payload["items"] if isinstance(payload, dict) and "items" in payload else payload
        if not isinstance(raw_items, list):
            raise DistillPipelineError("JSON source must contain a list or an object with `items`")
        return [ManualSourceItem.model_validate(item) for item in raw_items]

    def _load_jsonl_items(self, source_path: Path) -> list[ManualSourceItem]:
        try:
            return load_curated_items(source_path)
        except ValueError as exc:
            raise DistillPipelineError(str(exc)) from exc

    def _load_csv_items(self, source_path: Path) -> list[ManualSourceItem]:
        try:
            with source_path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)
        except Exception as exc:
            raise DistillPipelineError(f"Failed to read CSV source: {source_path}") from exc

        if not rows:
            raise DistillPipelineError(f"CSV source is empty: {source_path}")

        items: list[ManualSourceItem] = []
        for row in rows:
            item_dict = self._row_to_manual_source_item(row)
            items.append(ManualSourceItem.model_validate(item_dict))
        return items

    def _row_to_manual_source_item(self, row: dict[str, str]) -> dict[str, Any]:
        """Parse a CSV row into a ManualSourceItem-compatible dictionary."""
        list_fields = {
            "subtopics",
            "choices",
            "diagram_tags",
            "style_notes",
            "allowed_answer_forms",
            "trigger_patterns",
        }
        json_fields = {"solution_steps", "distractors", "source_metadata"}
        int_fields = {"source_year", "score"}

        parsed: dict[str, Any] = {}
        for key, raw_value in row.items():
            value = (raw_value or "").strip()
            if key in int_fields:
                parsed[key] = int(value) if value else None
            elif key in list_fields:
                parsed[key] = self._parse_list_field(value)
            elif key in json_fields:
                parsed[key] = json.loads(value) if value else ([] if key != "source_metadata" else {})
            else:
                parsed[key] = value

        parsed["solution_steps"] = [
            ManualSourceStep.model_validate(step).model_dump(mode="json")
            for step in parsed["solution_steps"]
        ]
        parsed["distractors"] = [
            ManualSourceDistractor.model_validate(distractor).model_dump(mode="json")
            for distractor in parsed["distractors"]
        ]
        return parsed

    @staticmethod
    def _parse_list_field(value: str) -> list[str]:
        if not value:
            return []
        if value.startswith("["):
            parsed = json.loads(value)
            if not isinstance(parsed, list):
                raise DistillPipelineError("Expected JSON list in CSV field")
            return [str(item) for item in parsed]
        return [token.strip() for token in value.split("|") if token.strip()]

    def _run_records(
        self,
        *,
        source_records: list[SourceItemRecord],
        output_dir: Path,
        source_path: Path,
        source_batches: list[LoadedCuratedBatch],
        batch_validation: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if not source_records:
            raise DistillPipelineError("No source items were loaded for distillation")

        deduped_records, item_dedup_stats, version_history = self._dedupe_source_records(
            source_records
        )
        item_cards = [self._build_item_card_record(record) for record in deduped_records]
        solution_graphs = [build_solution_graph(record.item) for record in deduped_records]
        atoms, atom_dedup_stats = self._build_atoms(item_cards, solution_graphs)
        distractors, distractor_dedup_stats = self._build_distractors(deduped_records)
        fingerprints = [self._build_fingerprint(card) for card in item_cards]
        duplicate_candidates = detect_near_duplicates(fingerprints)
        coverage = self._coverage_stats(item_cards)

        output_dir.mkdir(parents=True, exist_ok=True)
        item_cards_payload = self._item_cards_payload(item_cards, source_path, source_batches)
        solution_graphs_payload = self._solution_graphs_payload(
            solution_graphs,
            source_path,
            source_batches,
        )
        atoms_payload = self._atoms_payload(atoms, source_path, source_batches)
        distractors_payload = self._distractors_payload(distractors, source_path, source_batches)
        topic_graph_payload = self._topic_graph_payload(item_cards, atoms, source_path, source_batches)
        diagram_templates_payload = self._diagram_templates_payload(
            item_cards,
            source_path,
            source_batches,
        )
        style_rules_payload = self._style_rules_payload(item_cards, source_path, source_batches)
        fingerprints_payload = self._fingerprints_payload(
            fingerprints,
            duplicate_candidates,
            source_path,
            source_batches,
        )

        generated_paths = {
            "item_cards.json": output_dir / "item_cards.json",
            "solution_graphs.json": output_dir / "solution_graphs.json",
            "atoms.json": output_dir / "atoms.json",
            "distractors.json": output_dir / "distractors.json",
            "topic_graph.json": output_dir / "topic_graph.json",
            "diagram_templates.json": output_dir / "diagram_templates.json",
            "style_rules.yaml": output_dir / "style_rules.yaml",
            "fingerprints.json": output_dir / "fingerprints.json",
        }

        self._write_json(generated_paths["item_cards.json"], item_cards_payload)
        self._write_json(generated_paths["solution_graphs.json"], solution_graphs_payload)
        self._write_json(generated_paths["atoms.json"], atoms_payload)
        self._write_json(generated_paths["distractors.json"], distractors_payload)
        self._write_json(generated_paths["topic_graph.json"], topic_graph_payload)
        self._write_json(generated_paths["diagram_templates.json"], diagram_templates_payload)
        self._write_yaml(generated_paths["style_rules.yaml"], style_rules_payload)
        self._write_json(generated_paths["fingerprints.json"], fingerprints_payload)

        generated_files = [
            {
                "path": self.portable_path(path),
                "sha256": self._hash_file(path),
            }
            for path in generated_paths.values()
        ]

        manifest = {
            "manifest_version": CURATED_BATCH_MANIFEST_VERSION,
            "spec_id": self.spec_id,
            "generated_at": utc_now_iso(),
            "mode": "curated_batches" if source_batches else "single_source",
            "source_path": self.portable_path(source_path),
            "output_dir": self.portable_path(output_dir),
            "source_batch_hashes": [batch.manifest.content_hash for batch in source_batches],
            "source_batches": self._source_batches_summary(source_batches),
            "counts": {
                "source_items": len(source_records),
                "retained_source_items": len(deduped_records),
                "item_cards": len(item_cards),
                "solution_graphs": len(solution_graphs),
                "atoms": len(atoms),
                "distractors": len(distractors),
                "fingerprints": len(fingerprints),
                "duplicate_candidates": len(duplicate_candidates),
            },
            "coverage": coverage,
            "dedup": {
                "item_cards": item_dedup_stats,
                "insight_atoms": atom_dedup_stats,
                "distractor_atoms": distractor_dedup_stats,
                "fingerprints": {
                    "input": len(item_cards),
                    "output": len(fingerprints),
                    "duplicates_removed": 0,
                },
                "near_duplicate_candidates": len(duplicate_candidates),
            },
            "version_history": version_history,
            "generated_files": generated_files,
        }
        if batch_validation is not None:
            manifest["batch_validation"] = batch_validation

        self._write_json(output_dir / "manifest.json", manifest)
        return manifest

    def _dedupe_source_records(
        self, source_records: list[SourceItemRecord]
    ) -> tuple[list[SourceItemRecord], dict[str, int], list[dict[str, Any]]]:
        grouped: dict[str, list[SourceItemRecord]] = defaultdict(list)
        for record in source_records:
            grouped[record.item.source_item_id].append(record)

        retained_records: list[SourceItemRecord] = []
        exact_duplicates = 0
        superseded_versions = 0
        version_groups = 0
        version_history: list[dict[str, Any]] = []

        for source_item_id in sorted(grouped):
            record_group = grouped[source_item_id]
            versions_by_hash: dict[str, list[SourceItemRecord]] = defaultdict(list)
            for record in record_group:
                versions_by_hash[record.item_hash].append(record)

            exact_duplicates += sum(len(records) - 1 for records in versions_by_hash.values())
            merged_versions = [
                self._merge_source_record_group(records)
                for _, records in sorted(versions_by_hash.items(), key=lambda item: item[0])
            ]
            winner = max(merged_versions, key=self._source_record_rank)
            retained_records.append(winner)

            if len(merged_versions) > 1:
                version_groups += 1
                superseded_versions += len(merged_versions) - 1

            if len(merged_versions) > 1 or any(len(records) > 1 for records in versions_by_hash.values()):
                version_history.append(
                    {
                        "source_item_id": source_item_id,
                        "retained_item_hash": winner.item_hash,
                        "retained_batch_ids": list(winner.batch_ids),
                        "retained_batch_versions": list(winner.batch_versions),
                        "exact_duplicate_records": sum(
                            len(records) - 1 for records in versions_by_hash.values()
                        ),
                        "versions": [
                            {
                                "item_hash": merged.item_hash,
                                "batch_ids": list(merged.batch_ids),
                                "batch_versions": list(merged.batch_versions),
                                "batch_hashes": list(merged.batch_hashes),
                                "source_paths": [
                                    self.portable_path(path) for path in merged.source_paths
                                ],
                                "manifest_paths": [
                                    self.portable_path(path) for path in merged.manifest_paths
                                ],
                            }
                            for merged in sorted(
                                merged_versions,
                                key=self._source_record_rank,
                                reverse=True,
                            )
                        ],
                    }
                )

        stats = {
            "input": len(source_records),
            "output": len(retained_records),
            "exact_duplicates": exact_duplicates,
            "superseded_versions": superseded_versions,
            "version_groups": version_groups,
        }
        return sorted(retained_records, key=lambda record: record.item.source_item_id), stats, version_history

    def _merge_source_record_group(self, records: list[SourceItemRecord]) -> SourceItemRecord:
        winner = max(records, key=self._source_record_rank)
        return SourceItemRecord(
            item=winner.item,
            item_hash=winner.item_hash,
            source_paths=self._unique_paths(path for record in records for path in record.source_paths),
            manifest_paths=self._unique_paths(
                path for record in records for path in record.manifest_paths
            ),
            batch_ids=tuple(
                unique_preserve_order(
                    [batch_id for record in records for batch_id in record.batch_ids]
                )
            ),
            batch_versions=tuple(
                unique_preserve_order(
                    [version for record in records for version in record.batch_versions]
                )
            ),
            batch_hashes=tuple(
                unique_preserve_order(
                    [batch_hash for record in records for batch_hash in record.batch_hashes]
                )
            ),
            batch_created_at=self._latest_batch_created_at(records),
        )

    @staticmethod
    def _latest_batch_created_at(records: list[SourceItemRecord]) -> datetime | None:
        timestamps = [record.batch_created_at for record in records if record.batch_created_at]
        return max(timestamps) if timestamps else None

    @staticmethod
    def _unique_paths(paths: Any) -> tuple[Path, ...]:
        seen: set[Path] = set()
        ordered: list[Path] = []
        for path in paths:
            resolved = Path(path)
            if resolved in seen:
                continue
            seen.add(resolved)
            ordered.append(resolved)
        return tuple(ordered)

    @staticmethod
    def _source_record_rank(record: SourceItemRecord) -> tuple[float, str, str, str]:
        timestamp = (
            record.batch_created_at.timestamp()
            if record.batch_created_at is not None
            else float("-inf")
        )
        last_batch_version = record.batch_versions[-1] if record.batch_versions else ""
        last_batch_id = record.batch_ids[-1] if record.batch_ids else ""
        return (timestamp, last_batch_version, last_batch_id, record.item_hash)

    def _build_item_card_record(self, record: SourceItemRecord) -> ItemCard:
        item_card = build_item_card(record.item, spec_id=self.spec_id).model_copy(
            update={
                "source_batch_ids": list(record.batch_ids),
                "source_batch_versions": list(record.batch_versions),
                "source_batch_hashes": list(record.batch_hashes),
            }
        )
        return self._with_record_version(item_card, exclude_fields={"card_id"} | RECORD_PROVENANCE_FIELDS)

    def _build_atoms(
        self,
        item_cards: list[ItemCard],
        solution_graphs: list[SolutionGraph],
    ) -> tuple[list[InsightAtom], dict[str, int]]:
        graph_by_source = {graph.source_item_id: graph for graph in solution_graphs}
        raw_atoms: list[InsightAtom] = []
        for item_card in item_cards:
            graph = graph_by_source[item_card.source_item_id]
            extracted = extract_item_atoms(item_card, graph)
            raw_atoms.extend(
                atom.model_copy(
                    update={
                        "source_batch_ids": item_card.source_batch_ids,
                        "source_batch_versions": item_card.source_batch_versions,
                        "source_batch_hashes": item_card.source_batch_hashes,
                    }
                )
                for atom in extracted
            )

        merged_atoms = [
            self._with_record_version(atom, exclude_fields=RECORD_PROVENANCE_FIELDS)
            for atom in merge_atoms(raw_atoms)
        ]
        stats = {
            "input": len(raw_atoms),
            "output": len(merged_atoms),
            "duplicates_removed": max(0, len(raw_atoms) - len(merged_atoms)),
        }
        return merged_atoms, stats

    def _build_distractors(
        self, source_records: list[SourceItemRecord]
    ) -> tuple[list[DistractorAtom], dict[str, int]]:
        raw_distractors: list[DistractorAtom] = []
        for record in source_records:
            extracted = extract_distractors(record.item)
            raw_distractors.extend(
                distractor.model_copy(
                    update={
                        "source_batch_ids": list(record.batch_ids),
                        "source_batch_versions": list(record.batch_versions),
                        "source_batch_hashes": list(record.batch_hashes),
                    }
                )
                for distractor in extracted
            )

        merged_distractors = [
            self._with_record_version(distractor, exclude_fields=RECORD_PROVENANCE_FIELDS)
            for distractor in merge_distractors(raw_distractors)
        ]
        stats = {
            "input": len(raw_distractors),
            "output": len(merged_distractors),
            "duplicates_removed": max(0, len(raw_distractors) - len(merged_distractors)),
        }
        return merged_distractors, stats

    def _build_fingerprint(self, item_card: ItemCard) -> ItemFingerprint:
        fingerprint = build_item_fingerprint(item_card)
        return self._with_record_version(
            fingerprint,
            exclude_fields={"fingerprint_id", "card_id"} | RECORD_PROVENANCE_FIELDS,
        )

    @staticmethod
    def _with_record_version(model: Any, *, exclude_fields: set[str]) -> Any:
        payload = model.model_dump(mode="json", exclude=exclude_fields)
        return model.model_copy(update={"record_version": stable_hash_from_value(payload)})

    def _coverage_stats(self, item_cards: list[ItemCard]) -> dict[str, dict[str, int]]:
        by_domain = Counter(card.subject_area for card in item_cards)
        by_topic = Counter(card.topic for card in item_cards)
        by_difficulty = Counter(card.difficulty.value for card in item_cards)
        by_answer_form: Counter[str] = Counter()
        for card in item_cards:
            answer_forms = unique_preserve_order(card.allowed_answer_forms) or [card.item_format.value]
            for answer_form in answer_forms:
                by_answer_form[answer_form] += 1

        return {
            "by_domain": dict(sorted(by_domain.items())),
            "by_topic": dict(sorted(by_topic.items())),
            "by_difficulty": dict(sorted(by_difficulty.items())),
            "by_answer_form": dict(sorted(by_answer_form.items())),
        }

    def _payload_header(
        self,
        *,
        source_path: Path,
        source_batches: list[LoadedCuratedBatch],
    ) -> dict[str, Any]:
        return {
            "manifest_version": CURATED_BATCH_MANIFEST_VERSION,
            "spec_id": self.spec_id,
            "generated_at": utc_now_iso(),
            "source_path": self.portable_path(source_path),
            "source_batches": self._source_batches_summary(source_batches),
        }

    def _item_cards_payload(
        self,
        item_cards: list[ItemCard],
        source_path: Path,
        source_batches: list[LoadedCuratedBatch],
    ) -> dict[str, Any]:
        return self._payload_header(source_path=source_path, source_batches=source_batches) | {
            "items": [item.model_dump(mode="json") for item in item_cards],
        }

    def _solution_graphs_payload(
        self,
        solution_graphs: list[SolutionGraph],
        source_path: Path,
        source_batches: list[LoadedCuratedBatch],
    ) -> dict[str, Any]:
        return self._payload_header(source_path=source_path, source_batches=source_batches) | {
            "graphs": [graph.model_dump(mode="json") for graph in solution_graphs],
        }

    def _atoms_payload(
        self,
        atoms: list[InsightAtom],
        source_path: Path,
        source_batches: list[LoadedCuratedBatch],
    ) -> dict[str, Any]:
        return self._payload_header(source_path=source_path, source_batches=source_batches) | {
            "atoms": [atom.model_dump(mode="json") for atom in atoms],
        }

    def _distractors_payload(
        self,
        distractors: list[DistractorAtom],
        source_path: Path,
        source_batches: list[LoadedCuratedBatch],
    ) -> dict[str, Any]:
        return self._payload_header(source_path=source_path, source_batches=source_batches) | {
            "distractors": [distractor.model_dump(mode="json") for distractor in distractors],
        }

    def _topic_graph_payload(
        self,
        item_cards: list[ItemCard],
        atoms: list[InsightAtom],
        source_path: Path,
        source_batches: list[LoadedCuratedBatch],
    ) -> dict[str, Any]:
        nodes: dict[str, dict[str, Any]] = {}
        edges: dict[tuple[str, str, str], dict[str, Any]] = {}

        def add_node(node_id: str, label: str, node_type: str) -> None:
            if node_id not in nodes:
                nodes[node_id] = {
                    "node_id": node_id,
                    "label": label,
                    "node_type": node_type,
                    "source_count": 0,
                }
            nodes[node_id]["source_count"] += 1

        def add_edge(from_id: str, to_id: str, relation: str) -> None:
            key = (from_id, to_id, relation)
            if key not in edges:
                edges[key] = {
                    "from": from_id,
                    "to": to_id,
                    "relation": relation,
                    "weight": 0,
                }
            edges[key]["weight"] += 1

        for card in item_cards:
            area_id = f"area:{card.subject_area}"
            topic_id = f"topic:{card.topic}"
            add_node(area_id, card.subject_area, "subject_area")
            add_node(topic_id, card.topic, "topic")
            add_edge(area_id, topic_id, "contains")
            for subtopic in card.subtopics:
                subtopic_id = f"subtopic:{subtopic}"
                add_node(subtopic_id, subtopic, "subtopic")
                add_edge(subtopic_id, topic_id, "supports")

        for atom in atoms:
            topic_id = f"topic:{atom.topic}"
            for prerequisite in atom.prerequisites:
                prereq_id = f"subtopic:{prerequisite}"
                add_node(prereq_id, prerequisite, "subtopic")
                add_edge(prereq_id, topic_id, "prerequisite")

        return self._payload_header(source_path=source_path, source_batches=source_batches) | {
            "nodes": sorted(nodes.values(), key=lambda node: (node["node_type"], node["label"])),
            "edges": sorted(
                edges.values(),
                key=lambda edge: (edge["relation"], edge["from"], edge["to"]),
            ),
        }

    def _diagram_templates_payload(
        self,
        item_cards: list[ItemCard],
        source_path: Path,
        source_batches: list[LoadedCuratedBatch],
    ) -> dict[str, Any]:
        templates: dict[str, dict[str, Any]] = {}
        for card in item_cards:
            for tag in card.diagram_tags:
                if tag not in templates:
                    templates[tag] = {
                        "diagram_tag": tag,
                        "usage_count": 0,
                        "applicable_topics": [],
                        "source_item_ids": [],
                        "notes": [],
                    }
                template = templates[tag]
                template["usage_count"] += 1
                template["applicable_topics"] = unique_preserve_order(
                    template["applicable_topics"] + [card.topic]
                )
                template["source_item_ids"] = unique_preserve_order(
                    template["source_item_ids"] + [card.source_item_id]
                )
                template["notes"] = unique_preserve_order(
                    template["notes"]
                    + [note for note in card.style_notes if "도표" in note or "그래프" in note]
                )
        return self._payload_header(source_path=source_path, source_batches=source_batches) | {
            "templates": sorted(templates.values(), key=lambda item: item["diagram_tag"]),
        }

    def _style_rules_payload(
        self,
        item_cards: list[ItemCard],
        source_path: Path,
        source_batches: list[LoadedCuratedBatch],
    ) -> dict[str, Any]:
        shared_style_notes = unique_preserve_order(
            [note for card in item_cards for note in card.style_notes]
        )
        diagram_tags = unique_preserve_order([tag for card in item_cards for tag in card.diagram_tags])
        return self._payload_header(source_path=source_path, source_batches=source_batches) | {
            "version": "1.0",
            "language": "ko-KR",
            "register": "formal_exam",
            "stem_rules": [
                "조건은 짧은 문장 단위로 나누고 핵심 수식은 한 번만 제시한다.",
                "정의역, 단조성, 경우의 수 조건처럼 오답 유도에 중요한 제약은 stem에 직접 넣는다.",
            ],
            "multiple_choice_rules": [
                "선택지는 계산 실수형, 개념 오해형, 정의역 누락형이 섞이되 정답 위치 패턴이 반복되지 않게 한다.",
                "너무 노골적인 함정 선택지는 금지한다.",
            ],
            "short_answer_rules": [
                "정답 형식은 정수, 유리수, 식, 구간 값 등 허용 형태를 item card에 명시한다.",
                "단답형은 답만 쓰게 하더라도 풀이 경로는 검증 가능해야 한다.",
            ],
            "diagram_rules": [
                f"사용 가능한 diagram tag는 {', '.join(diagram_tags)} 범위에서 관리한다.",
                "도표나 그래프는 핵심 추론에 직접 기여할 때만 사용한다.",
            ],
            "provenance_rules": [
                "raw source PDF는 runtime에서 직접 사용하지 않는다.",
                "distillation 결과만 JSON/YAML dataset으로 runtime에 전달한다.",
            ],
            "observed_style_notes": shared_style_notes,
        }

    def _fingerprints_payload(
        self,
        fingerprints: list[ItemFingerprint],
        duplicate_candidates: list[NearDuplicateCandidate],
        source_path: Path,
        source_batches: list[LoadedCuratedBatch],
    ) -> dict[str, Any]:
        return self._payload_header(source_path=source_path, source_batches=source_batches) | {
            "items": [fingerprint.model_dump(mode="json") for fingerprint in fingerprints],
            "candidate_pairs": [
                candidate.model_dump(mode="json") for candidate in duplicate_candidates
            ],
        }

    def _build_batch_validation_report(
        self,
        *,
        batches: list[LoadedCuratedBatch],
        batch_path: Path,
    ) -> dict[str, Any]:
        entries: list[dict[str, Any]] = []
        valid = True
        total_items = 0
        for batch in batches:
            errors: list[str] = []
            if batch.manifest.manifest_version != CURATED_BATCH_MANIFEST_VERSION:
                errors.append(
                    "unsupported manifest_version "
                    f"{batch.manifest.manifest_version}; expected {CURATED_BATCH_MANIFEST_VERSION}"
                )
            if batch.manifest.spec_id != self.spec_id:
                errors.append(
                    f"spec_id mismatch: manifest={batch.manifest.spec_id}, pipeline={self.spec_id}"
                )
            if batch.manifest.item_count != batch.computed_item_count:
                errors.append(
                    f"item_count mismatch: declared={batch.manifest.item_count}, "
                    f"computed={batch.computed_item_count}"
                )
            if batch.manifest.content_hash != batch.computed_content_hash:
                errors.append(
                    f"content_hash mismatch: declared={batch.manifest.content_hash}, "
                    f"computed={batch.computed_content_hash}"
                )

            valid = valid and not errors
            total_items += batch.computed_item_count
            entries.append(
                {
                    "batch_id": batch.manifest.batch_id,
                    "batch_version": batch.manifest.batch_version,
                    "manifest_version": batch.manifest.manifest_version,
                    "manifest_path": self.portable_path(batch.manifest_path),
                    "items_path": self.portable_path(batch.items_path),
                    "declared_item_count": batch.manifest.item_count,
                    "computed_item_count": batch.computed_item_count,
                    "declared_content_hash": batch.manifest.content_hash,
                    "computed_content_hash": batch.computed_content_hash,
                    "provenance": batch.manifest.provenance.model_dump(mode="json"),
                    "errors": errors,
                }
            )

        return {
            "spec_id": self.spec_id,
            "batch_root": self.portable_path(batch_path),
            "batch_count": len(batches),
            "item_count": total_items,
            "valid": valid,
            "batches": entries,
        }

    def _source_batches_summary(self, source_batches: list[LoadedCuratedBatch]) -> list[dict[str, Any]]:
        return [
            {
                "batch_id": batch.manifest.batch_id,
                "batch_version": batch.manifest.batch_version,
                "manifest_version": batch.manifest.manifest_version,
                "created_at": (
                    batch.manifest.created_at.isoformat()
                    if batch.manifest.created_at is not None
                    else None
                ),
                "manifest_path": self.portable_path(batch.manifest_path),
                "items_path": self.portable_path(batch.items_path),
                "item_count": batch.manifest.item_count,
                "content_hash": batch.manifest.content_hash,
                "provenance": batch.manifest.provenance.model_dump(mode="json"),
            }
            for batch in source_batches
        ]

    def portable_path(self, path: Path) -> str:
        resolved = path.resolve()
        if self.repo_root is not None:
            try:
                return resolved.relative_to(self.repo_root).as_posix()
            except ValueError:
                pass
        return str(path)

    @staticmethod
    def _hash_file(path: Path) -> str:
        return f"sha256:{sha256(path.read_bytes()).hexdigest()}"

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _write_yaml(self, path: Path, payload: dict[str, Any]) -> None:
        path.write_text(self._yaml_from_value(payload) + "\n", encoding="utf-8")

    def _yaml_from_value(self, value: Any, *, indent: int = 0) -> str:
        """Serialize simple nested data structures to YAML 1.2-compatible text."""
        prefix = " " * indent
        if isinstance(value, dict):
            lines: list[str] = []
            for key, item in value.items():
                if self._is_scalar(item):
                    lines.append(f"{prefix}{key}: {self._yaml_scalar(item)}")
                else:
                    lines.append(f"{prefix}{key}:")
                    lines.append(self._yaml_from_value(item, indent=indent + 2))
            return "\n".join(lines)
        if isinstance(value, list):
            if not value:
                return f"{prefix}[]"
            lines = []
            for item in value:
                if self._is_scalar(item):
                    lines.append(f"{prefix}- {self._yaml_scalar(item)}")
                else:
                    lines.append(f"{prefix}-")
                    lines.append(self._yaml_from_value(item, indent=indent + 2))
            return "\n".join(lines)
        return f"{prefix}{self._yaml_scalar(value)}"

    @staticmethod
    def _is_scalar(value: Any) -> bool:
        return value is None or isinstance(value, (str, int, float, bool))

    @staticmethod
    def _yaml_scalar(value: Any) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        return json.dumps(str(value), ensure_ascii=False)
