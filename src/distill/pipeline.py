"""Offline distillation pipeline for CSAT mathematics source items."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.distill.atom_extractor import InsightAtom, extract_item_atoms, merge_atoms
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


def utc_now_iso() -> str:
    """Return a UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


class DistillPipelineError(Exception):
    """Raised when the distillation pipeline cannot proceed."""


class DistillPipeline:
    """Manual-ingest distillation pipeline for offline datasets."""

    def __init__(self, *, spec_id: str = "csat_math_2028") -> None:
        self.spec_id = spec_id

    def load_source_items(self, source_path: Path) -> list[ManualSourceItem]:
        """Load manually curated source items from JSON, CSV, or a directory."""
        if not source_path.exists():
            raise DistillPipelineError(f"Source path does not exist: {source_path}")
        if source_path.is_dir():
            items: list[ManualSourceItem] = []
            for child in sorted(source_path.iterdir()):
                if child.suffix.lower() not in {".json", ".csv"}:
                    continue
                items.extend(self.load_source_items(child))
            if not items:
                raise DistillPipelineError(f"No JSON/CSV files found under {source_path}")
            return items

        if source_path.suffix.lower() == ".json":
            return self._load_json_items(source_path)
        if source_path.suffix.lower() == ".csv":
            return self._load_csv_items(source_path)
        raise DistillPipelineError(f"Unsupported source format: {source_path.suffix}")

    def _load_json_items(self, source_path: Path) -> list[ManualSourceItem]:
        try:
            payload = json.loads(source_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise DistillPipelineError(f"Failed to read JSON source: {source_path}") from exc

        raw_items = payload["items"] if isinstance(payload, dict) and "items" in payload else payload
        if not isinstance(raw_items, list):
            raise DistillPipelineError("JSON source must contain a list or an object with `items`")
        return [ManualSourceItem.model_validate(item) for item in raw_items]

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

    def run(self, *, source_path: Path, output_dir: Path) -> dict[str, Any]:
        """Execute the end-to-end distillation flow and persist outputs."""
        items = self.load_source_items(source_path)
        item_cards = [build_item_card(item, spec_id=self.spec_id) for item in items]
        solution_graphs = [build_solution_graph(item) for item in items]
        atoms = self._build_atoms(item_cards, solution_graphs)
        distractors = merge_distractors(
            [distractor for item in items for distractor in extract_distractors(item)]
        )
        fingerprints = [build_item_fingerprint(card) for card in item_cards]
        duplicate_candidates = detect_near_duplicates(fingerprints)

        output_dir.mkdir(parents=True, exist_ok=True)
        item_cards_payload = self._item_cards_payload(item_cards, source_path)
        solution_graphs_payload = self._solution_graphs_payload(solution_graphs, source_path)
        atoms_payload = self._atoms_payload(atoms, source_path)
        distractors_payload = self._distractors_payload(distractors, source_path)
        topic_graph_payload = self._topic_graph_payload(item_cards, atoms)
        diagram_templates_payload = self._diagram_templates_payload(item_cards)
        style_rules_payload = self._style_rules_payload(item_cards)
        fingerprints_payload = self._fingerprints_payload(
            fingerprints, duplicate_candidates, source_path
        )

        self._write_json(output_dir / "item_cards.json", item_cards_payload)
        self._write_json(output_dir / "solution_graphs.json", solution_graphs_payload)
        self._write_json(output_dir / "atoms.json", atoms_payload)
        self._write_json(output_dir / "distractors.json", distractors_payload)
        self._write_json(output_dir / "topic_graph.json", topic_graph_payload)
        self._write_json(output_dir / "diagram_templates.json", diagram_templates_payload)
        self._write_yaml(output_dir / "style_rules.yaml", style_rules_payload)
        self._write_json(output_dir / "fingerprints.json", fingerprints_payload)

        manifest = {
            "spec_id": self.spec_id,
            "generated_at": utc_now_iso(),
            "source_path": str(source_path),
            "output_dir": str(output_dir),
            "counts": {
                "source_items": len(items),
                "item_cards": len(item_cards),
                "solution_graphs": len(solution_graphs),
                "atoms": len(atoms),
                "distractors": len(distractors),
                "fingerprints": len(fingerprints),
                "duplicate_candidates": len(duplicate_candidates),
            },
            "generated_files": [
                "item_cards.json",
                "solution_graphs.json",
                "atoms.json",
                "distractors.json",
                "topic_graph.json",
                "diagram_templates.json",
                "style_rules.yaml",
                "fingerprints.json",
            ],
        }
        self._write_json(output_dir / "manifest.json", manifest)
        return manifest

    def _build_atoms(
        self, item_cards: list[ItemCard], solution_graphs: list[SolutionGraph]
    ) -> list[InsightAtom]:
        graph_by_source = {graph.source_item_id: graph for graph in solution_graphs}
        atoms = []
        for item_card in item_cards:
            graph = graph_by_source[item_card.source_item_id]
            atoms.extend(extract_item_atoms(item_card, graph))
        return merge_atoms(atoms)

    def _item_cards_payload(self, item_cards: list[ItemCard], source_path: Path) -> dict[str, Any]:
        return {
            "spec_id": self.spec_id,
            "generated_at": utc_now_iso(),
            "source_path": str(source_path),
            "items": [item.model_dump(mode="json") for item in item_cards],
        }

    def _solution_graphs_payload(
        self, solution_graphs: list[SolutionGraph], source_path: Path
    ) -> dict[str, Any]:
        return {
            "spec_id": self.spec_id,
            "generated_at": utc_now_iso(),
            "source_path": str(source_path),
            "graphs": [graph.model_dump(mode="json") for graph in solution_graphs],
        }

    def _atoms_payload(self, atoms: list[InsightAtom], source_path: Path) -> dict[str, Any]:
        return {
            "spec_id": self.spec_id,
            "generated_at": utc_now_iso(),
            "source_path": str(source_path),
            "atoms": [atom.model_dump(mode="json") for atom in atoms],
        }

    def _distractors_payload(
        self, distractors: list[DistractorAtom], source_path: Path
    ) -> dict[str, Any]:
        return {
            "spec_id": self.spec_id,
            "generated_at": utc_now_iso(),
            "source_path": str(source_path),
            "distractors": [distractor.model_dump(mode="json") for distractor in distractors],
        }

    def _topic_graph_payload(
        self, item_cards: list[ItemCard], atoms: list[InsightAtom]
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

        return {
            "spec_id": self.spec_id,
            "generated_at": utc_now_iso(),
            "nodes": sorted(nodes.values(), key=lambda node: (node["node_type"], node["label"])),
            "edges": sorted(
                edges.values(),
                key=lambda edge: (edge["relation"], edge["from"], edge["to"]),
            ),
        }

    def _diagram_templates_payload(self, item_cards: list[ItemCard]) -> dict[str, Any]:
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
        return {
            "spec_id": self.spec_id,
            "generated_at": utc_now_iso(),
            "templates": sorted(templates.values(), key=lambda item: item["diagram_tag"]),
        }

    def _style_rules_payload(self, item_cards: list[ItemCard]) -> dict[str, Any]:
        shared_style_notes = unique_preserve_order(
            [note for card in item_cards for note in card.style_notes]
        )
        diagram_tags = unique_preserve_order([tag for card in item_cards for tag in card.diagram_tags])
        return {
            "version": "1.0",
            "spec_id": self.spec_id,
            "generated_at": utc_now_iso(),
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
    ) -> dict[str, Any]:
        return {
            "spec_id": self.spec_id,
            "generated_at": utc_now_iso(),
            "source_path": str(source_path),
            "items": [fingerprint.model_dump(mode="json") for fingerprint in fingerprints],
            "candidate_pairs": [
                candidate.model_dump(mode="json") for candidate in duplicate_candidates
            ],
        }

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
