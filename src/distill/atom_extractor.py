"""Insight atom extraction from item cards and solution graphs."""

from __future__ import annotations

from hashlib import sha1

from pydantic import Field

from src.core.schemas import StrictModel
from src.distill.item_card_schema import ItemCard, unique_preserve_order
from src.distill.solution_graph import SolutionGraph, SolutionNodeKind


class InsightAtom(StrictModel):
    """Reusable reasoning unit extracted from a source item."""

    atom_id: str
    label: str
    topic: str
    prerequisites: list[str] = Field(default_factory=list)
    trigger_patterns: list[str] = Field(default_factory=list)
    canonical_moves: list[str] = Field(default_factory=list)
    common_failures: list[str] = Field(default_factory=list)
    allowed_answer_forms: list[str] = Field(default_factory=list)
    diagram_tags: list[str] = Field(default_factory=list)
    difficulty_delta: int = 0
    source_item_ids: list[str] = Field(default_factory=list)
    source_step_ids: list[str] = Field(default_factory=list)


def _stable_atom_id(topic: str, label: str) -> str:
    digest = sha1(f"{topic}:{label}".encode("utf-8")).hexdigest()[:12]
    return f"atom-{digest}"


def extract_item_atoms(item_card: ItemCard, graph: SolutionGraph) -> list[InsightAtom]:
    """Extract per-step insight atoms from a solution graph."""
    atoms: list[InsightAtom] = []
    prerequisites = item_card.subtopics[:2] if item_card.subtopics else [item_card.subject_area]

    for node in graph.nodes:
        if node.kind == SolutionNodeKind.CHECK:
            continue
        label = f"{node.label} [{node.technique}]"
        atoms.append(
            InsightAtom(
                atom_id=_stable_atom_id(item_card.topic, label),
                label=label,
                topic=item_card.topic,
                prerequisites=unique_preserve_order(prerequisites),
                trigger_patterns=item_card.trigger_patterns,
                canonical_moves=unique_preserve_order([node.technique, node.content]),
                common_failures=item_card.common_failures,
                allowed_answer_forms=item_card.allowed_answer_forms,
                diagram_tags=item_card.diagram_tags,
                difficulty_delta=node.difficulty_delta,
                source_item_ids=[item_card.source_item_id],
                source_step_ids=[node.node_id],
            )
        )
    return atoms


def merge_atoms(atoms: list[InsightAtom]) -> list[InsightAtom]:
    """Merge equivalent atoms by topic and label."""
    merged: dict[str, InsightAtom] = {}
    for atom in atoms:
        key = f"{atom.topic}:{atom.label}"
        if key not in merged:
            merged[key] = atom
            continue

        current = merged[key]
        merged[key] = current.model_copy(
            update={
                "prerequisites": unique_preserve_order(current.prerequisites + atom.prerequisites),
                "trigger_patterns": unique_preserve_order(
                    current.trigger_patterns + atom.trigger_patterns
                ),
                "canonical_moves": unique_preserve_order(
                    current.canonical_moves + atom.canonical_moves
                ),
                "common_failures": unique_preserve_order(
                    current.common_failures + atom.common_failures
                ),
                "allowed_answer_forms": unique_preserve_order(
                    current.allowed_answer_forms + atom.allowed_answer_forms
                ),
                "diagram_tags": unique_preserve_order(current.diagram_tags + atom.diagram_tags),
                "difficulty_delta": max(current.difficulty_delta, atom.difficulty_delta),
                "source_item_ids": unique_preserve_order(
                    current.source_item_ids + atom.source_item_ids
                ),
                "source_step_ids": unique_preserve_order(
                    current.source_step_ids + atom.source_step_ids
                ),
            }
        )
    return sorted(merged.values(), key=lambda atom: (atom.topic, atom.label))
