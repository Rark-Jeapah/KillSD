"""Distractor atom extraction from manual source annotations."""

from __future__ import annotations

from hashlib import sha1

from pydantic import Field

from src.core.schemas import StrictModel
from src.distill.item_card_schema import ManualSourceItem, unique_preserve_order


class DistractorAtom(StrictModel):
    """Reusable wrong-answer pattern used during generation and validation."""

    distractor_id: str
    error_type: str
    trigger: str
    wrong_move: str
    plausible_choice_shape: str
    reject_if_too_obvious: bool
    topic: str
    source_item_ids: list[str] = Field(default_factory=list)


def _stable_distractor_id(
    *, error_type: str, trigger: str, wrong_move: str, topic: str
) -> str:
    digest = sha1(f"{topic}:{error_type}:{trigger}:{wrong_move}".encode("utf-8")).hexdigest()[:12]
    return f"dst-{digest}"


def extract_distractors(source_item: ManualSourceItem) -> list[DistractorAtom]:
    """Extract distractor atoms from one source item."""
    distractors: list[DistractorAtom] = []
    for distractor in source_item.distractors:
        distractors.append(
            DistractorAtom(
                distractor_id=_stable_distractor_id(
                    error_type=distractor.error_type,
                    trigger=distractor.trigger,
                    wrong_move=distractor.wrong_move,
                    topic=source_item.topic,
                ),
                error_type=distractor.error_type,
                trigger=distractor.trigger,
                wrong_move=distractor.wrong_move,
                plausible_choice_shape=distractor.plausible_choice_shape,
                reject_if_too_obvious=distractor.reject_if_too_obvious,
                topic=source_item.topic,
                source_item_ids=[source_item.source_item_id],
            )
        )
    return distractors


def merge_distractors(distractors: list[DistractorAtom]) -> list[DistractorAtom]:
    """Merge equivalent distractor atoms while preserving traceability."""
    merged: dict[str, DistractorAtom] = {}
    for distractor in distractors:
        key = (
            f"{distractor.topic}:{distractor.error_type}:"
            f"{distractor.trigger}:{distractor.wrong_move}"
        )
        if key not in merged:
            merged[key] = distractor
            continue
        current = merged[key]
        merged[key] = current.model_copy(
            update={
                "source_item_ids": unique_preserve_order(
                    current.source_item_ids + distractor.source_item_ids
                )
            }
        )
    return sorted(merged.values(), key=lambda atom: (atom.topic, atom.error_type, atom.trigger))
