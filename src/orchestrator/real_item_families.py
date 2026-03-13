"""Deterministic real-item family registry and strategy hooks."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1
from typing import Any, Callable, Sequence

from src.core.schemas import (
    CritiqueFinding,
    CritiqueReport,
    DraftItem,
    ExamSpec,
    ItemBlueprint,
    ItemFormat,
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

FAMILY_VARIANT_ATOM_ORDER: dict[str, tuple[str, ...]] = {
    "calculus_derivative_vertex_mcq": (
        "atom-f81b2ab6c767",
        "atom-d1170f7c15a9",
        "atom-f9684d631a8c",
        "atom-bb0d073139cc",
        "atom-1c4317d67e80",
        "atom-bba0fe482772",
    ),
    "algebra_log_quadratic_filter_mcq": (
        "atom-991b78d60850",
        "atom-c2ed46456b9d",
        "atom-5d39a6b6e0f6",
    ),
    "probability_conditional_cases_short": (
        "atom-5480edcc0dcb",
        "atom-aaa349a7160b",
    ),
}


class RealItemFamilySelectionError(ValueError):
    """Raised when the registry cannot choose a deterministic family."""


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

    def matches_atom(self, atom: InsightAtom) -> bool:
        if atom.topic not in self.supported_atom_topics:
            return False
        if not set(atom.allowed_answer_forms).intersection(self.supported_answer_forms):
            return False
        if self.atom_matcher is None:
            return True
        return self.atom_matcher(atom)

    def matches_blueprint(self, blueprint: ItemBlueprint) -> bool:
        return blueprint.item_no == self.blueprint_item_no


class RealItemFamilyRegistry:
    """Registry for blueprint selection and stage routing."""

    def __init__(self, families: Sequence[RealItemFamily]) -> None:
        self._families = tuple(families)
        self._families_by_id = {family.family_id: family for family in self._families}

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
        matches = [family for family in self._families if family.matches_blueprint(blueprint)]
        if not matches:
            raise RealItemFamilySelectionError(
                "No real-item family is registered for the blueprint: "
                f"item_no={blueprint.item_no}, domain='{blueprint.domain}', format='{blueprint.format.value}'"
            )
        if len(matches) > 1:
            raise RealItemFamilySelectionError(
                "Blueprint mapped to more than one real-item family: "
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


def build_real_item_family_registry() -> RealItemFamilyRegistry:
    """Return the deterministic real-item families used by the gauntlet."""
    return RealItemFamilyRegistry(
        (
            RealItemFamily(
                family_id="calculus_derivative_vertex_mcq",
                supported_atom_topics=("derivative_monotonicity",),
                supported_answer_forms=("choice_index",),
                blueprint_item_no=14,
                blueprint_builder=_build_derivative_blueprint,
                draft_strategy=_draft_derivative_mcq,
                solve_strategy=_solve_derivative_mcq,
                critique_strategy=_critique_derivative_mcq,
                revise_strategy=_revise_derivative_mcq,
            ),
            RealItemFamily(
                family_id="algebra_log_domain_filter_mcq",
                supported_atom_topics=("log_equation_domain",),
                supported_answer_forms=("choice_index",),
                blueprint_item_no=7,
                blueprint_builder=_build_log_domain_blueprint,
                draft_strategy=_draft_log_domain_mcq,
                solve_strategy=_solve_log_domain_mcq,
                critique_strategy=_critique_log_domain_mcq,
                revise_strategy=_revise_log_domain_mcq,
                atom_matcher=_atom_has_any_move("domain_check"),
            ),
            RealItemFamily(
                family_id="algebra_log_quadratic_filter_mcq",
                supported_atom_topics=("log_equation_domain",),
                supported_answer_forms=("choice_index",),
                blueprint_item_no=8,
                blueprint_builder=_build_log_quadratic_blueprint,
                draft_strategy=_draft_log_quadratic_mcq,
                solve_strategy=_solve_log_quadratic_mcq,
                critique_strategy=_critique_log_quadratic_mcq,
                revise_strategy=_revise_log_quadratic_mcq,
                atom_matcher=_atom_has_any_move("log_merge", "quadratic_filter", "choice_alignment"),
            ),
            RealItemFamily(
                family_id="probability_conditional_cases_short",
                supported_atom_topics=("conditional_probability_table",),
                supported_answer_forms=("reduced_fraction",),
                blueprint_item_no=23,
                blueprint_builder=_build_probability_cases_blueprint,
                draft_strategy=_draft_probability_cases_short,
                solve_strategy=_solve_probability_cases_short,
                critique_strategy=_critique_probability_cases_short,
                revise_strategy=_revise_probability_cases_short,
                atom_matcher=_atom_has_any_move("count_conditioned_cases", "condition_partition"),
            ),
            RealItemFamily(
                family_id="probability_conditional_ratio_short",
                supported_atom_topics=("conditional_probability_table",),
                supported_answer_forms=("reduced_fraction",),
                blueprint_item_no=24,
                blueprint_builder=_build_probability_ratio_blueprint,
                draft_strategy=_draft_probability_ratio_short,
                solve_strategy=_solve_probability_ratio_short,
                critique_strategy=_critique_probability_ratio_short,
                revise_strategy=_revise_probability_ratio_short,
                atom_matcher=_atom_has_any_move("conditional_probability_ratio"),
            ),
        )
    )


def _slot(spec: ExamSpec, item_no: int) -> ItemBlueprint:
    return next(blueprint for blueprint in spec.default_item_blueprints if blueprint.item_no == item_no)


def _normalized_skill_tags(*values: str) -> list[str]:
    tags: list[str] = []
    for value in values:
        normalized = value.replace(" ", "_").lower()
        if normalized and normalized not in tags:
            tags.append(normalized)
    return tags


def _skill_tags_with_prerequisites(*, base: list[str], atom: InsightAtom) -> list[str]:
    return _normalized_skill_tags(*base, *atom.prerequisites)


def _atom_has_any_move(*moves: str) -> AtomMatcher:
    target = set(moves)

    def matcher(atom: InsightAtom) -> bool:
        return any(move in target for move in atom.canonical_moves)

    return matcher


def _variant_index(*, family_id: str, atom: InsightAtom, variant_count: int) -> int:
    preferred_order = FAMILY_VARIANT_ATOM_ORDER.get(family_id)
    if preferred_order and atom.atom_id in preferred_order:
        return preferred_order.index(atom.atom_id) % variant_count
    digest = sha1(f"{family_id}:{atom.atom_id}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % variant_count


def _latexify_choice(choice: str) -> str:
    return (
        choice.replace(" <= ", " \\le ")
        .replace(" >= ", " \\ge ")
        .replace("<=", "\\le ")
        .replace(">=", "\\ge ")
    )


def _derivative_variant(atom: InsightAtom) -> dict[str, Any]:
    variants = (
        {
            "variable": "a",
            "function": "y=x^3-6x^2+ax",
            "derivative": "y'=3x^2-12x+a",
            "derivative_squared": "y'=3(x-2)^2+(a-12)",
            "vertex_x": "2",
            "threshold": "12",
            "stem": (
                "실수 a에 따라 함수 h(x)=x^3-6x^2+ax의 접선 기울기가 "
                "모든 x에서 0 미만으로 떨어지지 않게 하려 한다. 이를 보장하는 a의 조건은?"
            ),
            "choices": ["a <= 12", "a = 12", "a >= 3", "a >= 12", "a <= 3"],
            "correct_choice_index": 4,
            "solution_steps": [
                "접선 기울기가 항상 음수가 아니어야 하므로 모든 실수 x에 대해 y'=3x^2-12x+a >= 0 이어야 한다.",
                "도함수 y'를 y'=3(x-2)^2+(a-12)로 고치면 최솟값은 x=2에서 a-12임을 바로 알 수 있다.",
                "전구간에서 0 이상이 되려면 최솟값 a-12가 0 이상이어야 하므로 a >= 12이다.",
                "따라서 조건에 맞는 선택지는 4번 a >= 12이다.",
            ],
            "summary": "도함수를 완전제곱식으로 바꾸어 최솟값을 확인하면 매개변수 조건이 정해진다.",
        },
        {
            "variable": "b",
            "function": "y=x^3-9x^2+bx",
            "derivative": "y'=3x^2-18x+b",
            "derivative_squared": "y'=3(x-3)^2+(b-27)",
            "vertex_x": "3",
            "threshold": "27",
            "stem": (
                "실수 b에 대하여 함수 y=x^3-9x^2+bx가 전체 실수 범위에서 줄어드는 구간을 "
                "갖지 않으려면 b는 어떤 조건을 만족해야 하는가?"
            ),
            "choices": ["b = 27", "b <= 27", "b >= 18", "b <= 18", "b >= 27"],
            "correct_choice_index": 5,
            "solution_steps": [
                "함수가 어느 구간에서도 감소하지 않으려면 모든 실수 x에 대해 y'=3x^2-18x+b >= 0 이어야 한다.",
                "도함수를 y'=3(x-3)^2+(b-27)로 정리하면 최솟값은 x=3일 때의 b-27이다.",
                "최솟값이 0 이상이어야 전구간에서 도함수가 음수가 되지 않으므로 b-27 >= 0, 즉 b >= 27이다.",
                "따라서 정답은 5번 b >= 27이다.",
            ],
            "summary": "도함수의 꼭짓점 값을 확인해 전구간 부호 조건을 읽으면 b >= 27이 된다.",
        },
        {
            "variable": "c",
            "function": "y=x^3-12x^2+cx",
            "derivative": "y'=3x^2-24x+c",
            "derivative_squared": "y'=3(x-4)^2+(c-48)",
            "vertex_x": "4",
            "threshold": "48",
            "stem": (
                "매개변수 c에 대하여 함수 y=x^3-12x^2+cx의 도함수가 모든 실수 x에서 "
                "음이 아니도록 할 때 c의 조건으로 옳은 것은?"
            ),
            "choices": ["c <= 48", "c >= 48", "c = 24", "c >= 24", "c <= 24"],
            "correct_choice_index": 2,
            "solution_steps": [
                "도함수가 항상 음이 아니어야 하므로 모든 실수 x에 대해 y'=3x^2-24x+c >= 0 이어야 한다.",
                "이를 y'=3(x-4)^2+(c-48)로 완전제곱식 형태로 쓰면 최소값은 x=4에서 c-48이다.",
                "최솟값 c-48이 0 이상이어야 하므로 c >= 48이다.",
                "따라서 조건에 맞는 선택지는 2번 c >= 48이다.",
            ],
            "summary": "도함수를 3(x-4)^2+(c-48)로 정리하여 최소값을 보면 c >= 48임을 알 수 있다.",
        },
        {
            "variable": "k",
            "function": "y=x^3-15x^2+kx",
            "derivative": "y'=3x^2-30x+k",
            "derivative_squared": "y'=3(x-5)^2+(k-75)",
            "vertex_x": "5",
            "threshold": "75",
            "stem": (
                "매개변수 k에 대해 함수 g(x)=x^3-15x^2+kx의 접선 기울기가 "
                "모든 실수 x에서 음수가 되지 않도록 만들고자 한다. 가능한 k의 범위는?"
            ),
            "choices": ["k >= 75", "k = 75", "k <= 75", "k >= 50", "k <= 50"],
            "correct_choice_index": 1,
            "solution_steps": [
                "전구간에서 감소하지 않으려면 모든 실수 x에 대해 y'=3x^2-30x+k >= 0 이어야 한다.",
                "도함수를 y'=3(x-5)^2+(k-75)로 고치면 최솟값은 x=5에서 k-75이다.",
                "따라서 최솟값이 0 이상이 되도록 k-75 >= 0, 즉 k >= 75가 필요하다.",
                "그래서 정답은 1번 k >= 75이다.",
            ],
            "summary": "꼭짓점 x=5에서의 도함수 최소값을 이용하면 k >= 75가 바로 나온다.",
        },
        {
            "variable": "m",
            "function": "y=x^3-18x^2+mx",
            "derivative": "y'=3x^2-36x+m",
            "derivative_squared": "y'=3(x-6)^2+(m-108)",
            "vertex_x": "6",
            "threshold": "108",
            "stem": (
                "실수 m에 대하여 곡선 y=x^3-18x^2+mx의 접선 기울기가 어떤 x에서도 "
                "음수가 되지 않게 하려면 m은 어떤 범위에 있어야 하는가?"
            ),
            "choices": ["m <= 108", "m = 108", "m >= 72", "m >= 108", "m <= 72"],
            "correct_choice_index": 4,
            "solution_steps": [
                "접선 기울기가 항상 음수가 아니려면 모든 실수 x에 대해 y'=3x^2-36x+m >= 0 이어야 한다.",
                "이를 y'=3(x-6)^2+(m-108)로 정리하면 최솟값은 x=6에서 m-108이다.",
                "최솟값이 0 이상이 되어야 하므로 m-108 >= 0, 따라서 m >= 108이다.",
                "따라서 정답은 4번 m >= 108이다.",
            ],
            "summary": "도함수의 꼭짓점 값을 확인하면 전구간 비음수 조건은 m >= 108로 정리된다.",
        },
        {
            "variable": "p",
            "function": "y=x^3-21x^2+px",
            "derivative": "y'=3x^2-42x+p",
            "derivative_squared": "y'=3(x-7)^2+(p-147)",
            "vertex_x": "7",
            "threshold": "147",
            "stem": (
                "매개변수 p에 대하여 함수 y=x^3-21x^2+px의 증가 조건을 조사한다. "
                "도함수가 모든 실수 x에서 0 이상이 되려면 p는 어떤 조건을 만족해야 하는가?"
            ),
            "choices": ["p = 147", "p <= 147", "p >= 98", "p <= 98", "p >= 147"],
            "correct_choice_index": 5,
            "solution_steps": [
                "도함수가 전구간에서 0 이상이어야 하므로 y'=3x^2-42x+p >= 0 가 모든 실수 x에 대해 성립해야 한다.",
                "도함수를 y'=3(x-7)^2+(p-147)로 바꾸면 최솟값은 x=7에서 p-147이다.",
                "최솟값이 0 이상이면 충분하고 필요하므로 p-147 >= 0, 즉 p >= 147이다.",
                "따라서 조건을 만족하는 선택지는 5번 p >= 147이다.",
            ],
            "summary": "도함수를 완전제곱식으로 나타내어 꼭짓점에서의 최소값을 확인하면 p >= 147이다.",
        },
    )
    return variants[_variant_index(family_id="calculus_derivative_vertex_mcq", atom=atom, variant_count=len(variants))]


def _log_quadratic_variant(atom: InsightAtom) -> dict[str, Any]:
    variants = (
        {
            "stem": "다음 로그방정식 log_3(x-1)+log_3(x-4)=2를 만족시키는 실수 x는 무엇인가?",
            "choices": ["(5-3sqrt(5))/2", "2", "(5+3sqrt(5))/2", "4", "(7+3sqrt(5))/2"],
            "revised_choices": [
                "\\frac{5-3\\sqrt{5}}{2}",
                "2",
                "\\frac{5+3\\sqrt{5}}{2}",
                "4",
                "\\frac{7+3\\sqrt{5}}{2}",
            ],
            "correct_choice_index": 3,
            "solution_steps": [
                "로그의 진수가 양수여야 하므로 x-1>0, x-4>0 이고 따라서 x>4이다.",
                "두 로그를 합치면 log_3((x-1)(x-4))=2 이므로 (x-1)(x-4)=9이다.",
                "전개하면 x^2-5x-5=0 이고 근의 공식으로 x=\\frac{5\\pm3\\sqrt{5}}{2} 를 얻는다.",
                "이 중 x>4를 만족하는 것은 \\frac{5+3\\sqrt{5}}{2} 뿐이므로 정답은 3번이다.",
            ],
            "summary": "로그 결합으로 만든 이차방정식의 두 근을 구한 뒤 정의역 x>4 조건으로 하나만 남긴다.",
            "revised_summary": "로그를 하나로 합친 뒤 이차방정식의 근을 구하고 정의역 x>4 조건으로 \\frac{5+3\\sqrt{5}}{2}를 선택한다.",
        },
        {
            "stem": "정의역 조건을 먼저 고려할 때 식 log_2(x-2)+log_2(x-5)=3에서 남는 해는?",
            "choices": ["(7-sqrt(41))/2", "5", "(7+sqrt(41))/2", "6", "(9+sqrt(41))/2"],
            "revised_choices": [
                "\\frac{7-\\sqrt{41}}{2}",
                "5",
                "\\frac{7+\\sqrt{41}}{2}",
                "6",
                "\\frac{9+\\sqrt{41}}{2}",
            ],
            "correct_choice_index": 3,
            "solution_steps": [
                "로그의 진수가 양수여야 하므로 x-2>0, x-5>0 이고 따라서 x>5이다.",
                "두 로그를 합치면 log_2((x-2)(x-5))=3 이므로 (x-2)(x-5)=8이다.",
                "정리하면 x^2-7x+2=0 이고 근의 공식으로 x=\\frac{7\\pm\\sqrt{41}}{2} 를 얻는다.",
                "이 중 x>5를 만족하는 것은 \\frac{7+\\sqrt{41}}{2} 뿐이므로 정답은 3번이다.",
            ],
            "summary": "로그를 결합해 만든 이차방정식의 두 근 가운데 정의역 x>5를 만족하는 것만 남기면 된다.",
            "revised_summary": "로그를 하나로 묶어 x^2-7x+2=0을 만든 뒤 정의역 x>5를 적용하면 \\frac{7+\\sqrt{41}}{2}가 남는다.",
        },
        {
            "stem": "실수 x가 log_5(x-1)+log_5(x-6)=2를 만족한다. 조건을 모두 통과하는 값은 무엇인가?",
            "choices": ["(7-5sqrt(5))/2", "6", "(7+5sqrt(5))/2", "7", "(9+5sqrt(5))/2"],
            "revised_choices": [
                "\\frac{7-5\\sqrt{5}}{2}",
                "6",
                "\\frac{7+5\\sqrt{5}}{2}",
                "7",
                "\\frac{9+5\\sqrt{5}}{2}",
            ],
            "correct_choice_index": 3,
            "solution_steps": [
                "로그의 진수가 양수여야 하므로 x-1>0, x-6>0 이고 따라서 x>6이다.",
                "두 로그를 합치면 log_5((x-1)(x-6))=2 이므로 (x-1)(x-6)=25이다.",
                "전개하면 x^2-7x-19=0 이고 근의 공식으로 x=\\frac{7\\pm5\\sqrt{5}}{2} 를 얻는다.",
                "이 중 x>6를 만족하는 것은 \\frac{7+5\\sqrt{5}}{2} 뿐이므로 정답은 3번이다.",
            ],
            "summary": "로그를 합쳐 얻은 이차방정식의 근을 구하고 정의역 x>6 조건으로 하나를 골라낸다.",
            "revised_summary": "로그를 하나로 합쳐 x^2-7x-19=0을 만든 뒤 정의역 x>6를 적용하면 \\frac{7+5\\sqrt{5}}{2}가 정답이다.",
        },
    )
    return variants[_variant_index(family_id="algebra_log_quadratic_filter_mcq", atom=atom, variant_count=len(variants))]


def _probability_cases_variant(atom: InsightAtom) -> dict[str, Any]:
    variants = (
        {
            "stem": (
                "한 반 학생을 성별과 동아리 가입 여부에 따라 조사했더니 "
                "남학생은 가입 4명, 미가입 2명이고 여학생은 가입 6명, 미가입 3명이었다. "
                "임의로 한 학생을 택했을 때 동아리 가입 학생이라는 조건 아래 여학생일 확률을 기약분수로 구하시오."
            ),
            "answer": "3/5",
            "solution_steps": [
                "조건 사건이 동아리 가입 학생이므로 분모는 가입한 학생 전체인 4+6=10명이다.",
                "이 가운데 여학생은 6명이므로 조건부확률의 분자는 6, 분모는 10이다.",
                "정리하면 구하는 확률은 6/10=3/5 이므로 답은 3/5이다.",
            ],
            "summary": "조건 사건에 해당하는 가입 학생 10명만 남긴 뒤 그중 여학생 6명을 세어 3/5를 얻는다.",
            "revised_summary": "조건 사건인 가입 학생 10명을 분모로 두고 그중 여학생 6명을 세면 확률은 3/5이다.",
        },
        {
            "stem": (
                "학생들을 기숙사 거주 여부와 봉사활동 신청 여부에 따라 분류했더니 "
                "기숙사생은 신청 4명, 미신청 3명이고 통학생은 신청 3명, 미신청 5명이었다. "
                "임의로 한 학생을 고를 때 봉사활동 신청 학생이라는 조건 아래 기숙사생일 확률을 기약분수로 구하시오."
            ),
            "answer": "4/7",
            "solution_steps": [
                "조건 사건이 봉사활동 신청 학생이므로 분모는 신청한 학생 전체인 4+3=7명이다.",
                "그중 기숙사생은 4명이므로 조건부확률은 4/7이다.",
                "4와 7은 서로소이므로 이미 기약분수이며 답은 4/7이다.",
            ],
            "summary": "신청 학생 7명을 분모로 두고 그중 기숙사생 4명을 세면 조건부확률은 4/7이다.",
            "revised_summary": "조건 사건인 신청 학생 7명 가운데 기숙사생이 4명이므로 확률은 4/7이다.",
        },
    )
    return variants[_variant_index(family_id="probability_conditional_cases_short", atom=atom, variant_count=len(variants))]


def _build_derivative_blueprint(spec: ExamSpec, atom: InsightAtom) -> ItemBlueprint:
    slot = _slot(spec, 14)
    return slot.model_copy(
        update={
            "objective": "도함수의 부호와 꼭짓점 판단",
            "skill_tags": _skill_tags_with_prerequisites(
                base=["derivative", "monotonicity", "quadratic_vertex_check"],
                atom=atom,
            ),
            "answer_type": "choice_index",
        }
    )


def _draft_derivative_mcq(blueprint: ItemBlueprint, atom: InsightAtom) -> DraftItem:
    variant = _derivative_variant(atom)
    return DraftItem(
        blueprint=blueprint,
        stem=variant["stem"],
        choices=variant["choices"],
        rubric="도함수를 완전제곱식으로 바꾸어 최솟값을 확인한 뒤 전구간 부호 조건을 판정한다.",
        answer_constraints=["choice_index"],
    )


def _solve_derivative_mcq(draft: DraftItem, atom: InsightAtom) -> SolvedItem:
    variant = _derivative_variant(atom)
    return SolvedItem(
        draft=draft,
        final_answer=str(variant["correct_choice_index"]),
        correct_choice_index=variant["correct_choice_index"],
        correct_choice_value=draft.choices[variant["correct_choice_index"] - 1],
        solution_steps=variant["solution_steps"],
        solution_summary=variant["summary"],
    )


def _critique_derivative_mcq(solved: SolvedItem, atom: InsightAtom) -> CritiqueReport:
    del atom
    return CritiqueReport(
        item_no=solved.draft.blueprint.item_no,
        summary="핵심 수학은 타당하지만 선지 부등호 표기를 수식형으로 통일하는 편이 낫다.",
        findings=[
            CritiqueFinding(
                severity=ValidationSeverity.WARNING,
                message="선지에 <=, >=가 섞여 있어 최종 렌더에서 수식 일관성이 떨어질 수 있다.",
                recommendation="부등호를 \\le, \\ge 표기로 통일해 최종본을 다시 저장한다.",
                blocking=False,
            )
        ],
        requires_revision=True,
    )


def _revise_derivative_mcq(
    solved: SolvedItem,
    critique: CritiqueReport,
    atom: InsightAtom,
) -> SolvedItem:
    del critique
    variant = _derivative_variant(atom)
    revised_choices = [_latexify_choice(choice) for choice in variant["choices"]]
    final_answer = str(variant["correct_choice_index"])
    revised_draft = solved.draft.model_copy(update={"choices": revised_choices})
    return solved.model_copy(
        update={
            "draft": revised_draft,
            "final_answer": final_answer,
            "correct_choice_index": variant["correct_choice_index"],
            "correct_choice_value": revised_choices[variant["correct_choice_index"] - 1],
            "solution_steps": [_latexify_choice(step) for step in variant["solution_steps"]],
            "solution_summary": _latexify_choice(variant["summary"]),
        }
    )


def _build_log_domain_blueprint(spec: ExamSpec, atom: InsightAtom) -> ItemBlueprint:
    slot = _slot(spec, 7)
    return slot.model_copy(
        update={
            "objective": "로그방정식 정의역과 해의 개수 판단",
            "skill_tags": _skill_tags_with_prerequisites(
                base=["logarithm", "equation", "domain_check"],
                atom=atom,
            ),
            "answer_type": "choice_index",
        }
    )


def _draft_log_domain_mcq(blueprint: ItemBlueprint, atom: InsightAtom) -> DraftItem:
    del atom
    return DraftItem(
        blueprint=blueprint,
        stem="방정식 log_2(x-1)=log_2(7-x)-1의 실근의 개수는?",
        choices=["0", "1", "2", "3", "4"],
        rubric="양변의 로그 정의역을 먼저 세우고, 같은 밑 로그식으로 바꾼 뒤 얻은 해가 정의역에 들어가는지 확인한다.",
        answer_constraints=["choice_index"],
    )


def _solve_log_domain_mcq(draft: DraftItem, atom: InsightAtom) -> SolvedItem:
    del atom
    return SolvedItem(
        draft=draft,
        final_answer="2",
        correct_choice_index=2,
        correct_choice_value=draft.choices[1],
        solution_steps=[
            "로그의 진수가 양수여야 하므로 x-1>0 이고 7-x>0 이다. 따라서 정의역은 1<x<7 이다.",
            "우변의 -1은 log_2(1/2) 이므로 log_2(7-x)-1=log_2((7-x)/2) 로 바꿀 수 있다.",
            "같은 밑의 로그가 같으므로 x-1=(7-x)/2 이고 정리하면 3x=9, 따라서 x=3 이다.",
            "얻은 해 x=3은 정의역 1<x<7을 만족하므로 실근의 개수는 1이다.",
            "따라서 정답은 2번이다.",
        ],
        solution_summary="정의역 1<x<7을 먼저 세우고 같은 밑 로그식으로 바꾸어 얻은 해 x=3이 조건을 만족하는지 확인하면 된다.",
    )


def _critique_log_domain_mcq(solved: SolvedItem, atom: InsightAtom) -> CritiqueReport:
    del atom
    return CritiqueReport(
        item_no=solved.draft.blueprint.item_no,
        summary="풀이는 맞지만 선지를 자연어 개수 표현으로 통일하면 문항 의도가 더 분명하다.",
        findings=[
            CritiqueFinding(
                severity=ValidationSeverity.WARNING,
                message="선지가 단순 숫자라서 '개수'를 묻는 문항이라는 점이 마지막에 약해진다.",
                recommendation="선지를 없음, 한 개, 두 개, 세 개, 네 개처럼 개수 표현으로 통일한다.",
                blocking=False,
            )
        ],
        requires_revision=True,
    )


def _revise_log_domain_mcq(
    solved: SolvedItem,
    critique: CritiqueReport,
    atom: InsightAtom,
) -> SolvedItem:
    del critique, atom
    revised_choices = ["없음", "한 개", "두 개", "세 개", "네 개"]
    revised_draft = solved.draft.model_copy(update={"choices": revised_choices})
    return solved.model_copy(
        update={
            "draft": revised_draft,
            "correct_choice_value": revised_choices[1],
            "solution_steps": [
                "로그의 진수가 양수여야 하므로 x-1>0 이고 7-x>0 이다. 따라서 정의역은 1<x<7 이다.",
                "우변의 -1은 log_2(1/2) 이므로 log_2(7-x)-1=log_2((7-x)/2) 로 바꿀 수 있다.",
                "같은 밑의 로그가 같으므로 x-1=(7-x)/2 이고 정리하면 3x=9, 따라서 x=3 이다.",
                "얻은 해 x=3은 정의역 1<x<7을 만족하므로 실근의 개수는 한 개이다.",
                "따라서 정답은 2번 한 개이다.",
            ],
            "solution_summary": "정의역 1<x<7을 먼저 확정하고 같은 밑 로그식으로 바꾸어 얻은 해 x=3을 점검하면 실근은 한 개만 남는다.",
        }
    )


def _build_log_quadratic_blueprint(spec: ExamSpec, atom: InsightAtom) -> ItemBlueprint:
    slot = _slot(spec, 8)
    return slot.model_copy(
        update={
            "objective": "로그방정식 정리와 이차방정식 해 선택",
            "skill_tags": _skill_tags_with_prerequisites(
                base=["logarithm", "equation", "quadratic_filter"],
                atom=atom,
            ),
            "answer_type": "choice_index",
        }
    )


def _draft_log_quadratic_mcq(blueprint: ItemBlueprint, atom: InsightAtom) -> DraftItem:
    variant = _log_quadratic_variant(atom)
    return DraftItem(
        blueprint=blueprint,
        stem=variant["stem"],
        choices=variant["choices"],
        rubric="로그를 합쳐 이차방정식으로 바꾼 뒤 정의역을 만족하는 해를 선택한다.",
        answer_constraints=["choice_index"],
    )


def _solve_log_quadratic_mcq(draft: DraftItem, atom: InsightAtom) -> SolvedItem:
    variant = _log_quadratic_variant(atom)
    return SolvedItem(
        draft=draft,
        final_answer=str(variant["correct_choice_index"]),
        correct_choice_index=variant["correct_choice_index"],
        correct_choice_value=draft.choices[variant["correct_choice_index"] - 1],
        solution_steps=variant["solution_steps"],
        solution_summary=variant["summary"],
    )


def _critique_log_quadratic_mcq(solved: SolvedItem, atom: InsightAtom) -> CritiqueReport:
    del atom
    return CritiqueReport(
        item_no=solved.draft.blueprint.item_no,
        summary="수학은 타당하지만 근호 표기를 LaTeX 형식으로 통일하는 편이 렌더에 안정적이다.",
        findings=[
            CritiqueFinding(
                severity=ValidationSeverity.WARNING,
                message="선지에 sqrt(5) 형식이 남아 있어 수식 표기가 일정하지 않다.",
                recommendation="sqrt(5)를 \\sqrt{5} 표기로 통일한다.",
                blocking=False,
            )
        ],
        requires_revision=True,
    )


def _revise_log_quadratic_mcq(
    solved: SolvedItem,
    critique: CritiqueReport,
    atom: InsightAtom,
) -> SolvedItem:
    del critique
    variant = _log_quadratic_variant(atom)
    revised_choices = variant["revised_choices"]
    revised_draft = solved.draft.model_copy(update={"choices": revised_choices})
    return solved.model_copy(
        update={
            "draft": revised_draft,
            "final_answer": str(variant["correct_choice_index"]),
            "correct_choice_index": variant["correct_choice_index"],
            "correct_choice_value": revised_choices[variant["correct_choice_index"] - 1],
            "solution_steps": variant["solution_steps"],
            "solution_summary": variant["revised_summary"],
        }
    )


def _build_probability_cases_blueprint(spec: ExamSpec, atom: InsightAtom) -> ItemBlueprint:
    slot = _slot(spec, 23)
    return slot.model_copy(
        update={
            "objective": "조건 사건 표 정리를 통한 조건부확률 계산",
            "skill_tags": _skill_tags_with_prerequisites(
                base=["conditional_probability", "sample_space_partition"],
                atom=atom,
            ),
            "answer_type": "reduced_fraction",
        }
    )


def _draft_probability_cases_short(blueprint: ItemBlueprint, atom: InsightAtom) -> DraftItem:
    variant = _probability_cases_variant(atom)
    return DraftItem(
        blueprint=blueprint,
        stem=variant["stem"],
        rubric="조건 사건에 해당하는 집단만 다시 모아 분모를 정하고, 그중 목표 집단의 수를 분자로 둔다.",
        answer_constraints=["reduced_fraction"],
    )


def _solve_probability_cases_short(draft: DraftItem, atom: InsightAtom) -> SolvedItem:
    variant = _probability_cases_variant(atom)
    return SolvedItem(
        draft=draft,
        final_answer=variant["answer"],
        solution_steps=variant["solution_steps"],
        solution_summary=variant["summary"],
    )


def _critique_probability_cases_short(
    solved: SolvedItem,
    atom: InsightAtom,
) -> CritiqueReport:
    del atom
    return CritiqueReport(
        item_no=solved.draft.blueprint.item_no,
        summary="수학은 맞지만 요약에 분모가 무엇인지 한 번 더 명시하면 가독성이 좋아진다.",
        findings=[
            CritiqueFinding(
                severity=ValidationSeverity.WARNING,
                message="요약에서 조건 사건의 분모가 가입 학생 전체 10명이라는 점이 조금 더 선명하면 좋다.",
                recommendation="solution_summary에 '가입 학생 10명'을 직접 써 준다.",
                blocking=False,
            )
        ],
        requires_revision=True,
    )


def _revise_probability_cases_short(
    solved: SolvedItem,
    critique: CritiqueReport,
    atom: InsightAtom,
) -> SolvedItem:
    del critique
    variant = _probability_cases_variant(atom)
    return solved.model_copy(
        update={"solution_summary": variant["revised_summary"]}
    )


def _build_probability_ratio_blueprint(spec: ExamSpec, atom: InsightAtom) -> ItemBlueprint:
    slot = _slot(spec, 24)
    return slot.model_copy(
        update={
            "objective": "조건부확률 비율식 직접 적용",
            "skill_tags": _skill_tags_with_prerequisites(
                base=["conditional_probability", "probability_ratio"],
                atom=atom,
            ),
            "answer_type": "reduced_fraction",
        }
    )


def _draft_probability_ratio_short(blueprint: ItemBlueprint, atom: InsightAtom) -> DraftItem:
    del atom
    return DraftItem(
        blueprint=blueprint,
        stem="사건 A, B에 대하여 P(A∩B)=4/15, P(B)=2/5 이다. P(A|B)를 기약분수로 구하시오.",
        rubric="조건부확률의 정의 P(A|B)=P(A∩B)/P(B)를 그대로 적용한 뒤 기약분수로 정리한다.",
        answer_constraints=["reduced_fraction"],
    )


def _solve_probability_ratio_short(draft: DraftItem, atom: InsightAtom) -> SolvedItem:
    del atom
    return SolvedItem(
        draft=draft,
        final_answer="2/3",
        solution_steps=[
            "조건부확률의 정의에 따라 P(A|B)=P(A∩B)/P(B) 이므로 먼저 비율식을 그대로 쓴다.",
            "주어진 값을 대입하면 P(A|B)=(4/15)/(2/5) 이다.",
            "분수의 나눗셈은 역수를 곱하는 것이므로 (4/15)\\times(5/2)=20/30=2/3 이다.",
            "따라서 답은 2/3이다.",
        ],
        solution_summary="정의식 P(A|B)=P(A∩B)/P(B)에 값을 대입해 정리하면 2/3이 된다.",
    )


def _critique_probability_ratio_short(
    solved: SolvedItem,
    atom: InsightAtom,
) -> CritiqueReport:
    del atom
    return CritiqueReport(
        item_no=solved.draft.blueprint.item_no,
        summary="풀이는 맞지만 요약과 단계에서 조건부확률 기호를 조금 더 일관되게 보이는 편이 좋다.",
        findings=[
            CritiqueFinding(
                severity=ValidationSeverity.WARNING,
                message="마지막 요약에 P(A|B) 기호를 다시 적어 주면 식의 대응이 더 또렷해진다.",
                recommendation="solution_summary를 P(A|B)=2/3 형태가 보이도록 고친다.",
                blocking=False,
            )
        ],
        requires_revision=True,
    )


def _revise_probability_ratio_short(
    solved: SolvedItem,
    critique: CritiqueReport,
    atom: InsightAtom,
) -> SolvedItem:
    del critique, atom
    return solved.model_copy(
        update={
            "solution_summary": "정의식 P(A|B)=P(A∩B)/P(B)에 값을 대입하면 P(A|B)=2/3 이다."
        }
    )
