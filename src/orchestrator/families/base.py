"""Shared registry types and authoring helpers for deterministic real-item families."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from hashlib import sha1
from typing import Any, Callable, Sequence

from src.core.schemas import (
    CritiqueFinding,
    CritiqueReport,
    DraftItem,
    ExamSpec,
    ItemBlueprint,
    SolvedItem,
    ValidationSeverity,
)
from src.distill.atom_extractor import InsightAtom

BlueprintBuilder = Callable[[ExamSpec, InsightAtom], ItemBlueprint]
DraftStrategy = Callable[[ItemBlueprint, InsightAtom], DraftItem]
SolveStrategy = Callable[[DraftItem, InsightAtom], SolvedItem]
CritiqueStrategy = Callable[[SolvedItem, InsightAtom], CritiqueReport]
ReviseStrategy = Callable[[SolvedItem, CritiqueReport, InsightAtom], SolvedItem]
AtomMatcher = Callable[[InsightAtom], bool]

BLUEPRINT_FAMILY_TAG_PREFIX = "real_item_family:"


class RealItemFamilySelectionError(ValueError):
    """Raised when the registry cannot choose a deterministic family."""


def _unique(values: Sequence[str]) -> list[str]:
    ordered: list[str] = []
    for value in values:
        if value and value not in ordered:
            ordered.append(value)
    return ordered


def blueprint_family_tag(family_id: str) -> str:
    """Return the hidden blueprint skill tag used to preserve family identity."""

    return f"{BLUEPRINT_FAMILY_TAG_PREFIX}{family_id}"


def extract_blueprint_family_id(blueprint: ItemBlueprint) -> str | None:
    """Recover an explicit family tag from a blueprint when one is present."""

    tagged_family_ids = [
        tag.removeprefix(BLUEPRINT_FAMILY_TAG_PREFIX)
        for tag in blueprint.skill_tags
        if tag.startswith(BLUEPRINT_FAMILY_TAG_PREFIX)
    ]
    if not tagged_family_ids:
        return None
    unique_family_ids = _unique(tagged_family_ids)
    if len(unique_family_ids) > 1:
        raise RealItemFamilySelectionError(
            f"Blueprint item_no={blueprint.item_no} carries conflicting family tags {unique_family_ids}"
        )
    return unique_family_ids[0]


@dataclass(frozen=True)
class RealItemFamily:
    """One deterministic item family and its stage hooks."""

    family_id: str
    supported_atom_topics: tuple[str, ...]
    supported_answer_forms: tuple[str, ...]
    blueprint_item_no: int
    blueprint_builder: BlueprintBuilder
    draft_strategy: DraftStrategy
    solve_strategy: SolveStrategy
    critique_strategy: CritiqueStrategy
    revise_strategy: ReviseStrategy
    atom_matcher: AtomMatcher | None = None
    smoke_canonical_moves: tuple[str, ...] = ()

    def matches_atom(self, atom: InsightAtom) -> bool:
        if atom.topic not in self.supported_atom_topics:
            return False
        if not set(atom.allowed_answer_forms).intersection(self.supported_answer_forms):
            return False
        if self.atom_matcher is None:
            return True
        return self.atom_matcher(atom)

    def matches_blueprint(self, blueprint: ItemBlueprint) -> bool:
        explicit_family_id = extract_blueprint_family_id(blueprint)
        if explicit_family_id is not None:
            return explicit_family_id == self.family_id
        return blueprint.item_no == self.blueprint_item_no

    def build_smoke_atom(self) -> InsightAtom:
        """Return a synthetic atom that should deterministically select this family."""

        topic = self.supported_atom_topics[0]
        canonical_moves = list(self.smoke_canonical_moves or (f"{self.family_id}_smoke",))
        return InsightAtom(
            atom_id=f"smoke-{self.family_id}",
            label=f"{self.family_id} smoke",
            topic=topic,
            prerequisites=_unique(topic.split("_")[:2]) or [topic],
            canonical_moves=canonical_moves,
            allowed_answer_forms=list(self.supported_answer_forms),
        )


class RealItemFamilyRegistry:
    """Registry for blueprint selection, stage routing, and coverage reporting."""

    def __init__(self, families: Sequence[RealItemFamily]) -> None:
        ordered_families = tuple(families)
        family_ids = [family.family_id for family in ordered_families]
        duplicate_ids = sorted(
            family_id for family_id, count in Counter(family_ids).items() if count > 1
        )
        if duplicate_ids:
            raise ValueError(f"Duplicate real-item family ids: {duplicate_ids}")
        self._families = ordered_families
        self._families_by_id = {family.family_id: family for family in self._families}

    @property
    def families(self) -> tuple[RealItemFamily, ...]:
        return self._families

    def family_ids(self) -> tuple[str, ...]:
        return tuple(family.family_id for family in self._families)

    def get(self, family_id: str) -> RealItemFamily:
        family = self._families_by_id.get(family_id)
        if family is None:
            available = ", ".join(self.family_ids())
            raise RealItemFamilySelectionError(
                f"Unknown real-item family '{family_id}'. Available families: {available}"
            )
        return family

    def select_for_atom(self, atom: InsightAtom, family_id: str | None = None) -> RealItemFamily:
        if family_id is not None:
            family = self.get(family_id)
            if not family.matches_atom(atom):
                raise RealItemFamilySelectionError(
                    "Requested real-item family does not support the supplied atom: "
                    f"family_id='{family.family_id}', topic='{atom.topic}', "
                    f"allowed_answer_forms={atom.allowed_answer_forms}"
                )
            return family

        matches = [family for family in self._families if family.matches_atom(atom)]
        if not matches:
            raise RealItemFamilySelectionError(
                "No real-item family matches the supplied atom metadata: "
                f"atom_id='{atom.atom_id}', topic='{atom.topic}', "
                f"allowed_answer_forms={atom.allowed_answer_forms}"
            )
        if len(matches) > 1:
            raise RealItemFamilySelectionError(
                "Atom matched more than one real-item family; tighten the registry matcher rules: "
                f"atom_id='{atom.atom_id}', matched={[family.family_id for family in matches]}"
            )
        return matches[0]

    def resolve_for_blueprint(self, blueprint: ItemBlueprint) -> RealItemFamily:
        explicit_family_id = extract_blueprint_family_id(blueprint)
        if explicit_family_id is not None:
            family = self.get(explicit_family_id)
            if family.blueprint_item_no != blueprint.item_no:
                raise RealItemFamilySelectionError(
                    "Blueprint carries a family tag but its item_no does not match the tagged family: "
                    f"tagged_family='{family.family_id}', blueprint_item_no={blueprint.item_no}, "
                    f"family_item_no={family.blueprint_item_no}"
                )
            return family

        matches = [family for family in self._families if family.matches_blueprint(blueprint)]
        if not matches:
            raise RealItemFamilySelectionError(
                "No real-item family is registered for the blueprint: "
                f"item_no={blueprint.item_no}, domain='{blueprint.domain}', format='{blueprint.format.value}'"
            )
        if len(matches) > 1:
            raise RealItemFamilySelectionError(
                "Blueprint mapped to more than one real-item family. "
                "Add an explicit real_item_family skill tag to disambiguate: "
                f"item_no={blueprint.item_no}, matched={[family.family_id for family in matches]}"
            )
        return matches[0]

    def resolve_for_context(self, context: dict[str, object]) -> RealItemFamily:
        if "item_blueprint" in context:
            blueprint = ItemBlueprint.model_validate(context["item_blueprint"])
            return self.resolve_for_blueprint(blueprint)
        if "draft_item" in context:
            draft = DraftItem.model_validate(context["draft_item"])
            return self.resolve_for_blueprint(draft.blueprint)
        if "solved_item" in context:
            solved = SolvedItem.model_validate(context["solved_item"])
            return self.resolve_for_blueprint(solved.draft.blueprint)
        if "atom" in context:
            atom = InsightAtom.model_validate(context["atom"])
            return self.select_for_atom(atom)
        raise RealItemFamilySelectionError(
            "Prompt context does not contain enough information to resolve a real-item family"
        )

    def classify_atom_support(
        self, atom: InsightAtom
    ) -> tuple[list[RealItemFamily], list[dict[str, str]]]:
        topic_matches = [
            family for family in self._families if atom.topic in family.supported_atom_topics
        ]
        if not topic_matches:
            return [], [
                {
                    "code": "topic_not_supported",
                    "message": f"No real-item family currently supports topic '{atom.topic}'",
                }
            ]

        answer_matches = [
            family
            for family in topic_matches
            if set(atom.allowed_answer_forms).intersection(family.supported_answer_forms)
        ]
        if not answer_matches:
            supported_forms = sorted(
                {
                    answer_form
                    for family in topic_matches
                    for answer_form in family.supported_answer_forms
                }
            )
            return topic_matches, [
                {
                    "code": "answer_form_not_supported",
                    "message": (
                        f"Topic '{atom.topic}' is only wired for answer forms {supported_forms}, "
                        f"not {atom.allowed_answer_forms}"
                    ),
                }
            ]

        matched = [family for family in answer_matches if family.matches_atom(atom)]
        if not matched:
            return answer_matches, [
                {
                    "code": "family_matcher_not_satisfied",
                    "message": (
                        f"Topic '{atom.topic}' and answer forms {atom.allowed_answer_forms} are recognized, "
                        "but the atom's canonical moves do not satisfy any family matcher."
                    ),
                }
            ]
        if len(matched) > 1:
            return matched, [
                {
                    "code": "ambiguous_family_match",
                    "message": (
                        f"Atom '{atom.atom_id}' matches multiple families "
                        f"{[family.family_id for family in matched]}"
                    ),
                }
            ]
        return matched, []

    def coverage_report(
        self,
        atoms: Sequence[InsightAtom],
        *,
        overload_threshold: int = 6,
    ) -> dict[str, Any]:
        """Report how atoms map into the family registry."""

        matched_rows: list[dict[str, Any]] = []
        unmatched_atoms: list[dict[str, Any]] = []
        ambiguous_atoms: list[dict[str, Any]] = []
        matched_atom_ids_by_family: dict[str, list[str]] = defaultdict(list)
        matched_atom_rows_by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)

        for atom in atoms:
            matched_families, reasons = self.classify_atom_support(atom)
            atom_row = {
                "atom_id": atom.atom_id,
                "label": atom.label,
                "topic": atom.topic,
                "allowed_answer_forms": list(atom.allowed_answer_forms),
                "canonical_moves": list(atom.canonical_moves),
                "source_item_ids": list(atom.source_item_ids),
            }
            if len(matched_families) == 1 and not reasons:
                family = matched_families[0]
                mapped_row = {**atom_row, "family_id": family.family_id}
                matched_rows.append(mapped_row)
                matched_atom_ids_by_family[family.family_id].append(atom.atom_id)
                matched_atom_rows_by_family[family.family_id].append(atom_row)
                continue

            unresolved_row = {
                **atom_row,
                "candidate_families": [family.family_id for family in matched_families],
                "reasons": reasons,
            }
            if any(reason["code"] == "ambiguous_family_match" for reason in reasons):
                ambiguous_atoms.append(unresolved_row)
            else:
                unmatched_atoms.append(unresolved_row)

        family_rows = []
        for family in sorted(self._families, key=lambda row: row.family_id):
            matched_atom_ids = matched_atom_ids_by_family.get(family.family_id, [])
            family_rows.append(
                {
                    "family_id": family.family_id,
                    "supported_atom_topics": list(family.supported_atom_topics),
                    "supported_answer_forms": list(family.supported_answer_forms),
                    "blueprint_item_no": family.blueprint_item_no,
                    "matched_atom_count": len(matched_atom_ids),
                    "matched_atom_ids": matched_atom_ids,
                    "matched_atoms": matched_atom_rows_by_family.get(family.family_id, []),
                }
            )

        overloaded_families = [
            {
                "family_id": family_row["family_id"],
                "matched_atom_count": family_row["matched_atom_count"],
                "threshold": overload_threshold,
                "matched_atom_ids": family_row["matched_atom_ids"],
            }
            for family_row in family_rows
            if family_row["matched_atom_count"] > overload_threshold
        ]

        return {
            "family_count": len(self._families),
            "curated_atom_count": len(atoms),
            "matched_atom_count": len(matched_rows),
            "supported_atom_count": len(matched_rows),
            "unmatched_atom_count": len(unmatched_atoms),
            "unsupported_atom_count": len(unmatched_atoms),
            "ambiguous_atom_count": len(ambiguous_atoms),
            "overload_threshold": overload_threshold,
            "atom_mappings": matched_rows,
            "unmatched_atoms": unmatched_atoms,
            "ambiguous_atoms": ambiguous_atoms,
            "overloaded_families": overloaded_families,
            "by_family": family_rows,
        }


@dataclass(frozen=True)
class FamilyVariant:
    """One deterministic stem/solution bundle for a family."""

    stem: str
    solution_steps: tuple[str, ...]
    solution_summary: str
    final_answer: str
    choices: tuple[str, ...] = ()
    revised_choices: tuple[str, ...] | None = None
    revised_solution_steps: tuple[str, ...] | None = None
    revised_solution_summary: str | None = None


@dataclass(frozen=True)
class FamilyCritiqueConfig:
    """Minor revision guidance applied by the critique/revise stages."""

    summary: str = "수학 내용은 타당하지만 마지막 설명을 조금 더 명료하게 다듬는 편이 좋다."
    message: str = "풀이 요약이 핵심 조건과 결론을 한 번 더 직접 연결해 주면 가독성이 좋아진다."
    recommendation: str = "solution_summary를 핵심 조건과 최종 답이 드러나도록 한 문장으로 다듬는다."


@dataclass(frozen=True)
class StaticFamilyTemplate:
    """Declarative authoring surface for one deterministic family."""

    family_id: str
    supported_atom_topics: tuple[str, ...]
    supported_answer_forms: tuple[str, ...]
    blueprint_item_no: int
    objective: str
    base_skill_tags: tuple[str, ...]
    rubric: str
    answer_type: str
    variants: tuple[FamilyVariant, ...]
    critique: FamilyCritiqueConfig = FamilyCritiqueConfig()
    matcher_moves: tuple[str, ...] = ()
    preferred_atom_order: tuple[str, ...] = ()


def _slot(spec: ExamSpec, item_no: int) -> ItemBlueprint:
    return next(blueprint for blueprint in spec.default_item_blueprints if blueprint.item_no == item_no)


def _normalized_skill_tags(*values: str) -> list[str]:
    tags: list[str] = []
    for value in values:
        normalized = value.replace(" ", "_").lower()
        if normalized and normalized not in tags:
            tags.append(normalized)
    return tags


def skill_tags_with_prerequisites(*, base: Sequence[str], atom: InsightAtom) -> list[str]:
    return _normalized_skill_tags(*base, *atom.prerequisites)


def atom_has_any_move(*moves: str) -> AtomMatcher:
    target = set(moves)

    def matcher(atom: InsightAtom) -> bool:
        return any(move in target for move in atom.canonical_moves)

    return matcher


def variant_index(
    *,
    family_id: str,
    atom: InsightAtom,
    variant_count: int,
    preferred_atom_order: Sequence[str] = (),
) -> int:
    if preferred_atom_order and atom.atom_id in preferred_atom_order:
        return preferred_atom_order.index(atom.atom_id) % variant_count
    digest = sha1(f"{family_id}:{atom.atom_id}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % variant_count


def _select_variant(template: StaticFamilyTemplate, atom: InsightAtom) -> FamilyVariant:
    return template.variants[
        variant_index(
            family_id=template.family_id,
            atom=atom,
            variant_count=len(template.variants),
            preferred_atom_order=template.preferred_atom_order,
        )
    ]


def _build_static_blueprint(template: StaticFamilyTemplate) -> BlueprintBuilder:
    def builder(spec: ExamSpec, atom: InsightAtom) -> ItemBlueprint:
        slot = _slot(spec, template.blueprint_item_no)
        skill_tags = skill_tags_with_prerequisites(base=template.base_skill_tags, atom=atom)
        skill_tags.append(blueprint_family_tag(template.family_id))
        return slot.model_copy(
            update={
                "objective": template.objective,
                "skill_tags": _unique(skill_tags),
                "answer_type": template.answer_type,
            }
        )

    return builder


def _build_static_draft(template: StaticFamilyTemplate) -> DraftStrategy:
    def draft_strategy(blueprint: ItemBlueprint, atom: InsightAtom) -> DraftItem:
        variant = _select_variant(template, atom)
        return DraftItem(
            blueprint=blueprint,
            stem=variant.stem,
            choices=list(variant.choices),
            rubric=template.rubric,
            answer_constraints=list(template.supported_answer_forms),
        )

    return draft_strategy


def _build_static_solve(template: StaticFamilyTemplate) -> SolveStrategy:
    def solve_strategy(draft: DraftItem, atom: InsightAtom) -> SolvedItem:
        variant = _select_variant(template, atom)
        if draft.blueprint.format.value == "multiple_choice":
            correct_choice_index = int(variant.final_answer)
            return SolvedItem(
                draft=draft,
                final_answer=variant.final_answer,
                correct_choice_index=correct_choice_index,
                correct_choice_value=draft.choices[correct_choice_index - 1],
                solution_steps=list(variant.solution_steps),
                solution_summary=variant.solution_summary,
            )
        return SolvedItem(
            draft=draft,
            final_answer=variant.final_answer,
            solution_steps=list(variant.solution_steps),
            solution_summary=variant.solution_summary,
        )

    return solve_strategy


def _build_static_critique(template: StaticFamilyTemplate) -> CritiqueStrategy:
    def critique_strategy(solved: SolvedItem, atom: InsightAtom) -> CritiqueReport:
        del atom
        return CritiqueReport(
            item_no=solved.draft.blueprint.item_no,
            summary=template.critique.summary,
            findings=[
                CritiqueFinding(
                    severity=ValidationSeverity.WARNING,
                    message=template.critique.message,
                    recommendation=template.critique.recommendation,
                    blocking=False,
                )
            ],
            requires_revision=True,
        )

    return critique_strategy


def _build_static_revise(template: StaticFamilyTemplate) -> ReviseStrategy:
    def revise_strategy(
        solved: SolvedItem,
        critique: CritiqueReport,
        atom: InsightAtom,
    ) -> SolvedItem:
        del critique
        variant = _select_variant(template, atom)
        revised_draft = solved.draft.model_copy(
            update={"choices": list(variant.revised_choices or solved.draft.choices)}
        )
        update: dict[str, Any] = {
            "draft": revised_draft,
            "solution_steps": list(variant.revised_solution_steps or solved.solution_steps),
            "solution_summary": variant.revised_solution_summary or solved.solution_summary,
        }
        if solved.draft.blueprint.format.value == "multiple_choice":
            correct_choice_index = int(variant.final_answer)
            update["final_answer"] = variant.final_answer
            update["correct_choice_index"] = correct_choice_index
            update["correct_choice_value"] = revised_draft.choices[correct_choice_index - 1]
        return solved.model_copy(update=update)

    return revise_strategy


def build_static_family(template: StaticFamilyTemplate) -> RealItemFamily:
    """Build a runtime family object from one declarative authoring template."""

    if not template.variants:
        raise ValueError(f"Family '{template.family_id}' must define at least one variant")

    atom_matcher = atom_has_any_move(*template.matcher_moves) if template.matcher_moves else None
    smoke_canonical_moves = template.matcher_moves or (f"{template.family_id}_smoke",)
    return RealItemFamily(
        family_id=template.family_id,
        supported_atom_topics=template.supported_atom_topics,
        supported_answer_forms=template.supported_answer_forms,
        blueprint_item_no=template.blueprint_item_no,
        blueprint_builder=_build_static_blueprint(template),
        draft_strategy=_build_static_draft(template),
        solve_strategy=_build_static_solve(template),
        critique_strategy=_build_static_critique(template),
        revise_strategy=_build_static_revise(template),
        atom_matcher=atom_matcher,
        smoke_canonical_moves=smoke_canonical_moves,
    )


def make_multiple_choice_family(
    *,
    family_id: str,
    topic: str,
    blueprint_item_no: int,
    objective: str,
    skill_tags: Sequence[str],
    stem: str,
    choices: Sequence[str],
    correct_choice_index: int,
    solution_steps: Sequence[str],
    solution_summary: str,
    rubric: str,
    critique: FamilyCritiqueConfig | None = None,
    matcher_moves: Sequence[str] = (),
    preferred_atom_order: Sequence[str] = (),
    revised_choices: Sequence[str] | None = None,
    revised_solution_steps: Sequence[str] | None = None,
    revised_solution_summary: str | None = None,
) -> RealItemFamily:
    """Create a declarative multiple-choice family."""

    return build_static_family(
        StaticFamilyTemplate(
            family_id=family_id,
            supported_atom_topics=(topic,),
            supported_answer_forms=("choice_index",),
            blueprint_item_no=blueprint_item_no,
            objective=objective,
            base_skill_tags=tuple(skill_tags),
            rubric=rubric,
            answer_type="choice_index",
            critique=critique or FamilyCritiqueConfig(),
            matcher_moves=tuple(matcher_moves),
            preferred_atom_order=tuple(preferred_atom_order),
            variants=(
                FamilyVariant(
                    stem=stem,
                    choices=tuple(choices),
                    final_answer=str(correct_choice_index),
                    solution_steps=tuple(solution_steps),
                    solution_summary=solution_summary,
                    revised_choices=tuple(revised_choices) if revised_choices is not None else None,
                    revised_solution_steps=(
                        tuple(revised_solution_steps)
                        if revised_solution_steps is not None
                        else None
                    ),
                    revised_solution_summary=revised_solution_summary,
                ),
            ),
        )
    )


def make_short_answer_family(
    *,
    family_id: str,
    topic: str,
    answer_form: str,
    blueprint_item_no: int,
    objective: str,
    skill_tags: Sequence[str],
    stem: str,
    final_answer: str,
    solution_steps: Sequence[str],
    solution_summary: str,
    rubric: str,
    critique: FamilyCritiqueConfig | None = None,
    matcher_moves: Sequence[str] = (),
    preferred_atom_order: Sequence[str] = (),
    revised_solution_steps: Sequence[str] | None = None,
    revised_solution_summary: str | None = None,
) -> RealItemFamily:
    """Create a declarative short-answer family."""

    return build_static_family(
        StaticFamilyTemplate(
            family_id=family_id,
            supported_atom_topics=(topic,),
            supported_answer_forms=(answer_form,),
            blueprint_item_no=blueprint_item_no,
            objective=objective,
            base_skill_tags=tuple(skill_tags),
            rubric=rubric,
            answer_type=answer_form,
            critique=critique or FamilyCritiqueConfig(),
            matcher_moves=tuple(matcher_moves),
            preferred_atom_order=tuple(preferred_atom_order),
            variants=(
                FamilyVariant(
                    stem=stem,
                    final_answer=final_answer,
                    solution_steps=tuple(solution_steps),
                    solution_summary=solution_summary,
                    revised_solution_steps=(
                        tuple(revised_solution_steps)
                        if revised_solution_steps is not None
                        else None
                    ),
                    revised_solution_summary=revised_solution_summary,
                ),
            ),
        )
    )
